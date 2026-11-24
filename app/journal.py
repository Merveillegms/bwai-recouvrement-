"""Journal d'audit en ajout seul, chaîné par empreintes SHA-256.

Chaque ligne contient l'empreinte de la précédente : modifier ou supprimer une ligne
(en contournant les déclencheurs SQL) casse la chaîne, ce que `verifier_chaine` détecte.
L'appelant doit écrire dans une transaction (`db.transaction`) pour garantir l'ordre.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

GENESE = "0" * 64
_CHAMPS = ("horodatage", "acteur", "type_acteur", "action", "objet_type", "objet_id", "avant", "apres", "regle")


def _json(valeur: Any) -> str | None:
    if valeur is None:
        return None
    return json.dumps(valeur, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def _calculer_hash(hash_precedent: str, ligne: dict[str, Any]) -> str:
    contenu = json.dumps({c: ligne[c] for c in _CHAMPS}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256((hash_precedent + contenu).encode("utf-8")).hexdigest()


def ajouter(
    conn: sqlite3.Connection,
    *,
    acteur: str,
    type_acteur: str,
    action: str,
    objet_type: str,
    objet_id: Any = None,
    avant: Any = None,
    apres: Any = None,
    regle: str | None = None,
) -> int:
    precedente = conn.execute("SELECT hash FROM journal ORDER BY id DESC LIMIT 1").fetchone()
    hash_precedent = precedente["hash"] if precedente else GENESE
    ligne = {
        "horodatage": datetime.now(timezone.utc).isoformat(timespec="microseconds"),
        "acteur": acteur,
        "type_acteur": type_acteur,
        "action": action,
        "objet_type": objet_type,
        "objet_id": None if objet_id is None else str(objet_id),
        "avant": _json(avant),
        "apres": _json(apres),
        "regle": regle,
    }
    empreinte = _calculer_hash(hash_precedent, ligne)
    curseur = conn.execute(
        "INSERT INTO journal (horodatage, acteur, type_acteur, action, objet_type, objet_id,"
        " avant, apres, regle, hash_precedent, hash) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (*(ligne[c] for c in _CHAMPS), hash_precedent, empreinte),
    )
    return curseur.lastrowid


def verifier_chaine(conn: sqlite3.Connection) -> list[int]:
    """Retourne les identifiants des lignes dont l'empreinte ou le chaînage est incohérent."""
    anomalies: list[int] = []
    attendu_precedent = GENESE
    for ligne in conn.execute("SELECT * FROM journal ORDER BY id"):
        donnees = dict(ligne)
        if donnees["hash_precedent"] != attendu_precedent or donnees["hash"] != _calculer_hash(
            donnees["hash_precedent"], donnees
        ):
            anomalies.append(donnees["id"])
        attendu_precedent = donnees["hash"]
    return anomalies
