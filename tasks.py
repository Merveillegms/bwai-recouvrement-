#!/usr/bin/env python
"""Commandes du projet (remplace un Makefile, fonctionne sous Windows, macOS et Linux).

    python tasks.py init    installe l'environnement, crée la base et le jeu de données
    python tasks.py test    lance les tests
    python tasks.py demo    lance l'application
    python tasks.py reset   remet la base et les données de démo à zéro
"""
from __future__ import annotations

import os
import subprocess
import sys
import venv
from pathlib import Path

RACINE = Path(__file__).resolve().parent
VENV = RACINE / ".venv"
PYTHON = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _lancer(*args: object) -> None:
    commande = [str(a) for a in args]
    print("->", " ".join(commande), flush=True)
    environnement = os.environ | {"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}  # accents corrects sous Windows
    resultat = subprocess.run(commande, cwd=RACINE, env=environnement)
    if resultat.returncode:
        sys.exit(resultat.returncode)


def _verifier_environnement() -> None:
    if not PYTHON.exists():
        sys.exit("Environnement absent : lancez d'abord  python tasks.py init")


def init() -> None:
    if sys.version_info < (3, 10):
        sys.exit("Python 3.10 ou plus récent est requis.")
    if not PYTHON.exists():
        print("Création de l'environnement virtuel .venv")
        venv.create(VENV, with_pip=True)
    _lancer(PYTHON, "-m", "pip", "install", "--disable-pip-version-check", "-q", "-r", "requirements.txt")
    _lancer(PYTHON, "-m", "app.cli", "init")


def test() -> None:
    _verifier_environnement()
    _lancer(PYTHON, "-m", "pytest", *sys.argv[2:])


def demo() -> None:
    _verifier_environnement()
    _lancer(PYTHON, "-m", "uvicorn", "app.api:app", "--host", "127.0.0.1", "--port", "8000")


def reset() -> None:
    _verifier_environnement()
    _lancer(PYTHON, "-m", "app.cli", "reset")


COMMANDES = {"init": init, "test": test, "demo": demo, "reset": reset}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDES:
        print(__doc__)
        sys.exit(1)
    COMMANDES[sys.argv[1]]()
