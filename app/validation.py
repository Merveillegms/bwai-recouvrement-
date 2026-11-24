"""File de validation humaine des lots de relances (docs/regles_metier.md § 11).

Décisions (rôle validateur uniquement) :
- approuver : le lot est revalidé (état réel + message) puis passe « validé » ;
- modifier : le texte proposé repasse par la vérification automatique, puis le lot est validé ;
- suspendre (motif) : lot annulé et factures suspendues ;
- rejeter (motif) : lot annulé ; l'étape n'est plus proposée pour ces factures (clé conservée).
Validation groupée : les lots « ordinaires » (seul motif : étape R3) s'approuvent en une action ;
chaque lot reste revalidé et journalisé individuellement.
Chaque décision enregistre le décideur, l'heure et le contenu exact approuvé.
"""
from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timezone

from app import etat as moteur
from app import garde_fous, journal, statuts
from app.db import transaction
from app.erreurs import ErreurMetier, exiger_motif

MOTIF_GROUPABLE = "étape soumise à validation (R3)"


def _maintenant() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _exiger_validateur(decideur: dict) -> None:
    if decideur.get("role") != "validateur":
        raise ErreurMetier("VALIDATEUR_REQUIS", "Cette décision est réservée au validateur")


def _relances_du_lot(conn, lot: str) -> list[sqlite3.Row]:
    relances = conn.execute("SELECT * FROM relances WHERE lot_envoi = ? AND statut <> 'annulee' ORDER BY id",
                            (lot,)).fetchall()
    if not relances:
        raise ErreurMetier("INTROUVABLE", "Lot introuvable")
    if any(r["statut"] != "a_valider" for r in relances):
        raise ErreurMetier("NON_APPLICABLE", "Ce lot n'est pas en attente de validation")
    return relances


def est_groupable(relances: list[sqlite3.Row]) -> bool:
    motifs = (relances[0]["motif_validation"] or "").split("; ")
    return relances[0]["etape"] != "R5" and all(m == MOTIF_GROUPABLE for m in motifs)


def file_de_validation(conn: sqlite3.Connection) -> list[dict]:
    ctx = moteur.contexte(conn)
    lots: dict[str, list[sqlite3.Row]] = {}
    for r in conn.execute("SELECT * FROM relances WHERE statut = 'a_valider' ORDER BY id"):
        lots.setdefault(r["lot_envoi"], []).append(r)
    resultat = []
    for lot, relances in lots.items():
        client = conn.execute("SELECT id, code, nom, canal_prefere, sensible FROM clients WHERE id = ?",
                              (relances[0]["client_id"],)).fetchone()
        resultat.append({
            "lot": lot, "client": dict(client), "canal": relances[0]["canal"],
            "escalade": relances[0]["etape"] == "R5", "message": relances[0]["message"],
            "raisons": (relances[0]["motif_validation"] or "").split("; "),
            "groupable": est_groupable(relances), "date_preparation": relances[0]["date_preparation"],
            "factures": [moteur.etat(conn, r["facture_id"], ctx).en_dict() | {"etape": r["etape"]} for r in relances],
        })
    return resultat


def _enregistrer_decision(conn, relances, decideur: dict, decision: str, motif: str | None,
                          contenu: str | None) -> None:
    for r in relances:
        conn.execute("INSERT INTO validations (relance_id, decideur_id, decision, motif, contenu_approuve, decide_le)"
                     " VALUES (?,?,?,?,?,?)", (r["id"], decideur["id"], decision, motif, contenu, _maintenant()))
    journal.ajouter(conn, acteur=decideur["identifiant"], type_acteur="humain", action=f"validation_{decision}",
                    objet_type="lot", objet_id=relances[0]["lot_envoi"],
                    apres={"decision": decision, "motif": motif, "relances": [r["id"] for r in relances],
                           "empreinte_contenu": hashlib.sha256(contenu.encode()).hexdigest() if contenu else None},
                    regle="VALIDATION_HUMAINE")


def approuver(conn: sqlite3.Connection, lot: str, decideur: dict, contenu: str | None = None,
              motif: str | None = None) -> dict:
    """Approuve le lot, éventuellement avec un message modifié. Un lot périmé est annulé, pas approuvé."""
    _exiger_validateur(decideur)
    with transaction(conn):
        relances = _relances_du_lot(conn, lot)
        message = relances[0]["message"]
        if contenu is not None:
            contenu = contenu.replace("\r\n", "\n").strip()
            if relances[0]["etape"] == "R5":
                raise ErreurMetier("NON_APPLICABLE", "Un dossier d'escalade ne se modifie pas")
            objet = message.partition("\n\n")[0] + "\n\n" if message.startswith("Objet : ") else ""
            message = objet + contenu
        raisons = garde_fous.revalider_lot(conn, relances, message=message)
        if raisons and contenu is not None and all(r.startswith("message :") for r in raisons):
            raise ErreurMetier("MESSAGE_NON_CONFORME", "Message modifié refusé : " + "; ".join(
                r.removeprefix("message : ") for r in raisons))
        if raisons and all(r.startswith("message :") for r in raisons):
            raise ErreurMetier("MESSAGE_A_CORRIGER", "Le message doit être modifié avant approbation : " + "; ".join(
                r.removeprefix("message : ") for r in raisons))
        if raisons:
            garde_fous.annuler_lot(conn, lot, raisons, decideur["identifiant"], "humain", "REVALIDATION_A_L_APPROBATION")
            return {"lot": lot, "statut": "annulee", "raisons": raisons}
        decision = "modifier" if contenu is not None and message != relances[0]["message"] else "approuver"
        conn.execute("UPDATE relances SET statut = 'validee', message = ?, maj_le = ? WHERE lot_envoi = ?"
                     " AND statut = 'a_valider'", (message, _maintenant(), lot))
        _enregistrer_decision(conn, relances, decideur, decision, motif, message)
    return {"lot": lot, "statut": "validee", "decision": decision}


def rejeter(conn: sqlite3.Connection, lot: str, decideur: dict, motif: str | None) -> dict:
    _exiger_validateur(decideur)
    motif = exiger_motif(motif)
    with transaction(conn):
        relances = _relances_du_lot(conn, lot)
        conn.execute("UPDATE relances SET statut = 'annulee', motif_annulation = ?, maj_le = ? WHERE lot_envoi = ?"
                     " AND statut = 'a_valider'", (f"Rejet : {motif}", _maintenant(), lot))
        _enregistrer_decision(conn, relances, decideur, "rejeter", motif, None)
    return {"lot": lot, "statut": "annulee"}


def suspendre(conn: sqlite3.Connection, lot: str, decideur: dict, motif: str | None) -> dict:
    _exiger_validateur(decideur)
    motif = exiger_motif(motif)
    with transaction(conn):
        relances = _relances_du_lot(conn, lot)
        conn.execute("UPDATE relances SET statut = 'annulee', motif_annulation = ?, maj_le = ?,"
                     " cle_idempotence = cle_idempotence || '#suspendue-' || id WHERE lot_envoi = ?"
                     " AND statut = 'a_valider'", (f"Suspension : {motif}", _maintenant(), lot))
        _enregistrer_decision(conn, relances, decideur, "suspendre", motif, None)
    for r in relances:  # chaque facture est suspendue (décision humaine journalisée, transaction propre)
        if moteur.etat(conn, r["facture_id"]).statut not in ("suspendue", "cloturee"):
            statuts.suspendre(conn, r["facture_id"], decideur["identifiant"], motif)
    return {"lot": lot, "statut": "annulee", "factures_suspendues": [r["facture_id"] for r in relances]}


def lots_groupables(conn: sqlite3.Connection) -> list[str]:
    lots: dict[str, list] = {}
    for r in conn.execute("SELECT * FROM relances WHERE statut = 'a_valider' ORDER BY id"):
        lots.setdefault(r["lot_envoi"], []).append(r)
    return [lot for lot, relances in lots.items() if est_groupable(relances)]


def approuver_groupe(conn: sqlite3.Connection, lots: list[str], decideur: dict, motif: str | None = None) -> dict:
    """Approbation groupée des lots ordinaires. Les autres sont refusés avec leur raison."""
    _exiger_validateur(decideur)
    groupables = set(lots_groupables(conn))
    resultat: dict[str, list] = {"validees": [], "annulees": [], "refusees": []}
    for lot in lots:
        if lot not in groupables:
            resultat["refusees"].append({"lot": lot, "raison": "lot non ordinaire : à examiner individuellement"})
            continue
        try:
            r = approuver(conn, lot, decideur, motif=motif or "Validation groupée")
        except ErreurMetier as e:
            resultat["refusees"].append({"lot": lot, "raison": e.message})
            continue
        resultat["validees" if r["statut"] == "validee" else "annulees"].append(lot)
    with transaction(conn):
        journal.ajouter(conn, acteur=decideur["identifiant"], type_acteur="humain", action="validation_groupee",
                        objet_type="lots", apres={k: len(v) for k, v in resultat.items()}, regle="VALIDATION_GROUPEE")
    return resultat
