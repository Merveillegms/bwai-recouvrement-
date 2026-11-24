import sqlite3

import pytest

from app import journal
from app.db import transaction


def _remplir(conn, n=5):
    with transaction(conn):
        for i in range(n):
            journal.ajouter(conn, acteur="test", type_acteur="systeme", action="essai",
                            objet_type="facture", objet_id=i, avant={"statut": "echue"},
                            apres={"statut": "payee", "montant": i * 1000}, regle="R-test")


def test_chaine_intacte(conn):
    _remplir(conn)
    assert journal.verifier_chaine(conn) == []
    premiere = conn.execute("SELECT hash_precedent FROM journal ORDER BY id LIMIT 1").fetchone()[0]
    assert premiere == journal.GENESE


def test_modification_interdite(conn):
    _remplir(conn)
    with pytest.raises(sqlite3.IntegrityError, match="ajout seul"):
        conn.execute("UPDATE journal SET acteur = 'pirate' WHERE id = 1")


def test_suppression_interdite(conn):
    _remplir(conn)
    with pytest.raises(sqlite3.IntegrityError, match="ajout seul"):
        conn.execute("DELETE FROM journal WHERE id = 1")


def test_alteration_detectee_meme_en_contournant_les_declencheurs(conn):
    _remplir(conn)
    conn.execute("DROP TRIGGER journal_interdit_modification")
    conn.execute("UPDATE journal SET apres = '{\"statut\":\"annulee\"}' WHERE id = 3")
    assert journal.verifier_chaine(conn) == [3]


def test_suppression_detectee_meme_en_contournant_les_declencheurs(conn):
    _remplir(conn)
    conn.execute("DROP TRIGGER journal_interdit_suppression")
    conn.execute("DELETE FROM journal WHERE id = 2")
    assert journal.verifier_chaine(conn) == [3]
