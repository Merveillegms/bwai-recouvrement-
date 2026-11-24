"""Journal d'audit : recherche, export, frise par facture, explication d'une relance.

`expliquer_relance` n'utilise QUE le journal : c'est la preuve que la piste d'audit suffit à reconstituer
pourquoi une relance a été préparée, puis envoyée, bloquée ou annulée.
"""
from __future__ import annotations

import csv
import io
import json
import sqlite3

COLONNES = ("id", "horodatage", "acteur", "type_acteur", "action", "objet_type", "objet_id", "avant", "apres",
            "regle", "hash_precedent", "hash")

_SQL_FACTURE = """
    (objet_type = 'facture' AND objet_id = :fid)
 OR (objet_type IN ('relance', 'paiement') AND json_extract(apres, '$.facture_id') = :fidn)
 OR (objet_type = 'paiement' AND json_extract(apres, '$.facture_proposee') = :fidn)
 OR (objet_type = 'paiement' AND json_extract(avant, '$.facture_id') = :fidn)
 OR (objet_type = 'message' AND EXISTS (SELECT 1 FROM json_each(journal.apres, '$.factures') WHERE value = :fidn))
 OR (objet_type = 'lot' AND objet_id IN (SELECT lot_envoi FROM relances WHERE facture_id = :fidn))
 OR (objet_type = 'client' AND action = 'reponse_client' AND json_extract(apres, '$.facture_id') = :fidn)
"""


def rechercher(conn: sqlite3.Connection, *, action: str | None = None, acteur: str | None = None,
               type_acteur: str | None = None, objet_type: str | None = None, objet_id: str | None = None,
               regle: str | None = None, depuis: str | None = None, jusqu_a: str | None = None,
               facture_id: int | None = None, client_code: str | None = None,
               limite: int = 200, decalage: int = 0) -> tuple[int, list[dict]]:
    """Recherche multicritère. Retourne (nombre total, page de résultats du plus récent au plus ancien)."""
    conditions, params = [], {}
    for champ, valeur in (("action", action), ("acteur", acteur), ("type_acteur", type_acteur),
                          ("objet_type", objet_type), ("objet_id", objet_id)):
        if valeur:
            conditions.append(f"{champ} = :{champ}")
            params[champ] = valeur
    if regle:
        conditions.append("regle LIKE :regle")
        params["regle"] = f"%{regle}%"
    if depuis:
        conditions.append("horodatage >= :depuis")
        params["depuis"] = depuis
    if jusqu_a:
        conditions.append("horodatage < :jusqu_a")
        params["jusqu_a"] = jusqu_a + "T99" if len(jusqu_a) == 10 else jusqu_a  # date seule : jour inclus
    if facture_id is not None:
        conditions.append(f"({_SQL_FACTURE})")
        params |= {"fid": str(facture_id), "fidn": facture_id}
    if client_code:
        ids = [r[0] for r in conn.execute("SELECT f.id FROM factures f JOIN clients c ON c.id = f.client_id"
                                          " WHERE c.code = ?", (client_code.upper(),))]
        parts = ["(objet_type = 'client' AND objet_id IN (:code, (SELECT CAST(id AS TEXT) FROM clients"
                 " WHERE code = :code)))"]
        params["code"] = client_code.upper()
        for i, fid in enumerate(ids):
            parts.append(f"(objet_type = 'facture' AND objet_id = :f{i})")
            params[f"f{i}"] = str(fid)
        conditions.append("(" + " OR ".join(parts) + ")")
    where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
    total = conn.execute(f"SELECT count(*) FROM journal{where}", params).fetchone()[0]
    lignes = conn.execute(f"SELECT * FROM journal{where} ORDER BY id DESC LIMIT :limite OFFSET :decalage",
                          params | {"limite": max(1, min(limite, 5000)), "decalage": max(0, decalage)})
    return total, [_ligne(l) for l in lignes]


def _ligne(l: sqlite3.Row) -> dict:
    d = dict(l)
    d["avant"] = json.loads(d["avant"]) if d["avant"] else None
    d["apres"] = json.loads(d["apres"]) if d["apres"] else None
    return d


def exporter_csv(lignes: list[dict]) -> bytes:
    tampon = io.StringIO()
    ecrivain = csv.writer(tampon, delimiter=";", lineterminator="\r\n")
    ecrivain.writerow(COLONNES)
    for l in lignes:
        ecrivain.writerow([json.dumps(l[c], ensure_ascii=False) if isinstance(l[c], (dict, list)) else
                           ("" if l[c] is None else l[c]) for c in COLONNES])
    return tampon.getvalue().encode("utf-8-sig")


# --------------------------------------------------------------------------- frise
_STATUTS = {"a_echoir": "à échoir", "echue": "échue", "partiellement_payee": "partiellement payée", "payee": "payée",
            "en_litige": "en litige", "suspendue": "suspendue", "cloturee": "clôturée"}


def libelle(e: dict) -> str:
    """Phrase lisible par un gestionnaire pour un événement du journal."""
    a, av, ap = e["action"], e["avant"] or {}, e["apres"] or {}
    textes = {
        "creation_facture": lambda: f"Facture importée ({ap.get('numero', '')}, échéance {ap.get('echeance', '')})"
                                    + (f", à vérifier : {', '.join(ap['a_verifier'])}" if ap.get("a_verifier") else ""),
        "changement_statut": lambda: f"Statut : {_STATUTS.get(av.get('statut'), av.get('statut'))} → "
                                     f"{_STATUTS.get(ap.get('statut'), ap.get('statut'))}",
        "rapprochement": lambda: f"Paiement {e['objet_id']} rapproché ({ap.get('methode')})",
        "rapprochement_a_valider": lambda: f"Paiement {e['objet_id']} à valider ({ap.get('motif')})",
        "validation_rapprochement": lambda: f"Rapprochement du paiement {e['objet_id']} validé par un humain",
        "annulation_rapprochement": lambda: f"Rapprochement du paiement {e['objet_id']} annulé : {ap.get('motif')}",
        "preparation_relance": lambda: f"Relance {ap.get('etape')} préparée par {ap.get('canal')}. "
                                       f"{ap.get('explication', '')}"
                                       + (". Validation requise : " + "; ".join(ap["raisons"]) if ap.get("raisons") else ""),
        "validation_approuver": lambda: "Relance approuvée par le validateur",
        "validation_modifier": lambda: f"Relance approuvée avec message modifié ({ap.get('motif') or 'sans motif'})",
        "validation_rejeter": lambda: f"Relance rejetée : {ap.get('motif')}",
        "validation_suspendre": lambda: f"Relance suspendue : {ap.get('motif')}",
        "annulation_lot": lambda: "Relance annulée avant envoi : " + "; ".join(ap.get("raisons", [])),
        "envoi_relance": lambda: f"Message envoyé par {ap.get('canal')} (accusé {ap.get('accuse')})",
        "reprise_envoi_confirme": lambda: f"Après interruption : envoi confirmé (accusé {ap.get('accuse')})",
        "reprise_envoi_non_effectue": lambda: "Après interruption : envoi non effectué, remis en file",
        "echec_envoi": lambda: f"Échec d'envoi : {ap.get('erreur')}",
        "reponse_client": lambda: f"Réponse du client : {ap.get('type')}"
                                  + (f" (jusqu'au {ap['date_promise']})" if ap.get("date_promise") else ""),
        "declaration_litige": lambda: f"Litige déclaré : {ap.get('motif')}",
        "levee_litige": lambda: f"Litige levé : {ap.get('motif')}",
        "suspension": lambda: f"Facture suspendue : {ap.get('motif')}",
        "reprise": lambda: f"Facture reprise : {ap.get('motif')}",
        "creation_avoir": lambda: f"Avoir émis : {ap.get('motif')}",
        "passage_en_perte": lambda: f"Passage en perte : {ap.get('motif')}",
        "confirmation_facture": lambda: "Doute levé par un humain",
        "annulation_facture": lambda: f"Facture annulée : {ap.get('motif')}",
        "remplacement_facture": lambda: f"Facture remplacée par la ligne importée : {ap.get('motif')}",
    }
    try:
        return textes[a]() if a in textes else a.replace("_", " ").capitalize()
    except (KeyError, TypeError):
        return a.replace("_", " ").capitalize()


def frise(conn: sqlite3.Connection, facture_id: int) -> list[dict]:
    lignes = conn.execute(f"SELECT * FROM journal WHERE {_SQL_FACTURE} ORDER BY id",
                          {"fid": str(facture_id), "fidn": facture_id})
    return [{"id": e["id"], "horodatage": e["horodatage"], "acteur": e["acteur"], "type_acteur": e["type_acteur"],
             "action": e["action"], "regle": e["regle"], "libelle": libelle(e)} for e in map(_ligne, lignes)]


# ------------------------------------------------------- explication par le journal
def expliquer_relance(conn: sqlite3.Connection, relance_id: int) -> dict:
    """Reconstitue le sort d'une relance à partir du journal SEUL (aucune autre table n'est lue)."""
    prep = conn.execute("SELECT * FROM journal WHERE objet_type = 'relance' AND objet_id = ?"
                        " AND action = 'preparation_relance'", (str(relance_id),)).fetchone()
    if prep is None:
        return {"relance_id": relance_id, "trouvee": False}
    prep = _ligne(prep)
    ap = prep["apres"]
    lot = ap["lot"]
    issue, raisons, decisions = "en_attente_validation" if ap["statut"] == "a_valider" else "validee", [], []
    suite = conn.execute(
        "SELECT * FROM journal WHERE id > ? AND ((objet_type = 'lot' AND objet_id = ?)"
        " OR (objet_type = 'message' AND json_extract(apres, '$.lot') = ?)) ORDER BY id", (prep["id"], lot, lot))
    for e in map(_ligne, suite):
        concerne = relance_id in (e["apres"] or {}).get("relances", [relance_id])
        if not concerne or issue in ("envoyee", "annulee"):
            continue
        if e["action"].startswith("validation_"):
            decisions.append({"decision": e["action"].removeprefix("validation_"), "par": e["acteur"],
                              "le": e["horodatage"], "motif": e["apres"].get("motif")})
            if e["action"] == "validation_rejeter" or e["action"] == "validation_suspendre":
                issue, raisons = "annulee", [e["apres"].get("motif")]
            else:
                issue = "validee"
        elif e["action"] == "annulation_lot":
            issue, raisons = "annulee", e["apres"]["raisons"]
        elif e["action"] in ("envoi_relance", "reprise_envoi_confirme"):
            issue = "envoyee"
        elif e["action"] == "echec_envoi":
            issue = "echec"
    return {
        "relance_id": relance_id, "trouvee": True, "facture_id": ap["facture_id"], "numero": ap.get("numero"),
        "etape": ap["etape"], "canal": ap["canal"], "lot": lot, "pourquoi": ap.get("explication"),
        "regle": prep["regle"], "validation_requise": ap.get("raisons") or [], "decisions": decisions,
        "issue": issue, "raisons": raisons, "solde_a_la_preparation": ap.get("solde"),
    }
