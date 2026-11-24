"""Chemins et configuration, surchargeables par variables d'environnement."""
from __future__ import annotations

import os
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
DOSSIER_MIGRATIONS = Path(__file__).resolve().parent / "migrations"
DOSSIER_DEMO = RACINE / "data" / "demo"


def chemin_base() -> Path:
    """Fichier SQLite utilisé par l'application (variable RECOUVREMENT_DB)."""
    return Path(os.environ.get("RECOUVREMENT_DB", RACINE / "data" / "recouvrement.db"))
