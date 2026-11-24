"""Lecture et modification des paramètres réglables (table `parametres`, valeurs JSON)."""
from __future__ import annotations

import json
import sqlite3
from datetime import date
from typing import Any

from app import journal
from app.db import transaction


class ParametreInconnu(KeyError):
    pass


def lire(conn: sqlite3.Connection, cle: str) -> Any:
    ligne = conn.execute("SELECT valeur FROM parametres WHERE cle = ?", (cle,)).fetchone()
    if ligne is None:
        raise ParametreInconnu(cle)
    return json.loads(ligne["valeur"])


def ecrire(conn: sqlite3.Connection, cle: str, valeur: Any, auteur: str, type_acteur: str = "humain") -> None:
    """Modifie un paramètre : version incrémentée, ancienne et nouvelle valeur au journal."""
    with transaction(conn):
        avant = lire(conn, cle)
        conn.execute(
            "UPDATE parametres SET valeur = ?, version = version + 1,"
            " modifie_le = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), modifie_par = ? WHERE cle = ?",
            (json.dumps(valeur, ensure_ascii=False), auteur, cle),
        )
        journal.ajouter(conn, acteur=auteur, type_acteur=type_acteur, action="modification_parametre",
                        objet_type="parametre", objet_id=cle, avant=avant, apres=valeur)


def date_du_jour(conn: sqlite3.Connection) -> date:
    """Date métier : la date simulée si elle est définie (démo, tests), sinon la date réelle."""
    simulee = lire(conn, "date_du_jour_simulee")
    return date.fromisoformat(simulee) if simulee else date.today()
