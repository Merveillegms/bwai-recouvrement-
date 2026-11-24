"""Commandes d'administration : python -m app.cli init|reset|generer."""
from __future__ import annotations

import sys

from app import config, generateur, seed
from app.db import connecter, migrer, version_schema


def _preparer_base() -> None:
    conn = connecter()
    try:
        nouvelles = migrer(conn)
        comptes = seed.initialiser(conn)
        print(f"Base : {config.chemin_base()} (schéma {version_schema(conn)}, "
              f"{len(nouvelles)} migration(s) appliquée(s), {comptes} compte(s) de test créé(s))")
    finally:
        conn.close()


def _generer() -> None:
    attendus = generateur.generer(config.DOSSIER_DEMO)
    print(f"Données de démo : {config.DOSSIER_DEMO} ({len(attendus['factures'])} lignes de factures, "
          f"{len(attendus['paiements'])} paiements)")


def init() -> None:
    _preparer_base()
    if not (config.DOSSIER_DEMO / "attendus.json").exists():
        _generer()


def reset() -> None:
    base = config.chemin_base()
    for suffixe in ("", "-wal", "-shm"):
        fichier = base.with_name(base.name + suffixe)
        try:
            fichier.unlink(missing_ok=True)
        except PermissionError:
            sys.exit(f"Impossible de supprimer {fichier} : arrêtez l'application (demo) puis relancez reset.")
    _generer()
    _preparer_base()


COMMANDES = {"init": init, "reset": reset, "generer": _generer}

if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in COMMANDES:
        sys.exit(f"Usage : python -m app.cli {'|'.join(COMMANDES)}")
    COMMANDES[sys.argv[1]]()
