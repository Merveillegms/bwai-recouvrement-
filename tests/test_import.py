"""Import du jeu piégé : chaque ligne doit obtenir exactement l'issue et les codes attendus."""
import csv
import io
from collections import defaultdict
from decimal import Decimal

import pytest
from openpyxl import Workbook

from app import config, importer, journal
from app.generateur import ENTETE_FACTURES, LOT1, LOT2
from app.importer import ImportRefuse


def _issues(rapport):
    """(ligne) → (issue, codes) d'après le rapport ; une ligne sans anomalie est acceptée."""
    par_ligne = defaultdict(list)
    for a in rapport.anomalies:
        par_ligne[a.ligne].append(a)
    resultat = {}
    for ligne, anomalies in par_ligne.items():
        rejets = [a.code for a in anomalies if a.gravite == "rejet"]
        resultat[ligne] = ("rejetee", rejets) if rejets else ("avertissement", [a.code for a in anomalies])
    return resultat


def _comparer(rapport, attendus_lignes, issue_ok="acceptee"):
    obtenus = _issues(rapport)
    erreurs = []
    for x in attendus_lignes:
        obtenu = obtenus.get(x["ligne"], (issue_ok, []))
        attendu_issue = x["issue"] if x["issue"] in ("rejetee", "avertissement", "acceptee") else issue_ok
        if obtenu != (attendu_issue, x["codes"]):
            erreurs.append(f"ligne {x['ligne']} ({x.get('cas', x.get('code_client'))}) : attendu "
                           f"{(attendu_issue, x['codes'])}, obtenu {obtenu}")
    assert not erreurs, "\n".join(erreurs)
    assert rapport.lignes_lues == len(attendus_lignes)


def test_clients_conformes(demo, attendus):
    _, rapports = demo
    _comparer(rapports["clients.csv"], attendus["clients"])


@pytest.mark.parametrize("fichier", [LOT1, LOT2])
def test_factures_conformes(demo, attendus, fichier):
    _, rapports = demo
    _comparer(rapports[fichier], [x for x in attendus["factures"] if x["fichier"] == fichier])


def test_paiements_doublon_rejete(demo, attendus):
    """Phase 1 : seul le doublon de transaction est rejeté ; le rapprochement vient en phase 2."""
    _, rapports = demo
    attendus_p = [{**p, "issue": "rejetee" if p["issue"] == "rejete" else "acceptee",
                   "codes": p["codes"] if p["issue"] == "rejete" else []} for p in attendus["paiements"]]
    _comparer(rapports["paiements_mobile_money.csv"], attendus_p)


def test_compteurs_du_rapport(demo, attendus):
    _, rapports = demo
    lot = [x for x in attendus["factures"] if x["fichier"] == LOT1]
    r = rapports[LOT1]
    assert r.lignes_rejetees == sum(x["issue"] == "rejetee" for x in lot)
    assert r.lignes_avertissement == sum(x["issue"] == "avertissement" for x in lot)
    assert r.lignes_acceptees == sum(x["issue"] == "acceptee" for x in lot)


def test_factures_en_base_conformes(demo, attendus):
    conn, _ = demo
    decimales = {r["code"]: r["decimales"] for r in conn.execute("SELECT * FROM devises")}
    acceptees = [x for x in attendus["factures"] if x["issue"] != "rejetee"]
    assert conn.execute("SELECT count(*) FROM factures").fetchone()[0] == len(acceptees)
    for x in acceptees:
        f = conn.execute("SELECT f.* FROM factures f JOIN clients c ON c.id = f.client_id"
                         " WHERE c.code = ? AND f.numero = ?", (x["code_client"], x["numero"])).fetchone()
        assert f is not None, x["cas"]
        assert f["montant_ttc"] == int(Decimal(x["montant_ttc"]).scaleb(decimales[x["devise"]])), x["cas"]
        assert f["devise"] == x["devise"]
        assert f["reference_paiement"] == x["reference_paiement"]
        assert bool(f["a_verifier"]) == ("a_verifier" in x["drapeaux"]), x["cas"]
        if x["total_paye"] == "0":  # aucun paiement à rapprocher : le statut d'import est le statut final
            assert f["statut"] == x["statut"], x["cas"]


def test_client_inconnu_cree_en_attente(demo):
    conn, _ = demo
    c = conn.execute("SELECT * FROM clients WHERE code = 'C999'").fetchone()
    assert c["statut_validation"] == "en_attente"
    assert conn.execute("SELECT count(*) FROM clients WHERE statut_validation = 'en_attente'").fetchone()[0] == 1


def test_lot2_detection_automatique(demo, attendus):
    _, rapports = demo
    r = rapports[LOT2]
    assert (r.encodage, r.separateur) == ("cp1252", ",")
    attendu = attendus["fichiers"][LOT2]["correspondance_colonnes"]
    assert {v: k for k, v in r.correspondance.items()} == attendu


def test_reimport_refuse_et_journalise(demo):
    conn, _ = demo
    contenu = (config.DOSSIER_DEMO / LOT1).read_bytes()
    avant = conn.execute("SELECT count(*) FROM factures").fetchone()[0]
    with pytest.raises(ImportRefuse) as exc:
        importer.importer(conn, "factures", contenu, "copie_renommee.csv", "gestionnaire")
    assert exc.value.code == "FICHIER_DEJA_IMPORTE"
    assert LOT1 in exc.value.message
    assert conn.execute("SELECT count(*) FROM factures").fetchone()[0] == avant
    assert conn.execute("SELECT count(*) FROM journal WHERE action = 'import_refuse'").fetchone()[0] == 1


def test_journal_complet_et_intact(demo, attendus):
    conn, _ = demo
    assert journal.verifier_chaine(conn) == []
    acceptees = sum(x["issue"] != "rejetee" for x in attendus["factures"])
    assert conn.execute("SELECT count(*) FROM journal WHERE action = 'creation_facture'").fetchone()[0] == acceptees
    assert conn.execute("SELECT count(*) FROM journal WHERE action = 'import_fichier'").fetchone()[0] == 4


def test_import_transactionnel(conn_prete, monkeypatch):
    """Une panne au milieu de l'import n'en laisse aucune trace ; le même fichier peut ensuite être importé."""
    conn = conn_prete
    importer.importer(conn, "clients", (config.DOSSIER_DEMO / "clients.csv").read_bytes(), "clients.csv", "g")
    vrai_ajouter, appels = journal.ajouter, {"n": 0}

    def panne(*args, **kwargs):
        appels["n"] += 1
        if appels["n"] == 40:
            raise RuntimeError("coupure simulée")
        return vrai_ajouter(*args, **kwargs)

    tables = ("factures", "clients", "imports", "import_anomalies", "journal")
    avant = {t: conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in tables}
    monkeypatch.setattr(journal, "ajouter", panne)
    contenu = (config.DOSSIER_DEMO / LOT1).read_bytes()
    with pytest.raises(RuntimeError):
        importer.importer(conn, "factures", contenu, LOT1, "g")
    assert {t: conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in tables} == avant
    monkeypatch.setattr(journal, "ajouter", vrai_ajouter)
    assert importer.importer(conn, "factures", contenu, LOT1, "g").lignes_acceptees > 0


def test_xlsx_donne_le_meme_resultat_que_le_csv(conn_prete, attendus):
    conn = conn_prete
    importer.importer(conn, "clients", (config.DOSSIER_DEMO / "clients.csv").read_bytes(), "clients.csv", "g")
    texte = (config.DOSSIER_DEMO / LOT1).read_bytes().decode("utf-8-sig")
    classeur = Workbook()
    for ligne in csv.reader(io.StringIO(texte), delimiter=";"):
        classeur.active.append(ligne)
    tampon = io.BytesIO()
    classeur.save(tampon)
    r = importer.importer(conn, "factures", tampon.getvalue(), "factures.xlsx", "g")
    assert r.format == "xlsx"
    _comparer(r, [x for x in attendus["factures"] if x["fichier"] == LOT1])


def test_xlsx_cellules_typees(conn_prete):
    """Dates et nombres saisis comme vraies cellules Excel (et non comme texte)."""
    from datetime import datetime

    conn = conn_prete
    classeur = Workbook()
    classeur.active.append(ENTETE_FACTURES)
    classeur.active.append(["F-1", "C1", datetime(2026, 11, 2), datetime(2026, 12, 2), 150000, "XOF", "non"])
    classeur.active.append(["F-2", "C1", datetime(2026, 11, 3), datetime(2026, 12, 3), 1250.5, "EUR", None])
    tampon = io.BytesIO()
    classeur.save(tampon)
    r = importer.importer(conn, "factures", tampon.getvalue(), "f.xlsx", "g")
    assert r.lignes_rejetees == 0
    lignes = conn.execute("SELECT numero, date_echeance, montant_ttc FROM factures ORDER BY numero").fetchall()
    assert [tuple(l) for l in lignes] == [("F-1", "2026-12-02", 150000), ("F-2", "2026-12-03", 125050)]


def _csv(lignes, sep=";"):
    return "\n".join(sep.join(l) for l in lignes).encode("utf-8")


def test_colonnes_obligatoires_manquantes(conn_prete):
    contenu = _csv([["numero_facture", "code_client", "date_emission", "date_echeance", "devise"],
                    ["F1", "C1", "2026-01-01", "2026-01-31", "XOF"]])
    with pytest.raises(ImportRefuse) as exc:
        importer.importer(conn_prete, "factures", contenu, "f.csv", "g")
    assert exc.value.code == "COLONNES_MANQUANTES" and "montant" in exc.value.message
    assert conn_prete.execute("SELECT count(*) FROM imports").fetchone()[0] == 0


def test_correspondance_manuelle(conn_prete):
    contenu = _csv([["A", "B", "C", "D", "E", "F"], ["F1", "C1", "01/10/2026", "31/10/2026", "45 000", "xof"]])
    apercu = importer.apercu("factures", contenu, "f.csv")
    assert "montant_ttc" in apercu["champs_manquants"]
    corr = {"numero_facture": "A", "code_client": "B", "date_emission": "C", "date_echeance": "D",
            "montant_ttc": "E", "devise": "F", "litige": None}
    r = importer.importer(conn_prete, "factures", contenu, "f.csv", "g", corr)
    assert r.lignes_rejetees == 0
    assert conn_prete.execute("SELECT montant_ttc, devise FROM factures").fetchone()[:] == (45000, "XOF")


@pytest.mark.parametrize("contenu", [b"", b"\n\n", b"une seule colonne\nvaleur", b"PK\x03\x04corrompu"])
def test_fichier_illisible(conn_prete, contenu):
    with pytest.raises(ImportRefuse) as exc:
        importer.importer(conn_prete, "factures", contenu, "f.csv", "g")
    assert exc.value.code in ("FICHIER_ILLISIBLE", "COLONNES_MANQUANTES")


def test_quasi_doublon_detecte_contre_la_base(conn_prete):
    entete = ["numero_facture", "code_client", "date_emission", "date_echeance", "montant_ttc", "devise"]
    importer.importer(conn_prete, "factures", _csv([entete, ["F1", "C1", "2026-10-01", "2026-10-31", "50000", "XOF"]]),
                      "a.csv", "g")
    r = importer.importer(conn_prete, "factures", _csv([entete, ["F2", "C1", "2026-10-04", "2026-11-03", "50000", "XOF"],
                                                        ["F3", "C1", "2026-10-30", "2026-11-29", "50000", "XOF"]]),
                          "b.csv", "g")
    assert [(a.ligne, a.code) for a in r.anomalies if a.code == "QUASI_DOUBLON"] == [(2, "QUASI_DOUBLON")]


def test_export_des_rejets(demo, attendus):
    conn, rapports = demo
    contenu = importer.exporter_rejets_csv(conn, rapports[LOT1].import_id).decode("utf-8-sig")
    lignes = list(csv.reader(io.StringIO(contenu), delimiter=";"))
    assert lignes[0][:3] == ["ligne", "code_rejet", "motif"]
    rejets = [x for x in attendus["factures"] if x["fichier"] == LOT1 and x["issue"] == "rejetee"]
    assert sorted((int(l[0]), l[1]) for l in lignes[1:]) == sorted((x["ligne"], x["codes"][0]) for x in rejets)
    assert all(l[2] for l in lignes[1:])  # chaque rejet a un motif lisible


def test_donnees_de_demo_a_jour(tmp_path):
    """Les fichiers de data/demo correspondent exactement à ce que produit le générateur."""
    from app.generateur import generer

    generer(tmp_path)
    for fichier in config.DOSSIER_DEMO.iterdir():
        assert fichier.read_bytes() == (tmp_path / fichier.name).read_bytes(), fichier.name


ENTETE_CLIENTS = ["code_client", "nom", "telephone", "email", "canal_prefere", "langue", "sensible", "notes"]


def test_reimport_clients_doublons_et_conflits(conn_prete):
    conn = conn_prete
    importer.importer(conn, "clients", _csv([ENTETE_CLIENTS, ["C1", "Alpha", "+229 0190000001", "", "sms", "fr", "non", ""]]),
                      "a.csv", "g")
    r = importer.importer(conn, "clients", _csv([
        ENTETE_CLIENTS,
        ["C1", "Alpha", "+229 0190000001", "", "sms", "fr", "non", ""],   # identique à la base
        ["C1", "Alpha SARL", "", "", "sms", "fr", "non", ""],              # différent de la base
        ["C2", "Beta", "", "b@x.example", "", "fr", "peut-etre", ""],      # sensible illisible
        ["C3", "Gamma", "", "g@x.example", "", "fr", "non", ""],
        ["C3", "Gamma bis", "", "g@x.example", "", "fr", "non", ""],      # même code, autres valeurs
    ]), "b.csv", "g")
    assert [(a.ligne, a.code) for a in r.anomalies] == [
        (2, "DOUBLON_IMPORT"), (3, "CONFLIT_CODE"), (4, "VALEUR_INVALIDE"), (6, "CONFLIT_CODE")]
    # canal vide : déduit des coordonnées disponibles
    assert conn.execute("SELECT canal_prefere FROM clients WHERE code = 'C3'").fetchone()[0] == "email"


def test_fichier_clients_complete_un_client_en_attente(conn_prete):
    conn = conn_prete
    entete = ["numero_facture", "code_client", "date_emission", "date_echeance", "montant_ttc", "devise"]
    importer.importer(conn, "factures", _csv([entete, ["F1", "C77", "2026-10-01", "2026-10-31", "50000", "XOF"]]),
                      "f.csv", "g")
    assert conn.execute("SELECT statut_validation FROM clients WHERE code = 'C77'").fetchone()[0] == "en_attente"
    r = importer.importer(conn, "clients", _csv([ENTETE_CLIENTS, ["C77", "Delta", "+229 0190000077", "", "sms", "fr",
                                                                  "non", ""]]), "c.csv", "g")
    assert r.lignes_acceptees == 1 and r.anomalies == []
    c = conn.execute("SELECT * FROM clients WHERE code = 'C77'").fetchone()
    assert (c["nom"], c["statut_validation"]) == ("Delta", "valide")
