"""Garde-fous de l'envoi (docs/regles_metier.md § 11).

- `verifier_message` : chaque montant, référence et numéro du texte doit correspondre exactement aux
  données calculées ; aucun montant « inventé » ; ton et longueur conformes.
- `revalider_lot` : juste avant l'envoi (ou l'approbation), l'état réel de chaque facture est relu et
  comparé à celui de la préparation. Le moindre écart annule le lot, avec sa raison.
- `reprendre` : après une interruption, chaque lot resté « en cours d'envoi » est vérifié auprès du
  connecteur : envoyé → confirmé ; non envoyé → remis en file. Jamais de second envoi.
"""
from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone

from app import etat as moteur
from app import gabarits, journal, parametres
from app.connecteurs import Connecteur
from app.db import transaction
from app.montants import formater
from app.references import formater_reference

_MONTANT = re.compile(r"\d{1,3}(?: \d{3})*(?:,\d+)? (?:FCFA|EUR)")
_REFERENCE = re.compile(r"RC-\d{4}-\d{4}-\d")
STATUTS_RELANCABLES = ("echue", "partiellement_payee")


def _maintenant() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def verifier_message(texte: str, etats: list[moteur.EtatFacture], canal: str | None = None,
                     escalade: bool = False) -> list[str]:
    """Écarts entre le texte et les données calculées (liste vide = conforme)."""
    ecarts: list[str] = []
    autorises: set[str] = set()
    totaux: dict[str, list] = {}
    for e in etats:
        solde = formater(e.solde, e.devise, e.decimales)
        autorises.add(solde)
        totaux.setdefault(e.devise, [0, e.decimales])[0] += e.solde
        if e.numero not in texte:
            ecarts.append(f"facture {e.numero} absente du message")
        if solde not in texte:
            ecarts.append(f"solde de {e.numero} absent ou différent (attendu {solde})")
        if formater_reference(e.reference_paiement) not in texte:
            ecarts.append(f"référence de {e.numero} absente ou différente")
    autorises |= {formater(m, d, dec) for d, (m, dec) in totaux.items()}
    for montant in sorted(set(_MONTANT.findall(texte)) - autorises):
        ecarts.append(f"montant non justifié par les données : {montant}")
    attendues = {formater_reference(e.reference_paiement) for e in etats}
    for ref in sorted(set(_REFERENCE.findall(texte)) - attendues):
        ecarts.append(f"référence inconnue dans le message : {ref}")
    if not escalade:
        ecarts += [f"ton : {x}" for x in gabarits.controler_ton(texte)]
        if canal and len(texte) > gabarits.LONGUEUR_MAX[canal]:
            ecarts.append(f"message trop long pour {canal}")
    return ecarts


def corps_du_message(message: str) -> str:
    return message.partition("\n\n")[2] if message.startswith("Objet : ") else message


def revalider_lot(conn: sqlite3.Connection, relances: list[sqlite3.Row], ctx: moteur.Contexte | None = None,
                  message: str | None = None) -> list[str]:
    """Raisons d'annuler le lot (liste vide = l'envoi peut partir)."""
    ctx = ctx or moteur.contexte(conn)
    raisons: list[str] = []
    etats = []
    for r in relances:
        e = moteur.etat(conn, r["facture_id"], ctx)
        etats.append(e)
        if e.version != r["version_facture"]:
            raisons.append(f"{e.numero} : facture modifiée depuis la préparation "
                           f"(version {r['version_facture']} → {e.version})")
        if e.solde != r["solde_prepare"]:
            raisons.append(f"{e.numero} : solde changé ({r['solde_prepare']} → {e.solde})")
        if e.statut not in STATUTS_RELANCABLES:
            raisons.append(f"{e.numero} : statut devenu « {e.statut} »")
        if "a_verifier" in e.drapeaux:
            raisons.append(f"{e.numero} : donnée à vérifier")
        if conn.execute("SELECT 1 FROM paiements WHERE statut_rapprochement IN ('a_valider', 'non_rapproche')"
                        " AND facture_proposee_id = ?", (e.id,)).fetchone():
            raisons.append(f"{e.numero} : un paiement en attente de rapprochement la concerne")
    client_id = relances[0]["client_id"]
    if conn.execute("SELECT 1 FROM reponses_client WHERE client_id = ? AND confirme = 1 AND date_promise >= ?"
                    " AND type IN ('promesse', 'demande_delai', 'paiement_annonce')",
                    (client_id, ctx.reference.isoformat())).fetchone():
        raisons.append("le client a fait une promesse de paiement en cours")
    if not raisons:
        escalade = relances[0]["etape"] == "R5"
        texte = message if message is not None else relances[0]["message"]
        raisons += [f"message : {x}" for x in verifier_message(corps_du_message(texte), etats,
                                                               relances[0]["canal"], escalade)]
    return raisons


def annuler_lot(conn: sqlite3.Connection, lot: str, raisons: list[str], auteur: str, type_acteur: str,
                regle: str) -> None:
    """À appeler dans une transaction. La clé d'idempotence est libérée (suffixée, historique conservé) :
    la facture pourra être relancée à la même étape avec ses nouvelles valeurs."""
    motif = "; ".join(raisons)
    conn.execute("UPDATE relances SET statut = 'annulee', motif_annulation = ?, maj_le = ?,"
                 " cle_idempotence = cle_idempotence || '#annulee-' || id"
                 " WHERE lot_envoi = ? AND statut IN ('brouillon', 'a_valider', 'validee', 'en_cours_envoi')",
                 (motif, _maintenant(), lot))
    journal.ajouter(conn, acteur=auteur, type_acteur=type_acteur, action="annulation_lot", objet_type="lot",
                    objet_id=lot, apres={"raisons": raisons}, regle=regle)


def reprendre(conn: sqlite3.Connection, connecteur: Connecteur, auteur: str = "systeme") -> dict[str, int]:
    """Lots interrompus en plein envoi : on demande au connecteur si l'envoi a eu lieu."""
    resultat = {"confirmes": 0, "remis_en_file": 0}
    lots = [r["lot_envoi"] for r in conn.execute(
        "SELECT DISTINCT lot_envoi FROM relances WHERE statut = 'en_cours_envoi'")]
    for lot in lots:
        accuse = connecteur.accuse(lot)
        with transaction(conn):
            if accuse:
                conn.execute("UPDATE messages_sortants SET statut = 'envoye', accuse = ?,"
                             " envoye_le = coalesce(envoye_le, ?) WHERE cle_envoi = ?", (accuse, _maintenant(), lot))
                conn.execute("UPDATE relances SET statut = 'envoyee', maj_le = ?, date_envoi = ?"
                             " WHERE lot_envoi = ? AND statut = 'en_cours_envoi'",
                             (_maintenant(), parametres.date_du_jour(conn).isoformat(), lot))
                journal.ajouter(conn, acteur=auteur, type_acteur="systeme", action="reprise_envoi_confirme",
                                objet_type="lot", objet_id=lot, apres={"accuse": accuse}, regle="REPRISE")
                resultat["confirmes"] += 1
            else:
                conn.execute("UPDATE relances SET statut = 'validee', maj_le = ?"
                             " WHERE lot_envoi = ? AND statut = 'en_cours_envoi'", (_maintenant(), lot))
                journal.ajouter(conn, acteur=auteur, type_acteur="systeme", action="reprise_envoi_non_effectue",
                                objet_type="lot", objet_id=lot, apres={"remis_en_file": True}, regle="REPRISE")
                resultat["remis_en_file"] += 1
    return resultat
