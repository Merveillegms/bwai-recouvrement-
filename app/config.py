"""Chemins et configuration, surchargeables par variables d'environnement."""
from __future__ import annotations

import os
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
DOSSIER_MIGRATIONS = Path(__file__).resolve().parent / "migrations"
DOSSIER_DEMO = RACINE / "data" / "demo"


def charger_env(fichier: Path | None = None) -> None:
    """Lit le fichier .env local (clés d'API, choix du fournisseur d'IA) sans écraser l'environnement.
    Le fichier .env n'est jamais versionné."""
    fichier = fichier or RACINE / ".env"
    if not fichier.exists():
        return
    for ligne in fichier.read_text(encoding="utf-8").splitlines():
        ligne = ligne.strip()
        if ligne and not ligne.startswith("#") and "=" in ligne:
            cle, _, valeur = ligne.partition("=")
            os.environ.setdefault(cle.strip(), valeur.strip().strip('"').strip("'"))


charger_env()


def chemin_base() -> Path:
    """Fichier SQLite utilisé par l'application (variable RECOUVREMENT_DB)."""
    return Path(os.environ.get("RECOUVREMENT_DB", RACINE / "data" / "recouvrement.db"))
