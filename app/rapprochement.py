"""Rapprochement des paiements avec les factures (docs/regles_metier.md § 8).

Seul un cas est appliqué automatiquement : une référence valide, connue, sur une facture ouverte
de même devise. Tout le reste est mis « à valider » avec un motif et, si possible, une proposition.
Aucun rapprochement ambigu n'est jamais appliqué sans humain.
"""
from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone

from app import etat as moteur
from app import journal, statuts
from app.db import transaction
from app.erreurs import ErreurMetier, exiger_motif
from app.references import normaliser_reference, reference_valide

_RESSEMBLE_A_UNE_REFERENCE = re.compile(r"^RC\d")


def _maintenant() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def numero_court(telephone: str | None) -> str | None:
    """8 derniers chiffres : rapproche +229 0190000001, 0190000001 et l'ancien format à 8 chiffres."""
    chiffres = re.sub(r"\D", "", telephone or "")
    return chiffres[-8:] if len(chiffres) >= 8 else None


def _candidats_montant(conn, paiement, ctx) -> list[moteur.EtatFacture]:
    """Factures ouvertes du client payeur (identifié par téléphone) dont le solde égale le montant payé."""
    court = numero_court(paiement["telephone_payeur"])
    if court is None:
        return []
    clients = [c["id"] for c in conn.execute("SELECT id, telephone FROM clients WHERE telephone IS NOT NULL")
               if numero_court(c["telephone"]) == court]
    if not clients:
        return []
    marques = ",".join("?" * len(clients))
    return [e for e in moteur.etats(conn, f"f.client_id IN ({marques}) AND f.devise = ?",
                                    (*clients, paiement["devise"]), ctx)
            if e.statut not in moteur.STATUTS_SOLDES and e.solde == paiement["montant"]]


def _mettre_a_valider(conn, paiement, code: str, proposee: int | None, auteur: str) -> str:
    conn.execute("UPDATE paiements SET statut_rapprochement = 'a_valider', motif_rapprochement = ?,"
                 " facture_proposee_id = ? WHERE id = ?", (code, proposee, paiement["id"]))
    journal.ajouter(conn, acteur=auteur, type_acteur="systeme", action="rapprochement_a_valider",
                    objet_type="paiement", objet_id=paiement["id_transaction"],
                    apres={"motif": code, "facture_proposee": proposee}, regle=code)
    return code


def _rapprocher(conn, paiement, facture_id: int, methode: str, auteur: str, type_acteur: str,
                ctx: moteur.Contexte | None) -> None:
    conn.execute("UPDATE paiements SET statut_rapprochement = 'rapproche', facture_id = ?, methode_rapprochement = ?,"
                 " motif_rapprochement = NULL, rapproche_par = ?, rapproche_le = ? WHERE id = ?",
                 (facture_id, methode, auteur, _maintenant(), paiement["id"]))
    journal.ajouter(conn, acteur=auteur, type_acteur=type_acteur, action="rapprochement", objet_type="paiement",
                    objet_id=paiement["id_transaction"],
                    apres={"facture_id": facture_id, "montant": paiement["montant"], "methode": methode},
                    regle=f"RAPPROCHEMENT_{methode.upper()}")
    statuts.actualiser(conn, facture_id, auteur=auteur, type_acteur=type_acteur,
                       regle=f"RAPPROCHEMENT_{methode.upper()}", ctx=ctx, donnees_modifiees=True)


def _traiter(conn, p, ctx, auteur) -> str:
    reference = normaliser_reference(p["reference_citee"] or "")
    if _RESSEMBLE_A_UNE_REFERENCE.match(reference):
        if not reference_valide(reference):
            candidats = _candidats_montant(conn, p, ctx)
            return _mettre_a_valider(conn, p, "REFERENCE_INVALIDE",
                                     candidats[0].id if len(candidats) == 1 else None, auteur)
        facture = conn.execute("SELECT id FROM factures WHERE reference_paiement = ?", (reference,)).fetchone()
        if facture is None:
            return _mettre_a_valider(conn, p, "REFERENCE_INCONNUE", None, auteur)
        e = moteur.etat(conn, facture["id"], ctx)
        if e.devise != p["devise"]:
            return _mettre_a_valider(conn, p, "DEVISE_DIFFERENTE", e.id, auteur)
        if e.statut == "cloturee":
            return _mettre_a_valider(conn, p, "FACTURE_CLOTUREE", e.id, auteur)
        if e.solde == 0:
            return _mettre_a_valider(conn, p, "FACTURE_DEJA_SOLDEE", e.id, auteur)
        _rapprocher(conn, p, e.id, "reference", "systeme", "systeme", ctx)
        return "RAPPROCHE"
    candidats = _candidats_montant(conn, p, ctx)
    if len(candidats) == 1:
        return _mettre_a_valider(conn, p, "PROPOSITION_MONTANT_CLIENT", candidats[0].id, auteur)
    if len(candidats) > 1:
        return _mettre_a_valider(conn, p, "RAPPROCHEMENT_AMBIGU", None, auteur)
    return _mettre_a_valider(conn, p, "NON_IDENTIFIE", None, auteur)


def rapprocher_tout(conn: sqlite3.Connection, auteur: str = "systeme") -> dict[str, int]:
    """Traite les paiements non rapprochés. Idempotent : relancé, il ne retraite rien.
    Les paiements avec référence passent d'abord, pour que les propositions par montant
    portent sur des soldes à jour."""
    resume: dict[str, int] = {}
    with transaction(conn):
        ctx = moteur.contexte(conn)
        attente = conn.execute("SELECT * FROM paiements WHERE statut_rapprochement = 'non_rapproche' ORDER BY id").fetchall()
        def a_une_reference(p) -> bool:
            return bool(_RESSEMBLE_A_UNE_REFERENCE.match(normaliser_reference(p["reference_citee"] or "")))

        ordre = sorted(attente, key=lambda p: (not a_une_reference(p), p["id"]))
        for p in ordre:
            code = _traiter(conn, p, ctx, auteur)
            resume[code] = resume.get(code, 0) + 1
    return resume


# ------------------------------------------------------------------ décisions humaines
def _paiement(conn, paiement_id: int) -> sqlite3.Row:
    p = conn.execute("SELECT * FROM paiements WHERE id = ?", (paiement_id,)).fetchone()
    if p is None:
        raise ErreurMetier("INTROUVABLE", "Paiement introuvable")
    return p


def valider_paiement(conn: sqlite3.Connection, paiement_id: int, auteur: str, facture_id: int | None = None,
                     motif: str | None = None) -> moteur.EtatFacture:
    """Confirme la proposition, ou affecte le paiement à une autre facture (motif alors obligatoire)."""
    with transaction(conn):
        p = _paiement(conn, paiement_id)
        if p["statut_rapprochement"] != "a_valider":
            raise ErreurMetier("NON_APPLICABLE", "Ce paiement n'est pas en attente de validation")
        cible = facture_id or p["facture_proposee_id"]
        if cible is None:
            raise ErreurMetier("FACTURE_REQUISE", "Aucune proposition : indiquez la facture à créditer")
        if cible != p["facture_proposee_id"]:
            motif = exiger_motif(motif)
        e = moteur.etat(conn, cible)
        if e is None:
            raise ErreurMetier("INTROUVABLE", "Facture introuvable")
        if e.devise != p["devise"]:
            raise ErreurMetier("DEVISE_DIFFERENTE", "La devise du paiement ne correspond pas à celle de la facture")
        if e.statut == "cloturee":
            raise ErreurMetier("DEJA_CLOTUREE", "Facture clôturée : affectation impossible")
        journal.ajouter(conn, acteur=auteur, type_acteur="humain", action="validation_rapprochement",
                        objet_type="paiement", objet_id=p["id_transaction"],
                        avant={"motif": p["motif_rapprochement"], "proposee": p["facture_proposee_id"]},
                        apres={"facture_id": cible, "motif": motif}, regle=p["motif_rapprochement"])
        _rapprocher(conn, p, cible, "manuelle", auteur, "humain", None)
        return moteur.etat(conn, cible)


def rejeter_paiement(conn: sqlite3.Connection, paiement_id: int, auteur: str, motif: str | None) -> None:
    """Paiement étranger à nos factures (erreur de destinataire, remboursé…) : écarté, conservé pour l'audit."""
    motif = exiger_motif(motif)
    with transaction(conn):
        p = _paiement(conn, paiement_id)
        if p["statut_rapprochement"] not in ("a_valider", "non_rapproche"):
            raise ErreurMetier("NON_APPLICABLE", "Seul un paiement non rapproché peut être rejeté")
        conn.execute("UPDATE paiements SET statut_rapprochement = 'rejete', rapproche_par = ?, rapproche_le = ?"
                     " WHERE id = ?", (auteur, _maintenant(), paiement_id))
        journal.ajouter(conn, acteur=auteur, type_acteur="humain", action="rejet_paiement", objet_type="paiement",
                        objet_id=p["id_transaction"], avant={"statut": p["statut_rapprochement"]},
                        apres={"statut": "rejete", "motif": motif}, regle="REJET_PAIEMENT")


def annuler_rapprochement(conn: sqlite3.Connection, paiement_id: int, auteur: str, motif: str | None) -> None:
    """Défait un rapprochement erroné : le paiement repart à valider, la facture retrouve son solde."""
    motif = exiger_motif(motif)
    with transaction(conn):
        p = _paiement(conn, paiement_id)
        if p["statut_rapprochement"] != "rapproche":
            raise ErreurMetier("NON_APPLICABLE", "Ce paiement n'est pas rapproché")
        conn.execute("UPDATE paiements SET statut_rapprochement = 'a_valider', facture_id = NULL,"
                     " facture_proposee_id = ?, motif_rapprochement = 'ANNULATION', methode_rapprochement = NULL"
                     " WHERE id = ?", (p["facture_id"], paiement_id))
        journal.ajouter(conn, acteur=auteur, type_acteur="humain", action="annulation_rapprochement",
                        objet_type="paiement", objet_id=p["id_transaction"], avant={"facture_id": p["facture_id"]},
                        apres={"facture_id": None, "motif": motif}, regle="ANNULATION_RAPPROCHEMENT")
        statuts.actualiser(conn, p["facture_id"], auteur=auteur, type_acteur="humain",
                           regle="ANNULATION_RAPPROCHEMENT", donnees_modifiees=True)
