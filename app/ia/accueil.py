"""Réponses entrantes des clients : le classifieur propose, l'humain dispose.

1. `recevoir` enregistre le message ; si l'IA est active, le classifieur local propose une catégorie, une
   confiance, une date de paiement évoquée et signale un litige possible (seuil bas : priorité au rappel).
2. `confirmer` : un humain retient la catégorie (proposée ou corrigée) ; c'est seulement alors que la réponse
   produit ses effets (promesse qui suspend les relances, litige déclaré…), via reponses.enregistrer.
Aucune proposition ne modifie seule une facture.
"""
from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime, timezone

from app import journal, parametres, reponses
from app.db import transaction
from app.erreurs import ErreurMetier, exiger_motif
from app.ia import classification

CORRESPONDANCE = {"promesse": "promesse", "paiement_annonce": "paiement_annonce", "litige": "litige",
                  "demande_delai": "demande_delai", "demande_info": "demande_info", "sans_rapport": "sans_rapport"}


def _maintenant() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def recevoir(conn: sqlite3.Connection, client_id: int, texte: str, auteur: str, facture_id: int | None = None) -> dict:
    texte = (texte or "").strip()
    if not texte:
        raise ErreurMetier("TEXTE_VIDE", "Collez le message reçu du client")
    if len(texte) > 2000:
        raise ErreurMetier("TEXTE_TROP_LONG", "Message trop long (2 000 caractères au maximum)")
    if not conn.execute("SELECT 1 FROM clients WHERE id = ?", (client_id,)).fetchone():
        raise ErreurMetier("INTROUVABLE", "Client introuvable")
    if facture_id is not None and not conn.execute("SELECT 1 FROM factures WHERE id = ? AND client_id = ?",
                                                   (facture_id, client_id)).fetchone():
        raise ErreurMetier("FACTURE_INCONNUE", "Cette facture n'appartient pas à ce client")
    proposition = None
    if parametres.lire(conn, "ia_active"):
        debut = time.perf_counter()
        p = classification.classer(texte)
        date_evoquee = classification.extraire_date(texte, parametres.date_du_jour(conn))
        litige_possible = p.probabilites.get("litige", 0) >= parametres.lire(conn, "ia_seuil_litige")
        proposition = {"categorie": p.categorie, "confiance": p.confiance, "probabilites": p.probabilites,
                       "date": date_evoquee.isoformat() if date_evoquee else None, "litige_possible": litige_possible,
                       "mots_decisifs": p.mots_decisifs,
                       "confiance_faible": p.confiance < parametres.lire(conn, "ia_seuil_confiance"),
                       "duree_ms": int((time.perf_counter() - debut) * 1000)}
    with transaction(conn):
        rid = conn.execute(
            "INSERT INTO reponses_entrantes (client_id, facture_id, texte, recue_le, categorie_proposee, confiance,"
            " probabilites, date_proposee, litige_possible) VALUES (?,?,?,?,?,?,?,?,?)",
            (client_id, facture_id, texte, _maintenant(), proposition and proposition["categorie"],
             proposition and proposition["confiance"],
             json.dumps(proposition["probabilites"]) if proposition else None,
             proposition and proposition["date"], int(bool(proposition and proposition["litige_possible"])))).lastrowid
        if proposition:
            conn.execute("INSERT INTO ia_appels (horodatage, fonction, fournisseur, modele, objet, entree, sortie, statut,"
                         " duree_ms) VALUES (?, 'classification', 'local', ?, ?, ?, ?, 'accepte', ?)",
                         (_maintenant(), classification.VERSION_MODELE, f"reponse:{rid}",
                          json.dumps({"texte": texte}, ensure_ascii=False),
                          json.dumps({k: v for k, v in proposition.items() if k != "duree_ms"}, ensure_ascii=False),
                          proposition["duree_ms"]))
        journal.ajouter(conn, acteur=auteur, type_acteur="humain", action="reponse_recue", objet_type="client",
                        objet_id=client_id,
                        apres={"reponse_entrante": rid, "facture_id": facture_id,
                               "proposition": proposition and proposition["categorie"],
                               "confiance": proposition and proposition["confiance"]},
                        regle="IA_CLASSIFICATION" if proposition else "SAISIE")
    return {"id": rid, "proposition": proposition}


def confirmer(conn: sqlite3.Connection, entrante_id: int, categorie: str, auteur: str, *,
              facture_id: int | None = None, date_promise: str | None = None) -> dict:
    if categorie not in CORRESPONDANCE:
        raise ErreurMetier("TYPE_INVALIDE", "Catégorie inconnue")
    e = conn.execute("SELECT * FROM reponses_entrantes WHERE id = ?", (entrante_id,)).fetchone()
    if e is None:
        raise ErreurMetier("INTROUVABLE", "Réponse introuvable")
    if e["statut"] != "a_traiter":
        raise ErreurMetier("DEJA_TRAITEE", "Cette réponse a déjà été traitée")
    facture_id = facture_id or e["facture_id"]
    reponse_id = reponses.enregistrer(conn, e["client_id"], CORRESPONDANCE[categorie], auteur, facture_id=facture_id,
                                      date_promise=date_promise, texte=e["texte"])
    statut = "confirmee" if categorie == e["categorie_proposee"] else "corrigee"
    with transaction(conn):
        conn.execute("UPDATE reponses_entrantes SET statut = ?, categorie_retenue = ?, traitee_par = ?, traitee_le = ?,"
                     " reponse_id = ? WHERE id = ?", (statut, categorie, auteur, _maintenant(), reponse_id, entrante_id))
        journal.ajouter(conn, acteur=auteur, type_acteur="humain", action=f"reponse_{statut}", objet_type="client",
                        objet_id=e["client_id"],
                        apres={"reponse_entrante": entrante_id, "proposee": e["categorie_proposee"],
                               "retenue": categorie, "facture_id": facture_id},
                        regle="IA_CLASSIFICATION_VALIDEE")
    return {"statut": statut, "reponse_id": reponse_id}


def ecarter(conn: sqlite3.Connection, entrante_id: int, auteur: str, motif: str | None) -> None:
    motif = exiger_motif(motif)
    with transaction(conn):
        n = conn.execute("UPDATE reponses_entrantes SET statut = 'ecartee', traitee_par = ?, traitee_le = ?"
                         " WHERE id = ? AND statut = 'a_traiter'", (auteur, _maintenant(), entrante_id)).rowcount
        if not n:
            raise ErreurMetier("NON_APPLICABLE", "Réponse introuvable ou déjà traitée")
        journal.ajouter(conn, acteur=auteur, type_acteur="humain", action="reponse_ecartee", objet_type="reponse",
                        objet_id=entrante_id, apres={"motif": motif}, regle="SAISIE")
