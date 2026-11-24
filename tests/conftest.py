import pytest

from app.db import connecter, migrer


@pytest.fixture
def conn(tmp_path):
    """Base SQLite neuve et migrée, isolée pour chaque test."""
    connexion = connecter(tmp_path / "test.db")
    migrer(connexion)
    yield connexion
    connexion.close()
