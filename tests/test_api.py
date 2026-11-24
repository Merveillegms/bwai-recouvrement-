import pytest
from fastapi.testclient import TestClient

from app import config, parametres, seed
from app.api import app
from app.db import connecter, migrer


@pytest.fixture
def client(tmp_path, monkeypatch):
    chemin = tmp_path / "api.db"
    monkeypatch.setenv("RECOUVREMENT_DB", str(chemin))
    conn = connecter(chemin)
    migrer(conn)
    seed.initialiser(conn)
    parametres.ecrire(conn, "date_du_jour_simulee", "2026-12-15", "test")
    conn.close()
    return TestClient(app)


def _envoyer(client, type_, nom, utilisateur="gestionnaire"):
    contenu = (config.DOSSIER_DEMO / nom).read_bytes()
    return client.post(f"/api/imports/{type_}", files={"fichier": (nom, contenu, "text/csv")},
                       headers={"X-Utilisateur": utilisateur})


def test_parcours_import(client):
    assert _envoyer(client, "clients", "clients.csv").status_code == 201
    r = _envoyer(client, "factures", "factures_lot1.csv")
    assert r.status_code == 201
    rapport = r.json()
    assert rapport["lignes_rejetees"] > 0 and all(a["message"] for a in rapport["anomalies"])

    deuxieme = _envoyer(client, "factures", "factures_lot1.csv")
    assert deuxieme.status_code == 409 and deuxieme.json()["code"] == "FICHIER_DEJA_IMPORTE"

    csv_rejets = client.get(f"/api/imports/{rapport['import_id']}/rejets.csv")
    assert csv_rejets.status_code == 200 and "code_rejet" in csv_rejets.content.decode("utf-8-sig")

    assert len(client.get("/api/factures/a-verifier").json()) == 4
    anomalies = client.get("/api/anomalies").json()
    conflit = next(a for a in anomalies if a["code"] == "CONFLIT_NUMERO")
    r = client.post(f"/api/anomalies/{conflit['id']}/resolution", json={"decision": "remplacer"},
                    headers={"X-Utilisateur": "validateur"})
    assert r.status_code == 422 and r.json()["code"] == "MOTIF_OBLIGATOIRE"


def test_apercu_lot2(client):
    contenu = (config.DOSSIER_DEMO / "factures_lot2.csv").read_bytes()
    r = client.post("/api/imports/factures/apercu", files={"fichier": ("lot2.csv", contenu, "text/csv")})
    assert r.status_code == 200
    corps = r.json()
    assert corps["champs_manquants"] == [] and corps["correspondance"]["date_echeance"] == "Échéance"


def test_auditeur_en_lecture_seule(client):
    r = _envoyer(client, "clients", "clients.csv", utilisateur="auditeur")
    assert r.status_code == 403 and r.json()["code"] == "LECTURE_SEULE"
    assert client.get("/api/imports", headers={"X-Utilisateur": "auditeur"}).status_code == 200


def test_utilisateur_inconnu(client):
    assert client.get("/api/imports", headers={"X-Utilisateur": "pirate"}).status_code == 401


def test_type_inconnu_message_clair(client):
    r = client.post("/api/imports/devis", files={"fichier": ("x.csv", b"a;b\n1;2", "text/csv")})
    assert r.status_code == 422 and r.json()["code"] == "TYPE_INCONNU"
