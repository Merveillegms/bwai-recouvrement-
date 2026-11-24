"""Décisions humaines sur les anomalies d'import. Chaque décision est motivée et journalisée.

- Conflit de numéro : garder la facture en base (ignorer la ligne) ou la remplacer par la ligne importée.
- Doublon exact / déjà importé : simple prise de connaissance (ignorer).
- Facture « à vérifier » : confirmer (le doute est levé) ou annuler comme doublon (clôture).
- Client en attente : compléter et valider la fiche.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from app import calculs, journal, parametres
from app.db import transaction
from app.importer import Anomalie, lire_ligne_facture

CANAUX = ("sms", "whatsapp", "email")


class ResolutionImpossible(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code, self.message = code, message


def _exiger_motif(motif: str | None) -> str:
    if not motif or not motif.strip():
        raise ResolutionImpossible("MOTIF_OBLIGATOIRE", "Un motif est obligatoire pour cette décision")
    return motif.strip()


def _maintenant() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _facture_engagee(conn: sqlite3.Connection, facture_id: int) -> str | None:
    """Raison pour laquelle une facture ne peut plus être modifiée, ou None."""
    if conn.execute("SELECT 1 FROM paiements WHERE facture_id = ? AND statut_rapprochement = 'rapproche'",
                    (facture_id,)).fetchone():
        return "des paiements y sont déjà rapprochés"
    if conn.execute("SELECT 1 FROM relances WHERE facture_id = ? AND statut IN ('en_cours_envoi', 'envoyee')",
                    (facture_id,)).fetchone():
        return "une relance a déjà été envoyée"
    return None


def resoudre_anomalie(conn: sqlite3.Connection, anomalie_id: int, decision: str, auteur: str,
                      motif: str | None = None) -> dict:
    if decision not in ("ignorer", "remplacer"):
        raise ResolutionImpossible("DECISION_INVALIDE", "Décision attendue : ignorer ou remplacer")
    with transaction(conn):
        a = conn.execute("SELECT * FROM import_anomalies WHERE id = ?", (anomalie_id,)).fetchone()
        if a is None:
            raise ResolutionImpossible("INTROUVABLE", "Anomalie introuvable")
        if a["resolution"] is not None:
            raise ResolutionImpossible("DEJA_RESOLUE", f"Anomalie déjà résolue ({a['resolution']}) par {a['resolu_par']}")
        if a["gravite"] != "rejet":
            raise ResolutionImpossible("NON_APPLICABLE",
                                       "Un avertissement se traite sur la facture (confirmer ou annuler)")
        apres: dict = {"decision": decision}
        if decision == "remplacer":
            motif = _exiger_motif(motif)
            if a["code"] != "CONFLIT_NUMERO":
                raise ResolutionImpossible("NON_APPLICABLE", "Seul un conflit de numéro peut remplacer une facture")
            devises = {r["code"]: r["decimales"] for r in conn.execute("SELECT code, decimales FROM devises")}
            lue = lire_ligne_facture(a["ligne"], json.loads(a["donnees"]), devises)
            if isinstance(lue, Anomalie):
                raise ResolutionImpossible("LIGNE_INVALIDE", lue.message)
            existante = conn.execute(
                "SELECT f.* FROM factures f JOIN clients c ON c.id = f.client_id WHERE c.code = ? AND f.numero = ?",
                (lue.code_client, lue.numero)).fetchone()
            if existante is None:
                raise ResolutionImpossible("INTROUVABLE", "La facture en conflit n'existe plus")
            if raison := _facture_engagee(conn, existante["id"]):
                raise ResolutionImpossible("FACTURE_ENGAGEE", f"Remplacement impossible : {raison}")
            statut = calculs.statut(montant_ttc=lue.montant, total_paye=0, echeance=lue.echeance,
                                    reference=parametres.date_du_jour(conn), en_litige=lue.litige,
                                    suspendue=bool(existante["suspendue"]))
            conn.execute(
                "UPDATE factures SET date_emission=?, date_echeance=?, montant_ttc=?, devise=?, en_litige=?, statut=?,"
                " version = version + 1, maj_le = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id = ?",
                (lue.emission.isoformat(), lue.echeance.isoformat(), lue.montant, lue.devise, int(lue.litige), statut,
                 existante["id"]))
            journal.ajouter(conn, acteur=auteur, type_acteur="humain", action="remplacement_facture",
                            objet_type="facture", objet_id=f"{lue.code_client}/{lue.numero}",
                            avant={k: existante[k] for k in ("date_emission", "date_echeance", "montant_ttc",
                                                              "devise", "en_litige", "statut")},
                            apres={"date_emission": lue.emission.isoformat(), "date_echeance": lue.echeance.isoformat(),
                                   "montant_ttc": lue.montant, "devise": lue.devise, "en_litige": int(lue.litige),
                                   "statut": statut, "motif": motif},
                            regle="RESOLUTION_CONFLIT_NUMERO")
            apres["facture_id"] = existante["id"]
        conn.execute("UPDATE import_anomalies SET resolution=?, motif_resolution=?, resolu_par=?, resolu_le=?"
                     " WHERE id=?", ("remplacee" if decision == "remplacer" else "ignoree", motif, auteur,
                                     _maintenant(), anomalie_id))
        journal.ajouter(conn, acteur=auteur, type_acteur="humain", action="resolution_anomalie",
                        objet_type="anomalie", objet_id=anomalie_id, avant={"code": a["code"], "ligne": a["ligne"]},
                        apres=apres | {"motif": motif}, regle=a["code"])
    return apres


def confirmer_facture(conn: sqlite3.Connection, facture_id: int, auteur: str, motif: str | None = None) -> None:
    """Le doute est levé : la facture redevient relançable normalement."""
    with transaction(conn):
        f = conn.execute("SELECT * FROM factures WHERE id = ?", (facture_id,)).fetchone()
        if f is None:
            raise ResolutionImpossible("INTROUVABLE", "Facture introuvable")
        if not f["a_verifier"]:
            raise ResolutionImpossible("NON_APPLICABLE", "Cette facture n'est pas à vérifier")
        client = conn.execute("SELECT statut_validation FROM clients WHERE id = ?", (f["client_id"],)).fetchone()
        if client["statut_validation"] == "en_attente":
            raise ResolutionImpossible("CLIENT_EN_ATTENTE", "Validez d'abord la fiche du client")
        conn.execute("UPDATE factures SET a_verifier = 0, motif_verification = NULL, version = version + 1,"
                     " maj_le = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id = ?", (facture_id,))
        journal.ajouter(conn, acteur=auteur, type_acteur="humain", action="confirmation_facture",
                        objet_type="facture", objet_id=facture_id, avant={"a_verifier": f["motif_verification"]},
                        apres={"a_verifier": None, "motif": motif}, regle="VERIFICATION_HUMAINE")


def annuler_facture(conn: sqlite3.Connection, facture_id: int, auteur: str, motif: str) -> None:
    """Facture reconnue comme doublon ou erronée : clôturée, jamais relancée, conservée pour l'audit."""
    motif = _exiger_motif(motif)
    with transaction(conn):
        f = conn.execute("SELECT * FROM factures WHERE id = ?", (facture_id,)).fetchone()
        if f is None:
            raise ResolutionImpossible("INTROUVABLE", "Facture introuvable")
        if f["statut"] == "cloturee":
            raise ResolutionImpossible("DEJA_CLOTUREE", "Facture déjà clôturée")
        if raison := _facture_engagee(conn, facture_id):
            raise ResolutionImpossible("FACTURE_ENGAGEE", f"Annulation impossible : {raison}")
        conn.execute("UPDATE factures SET statut = 'cloturee', motif_cloture = ?, a_verifier = 0, version = version + 1,"
                     " maj_le = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id = ?", (motif, facture_id))
        journal.ajouter(conn, acteur=auteur, type_acteur="humain", action="annulation_facture",
                        objet_type="facture", objet_id=facture_id, avant={"statut": f["statut"]},
                        apres={"statut": "cloturee", "motif": motif}, regle="VERIFICATION_HUMAINE")


def valider_client(conn: sqlite3.Connection, client_id: int, auteur: str, *, nom: str, telephone: str | None = None,
                   email: str | None = None, canal_prefere: str = "sms", sensible: bool = False) -> int:
    """Complète un client créé en attente. Lève le doute sur ses factures dont c'était le seul motif.
    Retourne le nombre de factures libérées."""
    if not nom or not nom.strip():
        raise ResolutionImpossible("CHAMP_MANQUANT", "Le nom du client est obligatoire")
    if canal_prefere not in CANAUX:
        raise ResolutionImpossible("CANAL_INVALIDE", "Canal attendu : sms, whatsapp ou email")
    with transaction(conn):
        c = conn.execute("SELECT * FROM clients WHERE id = ?", (client_id,)).fetchone()
        if c is None:
            raise ResolutionImpossible("INTROUVABLE", "Client introuvable")
        if c["statut_validation"] != "en_attente":
            raise ResolutionImpossible("NON_APPLICABLE", "Ce client est déjà validé")
        conn.execute("UPDATE clients SET nom=?, telephone=?, email=?, canal_prefere=?, sensible=?,"
                     " statut_validation='valide' WHERE id=?",
                     (nom.strip(), telephone or None, email or None, canal_prefere, int(sensible), client_id))
        liberees = conn.execute(
            "UPDATE factures SET a_verifier = 0, motif_verification = NULL, version = version + 1,"
            " maj_le = strftime('%Y-%m-%dT%H:%M:%fZ','now')"
            " WHERE client_id = ? AND motif_verification = 'CLIENT_INCONNU'", (client_id,)).rowcount
        conn.execute("UPDATE factures SET motif_verification = trim(replace(replace(motif_verification,"
                     " 'CLIENT_INCONNU,', ''), ',CLIENT_INCONNU', ''))"
                     " WHERE client_id = ? AND motif_verification LIKE '%CLIENT_INCONNU%'", (client_id,))
        journal.ajouter(conn, acteur=auteur, type_acteur="humain", action="validation_client", objet_type="client",
                        objet_id=c["code"], avant={"statut_validation": "en_attente"},
                        apres={"nom": nom.strip(), "canal": canal_prefere, "factures_liberees": liberees},
                        regle="CLIENT_INCONNU")
    return liberees
