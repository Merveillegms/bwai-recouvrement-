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


def test_parcours_paiements_et_statuts(client):
    for type_, nom in [("clients", "clients.csv"), ("factures", "factures_lot1.csv"),
                       ("paiements", "paiements_mobile_money.csv")]:
        r = _envoyer(client, type_, nom)
        assert r.status_code == 201
    assert r.json()["rapprochement"]["RAPPROCHE"] > 0

    a_valider = client.get("/api/paiements?statut=a_valider").json()
    proposition = next(p for p in a_valider if p["motif_rapprochement"] == "PROPOSITION_MONTANT_CLIENT")
    r = client.post(f"/api/paiements/{proposition['id']}/valider", json={})
    assert r.status_code == 200 and r.json()["statut"] == "payee"

    echue = client.get("/api/factures?statut=echue").json()[0]
    assert echue["solde_affiche"].endswith("FCFA") and echue["tranche"]
    r = client.post(f"/api/factures/{echue['id']}/litige", json={"motif": "Contestation"})
    assert r.status_code == 200 and r.json()["statut"] == "en_litige"
    # Lever un litige est réservé au validateur
    assert client.post(f"/api/factures/{echue['id']}/lever-litige", json={"motif": "ok"}).status_code == 403
    r = client.post(f"/api/factures/{echue['id']}/lever-litige", json={"motif": "ok"},
                    headers={"X-Utilisateur": "validateur"})
    assert r.json()["statut"] == "echue"

    r = client.post(f"/api/factures/{echue['id']}/avoirs", json={"montant": "abc", "motif": "x"},
                    headers={"X-Utilisateur": "validateur"})
    assert r.status_code == 422 and r.json()["code"] == "MONTANT_INVALIDE"

    detail = client.get(f"/api/factures/{echue['id']}").json()
    actions = [h["action"] for h in detail["historique"]]
    assert actions[0] == "creation_facture" and "declaration_litige" in actions and "levee_litige" in actions


def test_file_aujourdhui_et_explications(client):
    for type_, nom in [("clients", "clients.csv"), ("factures", "factures_lot1.csv"),
                       ("paiements", "paiements_mobile_money.csv")]:
        assert _envoyer(client, type_, nom).status_code == 201
    r = client.get("/api/aujourdhui").json()
    assert r["date_reference"] == "2026-12-15" and r["resume"]["a_relancer"] == len(r["file"]) > 0
    premiere = r["file"][0]
    assert premiere["rang"] == 1 and premiere["explication"].startswith("Priorité 1 :")

    filtre = client.get("/api/aujourdhui?tranche=1-15&montant_max=200000").json()
    assert filtre["file"] and all(p["facture"]["tranche"] == "1-15" for p in filtre["file"])
    assert client.get("/api/aujourdhui?montant_min=abc").status_code == 422

    pourquoi = client.get(f"/api/factures/{premiere['facture']['id']}/priorite").json()
    assert pourquoi["dans_la_file"] and pourquoi["detail"]
    exclue = r["exclues"][0]
    pourquoi = client.get(f"/api/factures/{exclue['facture']['id']}/priorite").json()
    assert pourquoi["dans_la_file"] is False and pourquoi["motif"]

    sim = client.post("/api/priorisation/simulation", json={"anciennete": "1", "solde": "0", "historique": "0"})
    assert sim.status_code == 200 and {"rang", "ancien_rang"} <= sim.json()[0].keys()
    invalide = {"anciennete": "0.9", "solde": "0.9", "historique": "0"}
    assert client.post("/api/priorisation/simulation", json=invalide).status_code == 422
    assert client.put("/api/parametres/poids_priorite", json=invalide,
                      headers={"X-Utilisateur": "validateur"}).status_code == 422
    nouveaux = {"anciennete": "0.4", "solde": "0.4", "historique": "0.2"}
    assert client.put("/api/parametres/poids_priorite", json=nouveaux).status_code == 403  # gestionnaire
    assert client.put("/api/parametres/poids_priorite", json=nouveaux,
                      headers={"X-Utilisateur": "validateur"}).status_code == 200
    assert client.get("/api/aujourdhui").json()["file"][0]["poids"]["solde"] == "0.4"


def test_parcours_relances(client, tmp_path):
    from app import parametres
    from app.db import connecter
    import os
    conn = connecter(os.environ["RECOUVREMENT_DB"])
    parametres.ecrire(conn, "controle_heures_envoi", False, "test")  # le test ne dépend pas de l'heure réelle
    conn.close()
    for type_, nom in [("clients", "clients.csv"), ("factures", "factures_lot1.csv"),
                       ("paiements", "paiements_mobile_money.csv")]:
        assert _envoyer(client, type_, nom).status_code == 201
    assert client.post("/api/relances/preparer", headers={"X-Utilisateur": "auditeur"}).status_code == 403
    resume = client.post("/api/relances/preparer").json()
    assert resume["relances"] > 0 and resume["lots"] > 0
    lots = client.get("/api/relances/lots").json()
    assert len(lots) == resume["lots"] and all(l["message"] and l["relances"] for l in lots)
    a_valider = client.get("/api/relances/lots?statut=a_valider").json()
    assert a_valider and all(l["motif_validation"] for l in a_valider)

    envoi = client.post("/api/relances/envoyer").json()
    assert envoi["envoyes"] == len([l for l in lots if l["statut"] == "validee"])
    messages = client.get("/api/messages").json()
    assert len(messages) == envoi["envoyes"] and all(m["accuse"].startswith("SBX-") for m in messages)

    facture = lots[0]["relances"][0]["facture_id"]
    pdf = client.get(f"/api/factures/{facture}/fiche-paiement.pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")

    client_id = lots[0]["client"]["id"]
    r = client.post(f"/api/clients/{client_id}/reponses", json={"type": "promesse", "date_promise": "2026-12-20"})
    assert r.status_code == 201
    r = client.post(f"/api/clients/{client_id}/reponses", json={"type": "promesse"})
    assert r.status_code == 422 and r.json()["code"] == "DATE_OBLIGATOIRE"
