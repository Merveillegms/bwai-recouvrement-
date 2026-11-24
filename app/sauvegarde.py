"""Sauvegarde et restauration de la base en une commande.

    python tasks.py sauvegarder                 copie cohérente (API de sauvegarde SQLite, même pendant l'utilisation)
    python tasks.py restaurer <fichier.db>      vérifie la copie, met la base actuelle de côté, puis restaure

Une copie n'est restaurée que si elle est intègre (PRAGMA integrity_check) et si son journal d'audit est intact
(chaînage des empreintes). La base remplacée est elle-même conservée.
"""
from __future__ import annotations

import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from app import config, journal
from app.db import connecter


def dossier_sauvegardes() -> Path:
    return config.chemin_base().parent / "sauvegardes"


def sauvegarder(destination: Path | None = None) -> Path:
    source = config.chemin_base()
    if not source.exists():
        raise FileNotFoundError(f"Aucune base à sauvegarder : {source}")
    destination = destination or dossier_sauvegardes() / f"recouvrement-{datetime.now():%Y%m%d-%H%M%S}.db"
    destination.parent.mkdir(parents=True, exist_ok=True)
    conn = connecter(source)
    try:
        cible = sqlite3.connect(destination)
        conn.backup(cible)  # copie cohérente, transactionnelle
        cible.close()
    finally:
        conn.close()
    return destination


def verifier(fichier: Path) -> list[str]:
    """Problèmes détectés dans une copie (liste vide = restaurable)."""
    if not fichier.exists():
        return [f"Fichier introuvable : {fichier}"]
    try:
        conn = sqlite3.connect(f"file:{fichier}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        problemes = []
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            problemes.append("intégrité SQLite non vérifiée")
        alterees = journal.verifier_chaine(conn)
        if alterees:
            problemes.append(f"journal d'audit altéré (lignes {alterees[:5]})")
        conn.close()
        return problemes
    except sqlite3.DatabaseError as e:
        return [f"Fichier illisible : {e}"]


def restaurer(fichier: Path) -> Path:
    problemes = verifier(fichier)
    if problemes:
        raise ValueError("Restauration refusée : " + "; ".join(problemes))
    base = config.chemin_base()
    mise_de_cote = None
    if base.exists():
        mise_de_cote = sauvegarder(dossier_sauvegardes() / f"avant-restauration-{datetime.now():%Y%m%d-%H%M%S}.db")
        for suffixe in ("-wal", "-shm"):
            base.with_name(base.name + suffixe).unlink(missing_ok=True)
    shutil.copyfile(fichier, base)
    return mise_de_cote or base


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "sauvegarder":
        print(f"Sauvegarde écrite : {sauvegarder()}")
    elif len(sys.argv) >= 3 and sys.argv[1] == "restaurer":
        try:
            ancienne = restaurer(Path(sys.argv[2]))
        except (ValueError, PermissionError) as e:
            sys.exit(str(e) if isinstance(e, ValueError) else "Base verrouillée : arrêtez l'application (demo) puis relancez.")
        print(f"Base restaurée depuis {sys.argv[2]} (ancienne base conservée : {ancienne})")
    else:
        sys.exit("Usage : python -m app.sauvegarde sauvegarder | restaurer <fichier.db>")
