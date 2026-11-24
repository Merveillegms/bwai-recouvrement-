import sqlite3

import pytest

from app import sauvegarde
from app.db import connecter


@pytest.fixture
def base(demo, tmp_path, monkeypatch):
    conn, _ = demo
    chemin = conn.execute("PRAGMA database_list").fetchone()["file"]
    monkeypatch.setenv("RECOUVREMENT_DB", chemin)
    return conn


def test_sauvegarde_puis_restauration(base, tmp_path):
    copie = sauvegarde.sauvegarder(tmp_path / "copie.db")
    assert sauvegarde.verifier(copie) == []
    avant = base.execute("SELECT count(*) FROM factures").fetchone()[0]
    base.execute("DELETE FROM factures WHERE id NOT IN (SELECT facture_id FROM paiements WHERE facture_id IS NOT NULL)"
                 " AND id NOT IN (SELECT facture_id FROM relances) AND id NOT IN (SELECT facture_id FROM avoirs)")
    base.close()
    ancienne = sauvegarde.restaurer(copie)
    assert ancienne.exists()  # la base remplacée est conservée
    conn = connecter()
    assert conn.execute("SELECT count(*) FROM factures").fetchone()[0] == avant
    conn.close()


def test_copie_alteree_refusee(base, tmp_path):
    copie = sauvegarde.sauvegarder(tmp_path / "copie.db")
    c = sqlite3.connect(copie)
    c.execute("DROP TRIGGER journal_interdit_modification")
    c.execute("UPDATE journal SET acteur = 'pirate' WHERE id = 2")
    c.commit()
    c.close()
    assert any("journal" in p for p in sauvegarde.verifier(copie))
    with pytest.raises(ValueError, match="refusée"):
        sauvegarde.restaurer(copie)


def test_fichier_absent_ou_illisible(tmp_path):
    assert sauvegarde.verifier(tmp_path / "rien.db")
    faux = tmp_path / "faux.db"
    faux.write_bytes(b"pas une base")
    assert sauvegarde.verifier(faux)
