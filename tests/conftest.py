import json

import pytest

from app import config, importer, parametres, seed
from app.db import connecter, migrer

DATE_DEMO = "2026-12-15"


@pytest.fixture
def conn(tmp_path):
    """Base SQLite neuve et migrée, isolée pour chaque test."""
    connexion = connecter(tmp_path / "test.db")
    migrer(connexion)
    yield connexion
    connexion.close()


@pytest.fixture
def conn_prete(conn):
    """Base avec comptes de test et date métier figée à la date du jeu de démo."""
    seed.initialiser(conn)
    parametres.ecrire(conn, "date_du_jour_simulee", DATE_DEMO, "test")
    return conn


@pytest.fixture(scope="session")
def attendus():
    return json.loads((config.DOSSIER_DEMO / "attendus.json").read_text(encoding="utf-8"))


def importer_demo(conn, attendus):
    """Importe les fichiers de démo dans l'ordre prévu ; retourne {fichier: rapport}."""
    types = {"clients.csv": "clients", "paiements_mobile_money.csv": "paiements"}
    rapports = {}
    for nom in attendus["ordre_import"]:
        contenu = (config.DOSSIER_DEMO / nom).read_bytes()
        rapports[nom] = importer.importer(conn, types.get(nom, "factures"), contenu, nom, "gestionnaire")
    return rapports


@pytest.fixture
def demo(conn_prete, attendus):
    return conn_prete, importer_demo(conn_prete, attendus)
