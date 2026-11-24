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
    c = TestClient(app)
    c.jetons = {}
    c.headers.update(_en_tant_que(c, "gestionnaire"))  # par défaut : le gestionnaire est connecté
    return c


def _en_tant_que(client, identifiant):
    """En-tête d'authentification d'un compte de test (connexion réelle, jeton mis en cache)."""
    if identifiant not in client.jetons:
        r = client.post("/api/auth/connexion", json={"identifiant": identifiant,
                                                     "mot_de_passe": f"demo-{identifiant}"})
        assert r.status_code == 200, r.text
        client.jetons[identifiant] = r.json()["jeton"]
    return {"Authorization": f"Bearer {client.jetons[identifiant]}"}


def _envoyer(client, type_, nom, utilisateur="gestionnaire"):
    contenu = (config.DOSSIER_DEMO / nom).read_bytes()
    return client.post(f"/api/imports/{type_}", files={"fichier": (nom, contenu, "text/csv")},
                       headers=_en_tant_que(client, utilisateur))


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
                    headers=_en_tant_que(client, "validateur"))
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
    assert client.get("/api/imports", headers=_en_tant_que(client, "auditeur")).status_code == 200


def test_utilisateur_inconnu(client):
    assert client.get("/api/imports", headers={"Authorization": "Bearer jeton-invente"}).status_code == 401


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
                    headers=_en_tant_que(client, "validateur"))
    assert r.json()["statut"] == "echue"

    r = client.post(f"/api/factures/{echue['id']}/avoirs", json={"montant": "abc", "motif": "x"},
                    headers=_en_tant_que(client, "validateur"))
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
                      headers=_en_tant_que(client, "validateur")).status_code == 422
    nouveaux = {"anciennete": "0.4", "solde": "0.4", "historique": "0.2"}
    assert client.put("/api/parametres/poids_priorite", json=nouveaux).status_code == 403  # gestionnaire
    assert client.put("/api/parametres/poids_priorite", json=nouveaux,
                      headers=_en_tant_que(client, "validateur")).status_code == 200
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
    assert client.post("/api/relances/preparer", headers=_en_tant_que(client, "auditeur")).status_code == 403
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


def test_sessions(client):
    r = client.post("/api/auth/connexion", json={"identifiant": "validateur", "mot_de_passe": "faux"})
    assert r.status_code == 401 and r.json()["code"] == "IDENTIFIANTS_INVALIDES"
    sans = TestClient(app)
    assert sans.get("/api/imports").status_code == 401
    entete = _en_tant_que(client, "validateur")
    assert client.get("/api/auth/moi", headers=entete).json()["role"] == "validateur"
    client.post("/api/auth/deconnexion", headers=entete)
    assert client.get("/api/auth/moi", headers=entete).status_code == 401  # jeton révoqué


def test_auditeur_voit_les_telephones_masques(client):
    _envoyer(client, "clients", "clients.csv")
    clair = {c["code"]: c["telephone"] for c in client.get("/api/clients").json()}
    masque = {c["code"]: c["telephone"] for c in client.get("/api/clients", headers=_en_tant_que(client, "auditeur")).json()}
    assert clair["C001"] == "+229 0190000001"
    assert masque["C001"] == "+229 01••••••01" and masque["C009"] is None


def test_double_clic_rejoue_la_meme_reponse(client):
    for type_, nom in [("clients", "clients.csv"), ("factures", "factures_lot1.csv")]:
        _envoyer(client, type_, nom)
    premier = client.post("/api/relances/preparer", headers={"Idempotency-Key": "clic-42"})
    second = client.post("/api/relances/preparer", headers={"Idempotency-Key": "clic-42"})
    assert premier.json() == second.json() and premier.json()["relances"] > 0
    assert second.headers.get("Idempotent-Replay") == "true"
    autre = client.post("/api/relances/preparer", headers={"Idempotency-Key": "clic-43"})
    assert autre.json()["relances"] == 0  # nouvelle action, mais rien de nouveau à préparer
    detourne = client.post("/api/recalcul", headers={"Idempotency-Key": "clic-42"})
    assert detourne.status_code == 422 and detourne.json()["code"] == "CLE_DEJA_UTILISEE"


def test_validation_et_arret_urgence_par_l_api(client):
    from app import parametres
    from app.db import connecter
    import os
    conn = connecter(os.environ["RECOUVREMENT_DB"])
    parametres.ecrire(conn, "controle_heures_envoi", False, "test")
    conn.close()
    for type_, nom in [("clients", "clients.csv"), ("factures", "factures_lot1.csv"),
                       ("paiements", "paiements_mobile_money.csv")]:
        _envoyer(client, type_, nom)
    client.post("/api/relances/preparer")
    file = client.get("/api/validation").json()
    assert file["lots"] and file["groupables"]
    lot = file["groupables"][0]
    assert client.post("/api/validation/approuver", json={"lot": lot}).status_code == 403  # gestionnaire
    validateur = _en_tant_que(client, "validateur")
    r = client.post("/api/validation/approuver-groupe", json={"lots": file["groupables"]}, headers=validateur)
    assert r.status_code == 200 and r.json()["validees"]

    assert client.post("/api/arret-urgence", json={"actif": True}, headers=validateur).status_code == 422
    assert client.post("/api/arret-urgence", json={"actif": True, "motif": "Erreur de tarif"}).status_code == 403
    assert client.post("/api/arret-urgence", json={"actif": True, "motif": "Erreur de tarif"},
                       headers=validateur).status_code == 200
    bloque = client.post("/api/relances/envoyer")
    assert bloque.status_code == 423 and bloque.json()["code"] == "ARRET_URGENCE"
    assert client.get("/api/etat-systeme").json()["arret_urgence"] is True
    client.post("/api/arret-urgence", json={"actif": False}, headers=validateur)
    assert client.post("/api/relances/envoyer").json()["envoyes"] > 0


def test_audit_tableau_de_bord_et_demo_par_l_api(client):
    import os
    from app import parametres
    from app.db import connecter
    conn = connecter(os.environ["RECOUVREMENT_DB"])
    parametres.ecrire(conn, "date_du_jour_simulee", None, "test")
    conn.close()
    assert client.post("/api/demo/avancer", json={"jours": 1}).json()["code"] == "MODE_REEL"
    charge = client.post("/api/demo/charger")
    assert charge.status_code == 200 and charge.json()["date"] == "2026-12-15"
    assert client.post("/api/demo/charger").status_code == 409
    assert client.post("/api/demo/charger", headers=_en_tant_que(client, "auditeur")).status_code == 403
    execution = client.post("/api/demo/executer").json()
    assert execution["preparation"]["relances"] > 0

    j = client.get("/api/journal?action=creation_facture&limite=5").json()
    assert j["total"] > 100 and len(j["lignes"]) == 5 and j["lignes"][0]["libelle"].startswith("Facture importée")
    assert client.get("/api/journal/verification").json()["intact"] is True
    export = client.get("/api/journal/export.csv?action=connexion")
    assert export.status_code == 200 and export.content.decode("utf-8-sig").startswith("id;horodatage")

    relance = client.get("/api/relances/lots").json()[0]["relances"][0]
    frise = client.get(f"/api/factures/{relance['facture_id']}/frise").json()
    assert frise["evenements"][0]["action"] == "creation_facture"
    explication = client.get(f"/api/relances/{relance['id']}/explication").json()
    assert explication["pourquoi"].startswith("Priorité")
    assert client.get("/api/relances/999999/explication").status_code == 404

    paye = client.post("/api/demo/paiement", json={"facture_id": relance["facture_id"], "montant": "1 000"})
    assert paye.status_code == 200 and paye.json()["rapprochement"] == {"RAPPROCHE": 1}
    avance = client.post("/api/demo/avancer", json={"jours": 7}).json()
    assert avance["date"] == "2026-12-22"

    tdb = client.get("/api/tableau-de-bord?client=C005").json()
    assert tdb["filtres"]["client"] == "C005" and "total_echu" in tdb["encours"]
    assert client.get("/api/tableau-de-bord/export.csv").status_code == 200
    pdf = client.get("/api/tableau-de-bord/export.pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")


def test_ia_par_l_api(client, monkeypatch):
    import app.api as module_api
    from tests.test_ia import Adaptatif
    client.post("/api/demo/charger")
    client.post("/api/relances/preparer")
    validateur = _en_tant_que(client, "validateur")
    monkeypatch.setattr(module_api, "_fournisseur_ia", lambda: None)
    etat = client.get("/api/ia/etat").json()
    assert etat["active"] is False and etat["redaction"]["configuree"] is False
    assert client.post("/api/ia/activer", json={"actif": True}).status_code == 403  # gestionnaire
    assert client.post("/api/ia/activer", json={"actif": True}, headers=validateur).json()["active"] is True
    assert client.post("/api/ia/rediger", json={"limite": 2}).json()["code"] == "IA_NON_CONFIGUREE"

    monkeypatch.setattr(module_api, "_fournisseur_ia", lambda: Adaptatif())
    r = client.post("/api/ia/rediger", json={"limite": 2}).json()
    assert r["acceptes"] == 2
    lot = next(l for l in client.get("/api/validation").json()["lots"] if l["redige_par_ia"])
    assert client.post("/api/validation/gabarit", json={"lot": lot["lot"]}, headers=validateur).status_code == 200

    c = client.get("/api/clients").json()[0]
    recue = client.post("/api/reponses", json={"client_id": c["id"], "texte": "Je vous paie vendredi sans faute"})
    assert recue.status_code == 201 and recue.json()["proposition"]["categorie"] == "promesse"
    entrante = client.get("/api/reponses").json()[0]
    ok = client.post(f"/api/reponses/{entrante['id']}/confirmer", json={"categorie": "promesse", "date_promise": entrante["date_proposee"]})
    assert ok.json()["statut"] == "confirmee"
    assert client.get("/api/etat-systeme").json()["reponses_a_traiter"] == 0
    assert client.get("/api/ia/appels").json()[0]["fonction"] == "classification"
