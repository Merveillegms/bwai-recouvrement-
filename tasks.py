#!/usr/bin/env python
"""Commandes du projet (remplace un Makefile, fonctionne sous Windows, macOS et Linux).

    python tasks.py init    installe l'environnement (Python + interface), crée la base et le jeu de données
    python tasks.py test    lance les tests
    python tasks.py demo    lance l'API (port 8000) et l'interface (http://127.0.0.1:3000)
    python tasks.py reset   remet la base et les données de démo à zéro

    python tasks.py sauvegarder           copie cohérente de la base dans data/sauvegardes/
    python tasks.py restaurer <fichier>   vérifie puis restaure une copie (l'ancienne base est conservée)
    python tasks.py couverture            tests + rapport de couverture (docs/couverture.txt)
    python tasks.py mesurer               gains, charge 10 000 factures, évaluation IA, licences (docs/)
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


def sauvegarder() -> None:
    _verifier_environnement()
    _lancer(PYTHON, "-m", "app.sauvegarde", "sauvegarder")


def restaurer() -> None:
    _verifier_environnement()
    if len(sys.argv) < 3:
        sys.exit("Usage : python tasks.py restaurer data/sauvegardes/<fichier>.db")
    _lancer(PYTHON, "-m", "app.sauvegarde", "restaurer", sys.argv[2])


def couverture() -> None:
    """Tests + rapport de couverture versionné (docs/couverture.txt)."""
    _verifier_environnement()
    sortie = RACINE / "docs" / "couverture.txt"
    with sortie.open("w", encoding="utf-8") as f:
        r = subprocess.run([str(PYTHON), "-m", "pytest", "-p", "no:warnings", "--cov=app", "--cov-report=term-missing:skip-covered"],
                           cwd=RACINE, env=ENV, stdout=f, stderr=subprocess.STDOUT)
    print(sortie.read_text(encoding="utf-8").splitlines()[-1])
    if r.returncode:
        sys.exit(r.returncode)


def mesurer() -> None:
    """Mesures du rapport : gains face à la référence, charge 10 000 factures, évaluation de l'IA, licences."""
    _verifier_environnement()
    for module in ("app.mesure_gains", "app.charge", "app.ia.evaluation", "app.licences"):
        _lancer(PYTHON, "-m", module)


COMMANDES = {"init": init, "test": test, "demo": demo, "reset": reset, "sauvegarder": sauvegarder,
             "restaurer": restaurer, "couverture": couverture, "mesurer": mesurer}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDES:
        print(__doc__)
        sys.exit(1)
    COMMANDES[sys.argv[1]]()
