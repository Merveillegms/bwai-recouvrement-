#!/usr/bin/env python
"""Commandes du projet (remplace un Makefile, fonctionne sous Windows, macOS et Linux).

    python tasks.py init    installe l'environnement (Python + interface), crée la base et le jeu de données
    python tasks.py test    lance les tests
    python tasks.py demo    lance l'API (port 8000) et l'interface (http://127.0.0.1:3000)
    python tasks.py reset   remet la base et les données de démo à zéro
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
import venv
from pathlib import Path

RACINE = Path(__file__).resolve().parent
VENV = RACINE / ".venv"
PYTHON = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
FRONT = RACINE / "frontend"
ENV = os.environ | {"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "NEXT_TELEMETRY_DISABLED": "1"}


def _npm() -> str:
    npm = shutil.which("npm")
    if npm is None:
        sys.exit("Node.js (npm) est requis pour l'interface : https://nodejs.org (version 20 ou plus)")
    return npm


def _lancer(*args: object, cwd: Path = RACINE) -> None:
    commande = [str(a) for a in args]
    print("->", " ".join(commande), flush=True)
    resultat = subprocess.run(commande, cwd=cwd, env=ENV)
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
    npm = _npm()
    _lancer(npm, "ci", "--no-fund", "--no-audit", cwd=FRONT)  # versions figées par package-lock.json
    _lancer(npm, "run", "build", cwd=FRONT)


def test() -> None:
    _verifier_environnement()
    _lancer(PYTHON, "-m", "pytest", *sys.argv[2:])


def demo() -> None:
    """API et interface ensemble ; Ctrl+C arrête les deux."""
    _verifier_environnement()
    npm = _npm()
    if not (FRONT / ".next" / "BUILD_ID").exists():
        _lancer(npm, "run", "build", cwd=FRONT)
    api = subprocess.Popen([str(PYTHON), "-m", "uvicorn", "app.api:app", "--host", "127.0.0.1", "--port", "8000"],
                           cwd=RACINE, env=ENV)
    interface = subprocess.Popen([npm, "run", "start"], cwd=FRONT, env=ENV)
    print("\n  Interface : http://127.0.0.1:3000   (API : http://127.0.0.1:8000/docs)\n  Ctrl+C pour arrêter.\n",
          flush=True)
    try:
        while api.poll() is None and interface.poll() is None:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        for p in (interface, api):
            if p.poll() is None:
                p.terminate()
        for p in (interface, api):
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()


def reset() -> None:
    _verifier_environnement()
    _lancer(PYTHON, "-m", "app.cli", "reset")


COMMANDES = {"init": init, "test": test, "demo": demo, "reset": reset}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDES:
        print(__doc__)
        sys.exit(1)
    COMMANDES[sys.argv[1]]()
