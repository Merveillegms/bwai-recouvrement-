import json
import shutil
import sqlite3

import pytest

from app import config, seed
from app.db import MigrationModifiee, connecter, migrer, transaction

TABLES = {
    "devises", "parametres", "utilisateurs", "imports", "import_anomalies", "clients", "factures",
    "avoirs", "paiements", "reponses_client", "messages_sortants", "relances", "validations",
    "verrous", "journal", "schema_migrations",
}


def _client_et_facture(conn):
    conn.execute("INSERT INTO clients (code, nom, canal_prefere) VALUES ('C1', 'Client', 'sms')")
    conn.execute(
        "INSERT INTO factures (numero, client_id, date_emission, date_echeance, montant_ttc, devise,"
        " reference_paiement, statut) VALUES ('F1', 1, '2026-01-01', '2026-01-31', 1000, 'XOF', 'RC1', 'echue')"
    )


def test_toutes_les_tables_existent(conn):
    noms = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert TABLES <= noms


def test_migration_rejouee_ne_fait_rien(conn):
    assert migrer(conn) == []


def test_migration_modifiee_est_detectee(tmp_path):
    dossier = tmp_path / "migrations"
    shutil.copytree(config.DOSSIER_MIGRATIONS, dossier)
    c = connecter(tmp_path / "m.db")
    migrer(c, dossier)
    fichier = next(dossier.glob("0001_*.sql"))
    fichier.write_text(fichier.read_text(encoding="utf-8") + "\n-- modif\n", encoding="utf-8")
    with pytest.raises(MigrationModifiee):
        migrer(c, dossier)
    c.close()


def test_migration_en_echec_est_annulee(tmp_path):
    dossier = tmp_path / "migrations"
    dossier.mkdir()
    (dossier / "0001_casse.sql").write_text("CREATE TABLE t (x);\nINSERT INTO inexistante VALUES (1);")
    c = connecter(tmp_path / "m.db")
    with pytest.raises(sqlite3.OperationalError):
        migrer(c, dossier)
    assert c.execute("SELECT count(*) FROM sqlite_master WHERE name = 't'").fetchone()[0] == 0
    assert c.execute("SELECT count(*) FROM schema_migrations").fetchone()[0] == 0
    c.close()


def test_cles_etrangeres_actives(conn):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO factures (numero, client_id, date_emission, date_echeance, montant_ttc, devise,"
            " reference_paiement, statut) VALUES ('F1', 999, '2026-01-01', '2026-01-31', 1000, 'XOF', 'RC1', 'echue')"
        )


def test_facture_unique_par_client_et_numero(conn):
    _client_et_facture(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO factures (numero, client_id, date_emission, date_echeance, montant_ttc, devise,"
            " reference_paiement, statut) VALUES ('F1', 1, '2026-01-01', '2026-01-31', 2000, 'XOF', 'RC2', 'echue')"
        )


def test_montant_negatif_refuse_en_base(conn):
    conn.execute("INSERT INTO clients (code, nom, canal_prefere) VALUES ('C1', 'Client', 'sms')")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO factures (numero, client_id, date_emission, date_echeance, montant_ttc, devise,"
            " reference_paiement, statut) VALUES ('F1', 1, '2026-01-01', '2026-01-31', -5, 'XOF', 'RC1', 'echue')"
        )


def test_cle_idempotence_unique_en_base(conn):
    _client_et_facture(conn)
    sql = (
        "INSERT INTO relances (facture_id, client_id, etape, canal, periode, cle_idempotence, statut,"
        " version_facture, solde_prepare) VALUES (1, 1, 'R1', 'sms', '2026-02', 'F1|R1|sms|2026-02', 'brouillon', 1, 1000)"
    )
    conn.execute(sql)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(sql)
    assert conn.execute("SELECT count(*) FROM relances").fetchone()[0] == 1


def test_paiement_en_double_refuse(conn):
    sql = ("INSERT INTO paiements (id_transaction, date_paiement, montant, devise, source)"
           " VALUES ('MP1', '2026-01-01', 500, 'XOF', 'mobile_money')")
    conn.execute(sql)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(sql)


def test_rejet_sans_motif_refuse(conn):
    _client_et_facture(conn)
    seed.initialiser(conn)
    conn.execute(
        "INSERT INTO relances (facture_id, client_id, etape, canal, periode, cle_idempotence, statut,"
        " version_facture, solde_prepare) VALUES (1, 1, 'R3', 'sms', 'p', 'k', 'a_valider', 1, 1000)"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO validations (relance_id, decideur_id, decision, motif) VALUES (1, 1, 'rejeter', '  ')")
    conn.execute("INSERT INTO validations (relance_id, decideur_id, decision) VALUES (1, 1, 'approuver')")


def test_transaction_annulee_en_cas_d_erreur(conn):
    with pytest.raises(RuntimeError):
        with transaction(conn):
            conn.execute("INSERT INTO clients (code, nom, canal_prefere) VALUES ('C1', 'Client', 'sms')")
            raise RuntimeError("panne simulée")
    assert conn.execute("SELECT count(*) FROM clients").fetchone()[0] == 0


def test_parametres_par_defaut(conn):
    valeurs = {r["cle"]: json.loads(r["valeur"]) for r in conn.execute("SELECT cle, valeur FROM parametres")}
    assert valeurs["seuil_gros_montant"]["XOF"] == 1_000_000
    assert sum(valeurs["poids_priorite"].values()) == pytest.approx(1)
    etapes = [e["etape"] for e in valeurs["sequence_relances"]]
    assert etapes == ["R0", "R1", "R2", "R3", "R4", "R5"]
    assert valeurs["ia_active"] is False and valeurs["arret_urgence"] is False


def test_seed_idempotent(conn):
    assert seed.initialiser(conn) == 3
    assert seed.initialiser(conn) == 0
    roles = {r["role"] for r in conn.execute("SELECT role FROM utilisateurs")}
    assert roles == {"gestionnaire", "validateur", "auditeur"}
