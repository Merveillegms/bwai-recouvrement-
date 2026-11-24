"""Journal, audit, tableau de bord et mode démo.

Critère de sortie de la phase : à partir du journal SEUL, on explique pourquoi chaque relance du jeu de
test a été envoyée, bloquée ou annulée. Pour le prouver, le journal est copié seul dans une base vide.
"""
import csv
import io
import sqlite3
from datetime import datetime

import pytest

from app import audit, demo, journal, parametres, rapprochement, relances, reponses, tableau_bord, validation
from app import etat as moteur
from app.erreurs import ErreurMetier

MATIN = datetime(2026, 12, 15, 10, 0)


def _compte(conn, role):
    return dict(conn.execute("SELECT id, identifiant, role FROM utilisateurs WHERE role = ?", (role,)).fetchone())


@pytest.fixture
def cycle(demo):
    """Un cycle complet : préparation, décisions humaines variées, paiement tardif, envoi."""
    conn, _ = demo
    rapprochement.rapprocher_tout(conn)
    relances.preparer(conn)
    v = _compte(conn, "validateur")
    lots = [l["lot"] for l in validation.file_de_validation(conn) if not l["escalade"]]
    groupables = validation.lots_groupables(conn)
    autres = [l for l in lots if l not in groupables]
    a_rejeter, a_suspendre, en_attente, *a_approuver = autres  # un lot reste volontairement en attente
    validation.rejeter(conn, a_rejeter, v, "Client déjà joint par téléphone")
    validation.suspendre(conn, a_suspendre, v, "Négociation commerciale en cours")
    validation.approuver_groupe(conn, groupables, v)
    for lot in a_approuver:
        try:
            validation.approuver(conn, lot, v)
        except ErreurMetier:
            pass  # message à corriger : reste en attente
    # un paiement arrive sur une facture d'un lot validé, juste avant l'envoi
    r = conn.execute("SELECT * FROM relances WHERE statut = 'validee' ORDER BY id LIMIT 1").fetchone()
    e = moteur.etat(conn, r["facture_id"])
    conn.execute("INSERT INTO paiements (id_transaction, date_paiement, montant, devise, reference_citee, source)"
                 " VALUES ('TX-TARD', '2026-12-15', ?, ?, ?, 'mobile_money')", (e.solde, e.devise, e.reference_paiement))
    rapprochement.rapprocher_tout(conn)
    relances.envoyer(conn, maintenant=MATIN)
    return conn


ISSUES = {"envoyee": "envoyee", "annulee": "annulee", "a_valider": "en_attente_validation", "validee": "validee",
          "echec": "echec"}


def test_le_journal_seul_explique_chaque_relance(cycle):
    seul = sqlite3.connect(":memory:")
    seul.row_factory = sqlite3.Row
    seul.execute("ATTACH DATABASE ? AS source", (cycle.execute("PRAGMA database_list").fetchone()["file"],))
    seul.execute("CREATE TABLE journal AS SELECT * FROM source.journal")
    seul.execute("DETACH DATABASE source")
    assert [r[0] for r in seul.execute("SELECT name FROM sqlite_master")] == ["journal"]  # rien d'autre

    relances_reelles = cycle.execute("SELECT * FROM relances ORDER BY id").fetchall()
    issues = set()
    for r in relances_reelles:
        x = audit.expliquer_relance(seul, r["id"])
        assert x["trouvee"] and x["etape"] == r["etape"] and x["facture_id"] == r["facture_id"]
        assert x["issue"] == ISSUES[r["statut"]], (r["id"], r["statut"], x)
        assert x["pourquoi"].startswith("Priorité") and x["regle"].startswith("SEQUENCE_")
        if r["statut"] == "annulee":
            assert x["raisons"] and all(x["raisons"])
        issues.add(x["issue"])
    assert {"envoyee", "annulee", "en_attente_validation"} <= issues  # tous les cas sont représentés


def test_frise_d_une_facture(cycle):
    r = cycle.execute("SELECT facture_id FROM relances WHERE statut = 'envoyee' LIMIT 1").fetchone()
    evenements = audit.frise(cycle, r["facture_id"])
    actions = [e["action"] for e in evenements]
    assert actions[0] == "creation_facture"
    assert actions.index("preparation_relance") < actions.index("validation_approuver") < actions.index("envoi_relance")
    assert all(e["libelle"] for e in evenements)
    envoi = next(e for e in evenements if e["action"] == "envoi_relance")
    assert envoi["libelle"].startswith("Message envoyé par")


def test_frise_d_une_facture_payee_avant_envoi(cycle):
    p = cycle.execute("SELECT facture_id FROM paiements WHERE id_transaction = 'TX-TARD'").fetchone()
    libelles = [e["libelle"] for e in audit.frise(cycle, p["facture_id"])]
    assert any(l.startswith("Paiement TX-TARD rapproché") for l in libelles)
    assert any(l.startswith("Relance annulée avant envoi") and "solde changé" in l for l in libelles)


def test_recherche_et_export(cycle):
    total, lignes = audit.rechercher(cycle, action="envoi_relance")
    assert total == cycle.execute("SELECT count(*) FROM messages_sortants WHERE statut = 'envoye'").fetchone()[0]
    assert all(l["action"] == "envoi_relance" for l in lignes)
    total_validateur, _ = audit.rechercher(cycle, acteur="validateur")
    assert total_validateur > 0
    total_c1, _ = audit.rechercher(cycle, client_code="c001")
    assert total_c1 > 0
    page1 = audit.rechercher(cycle, limite=10)[1]
    page2 = audit.rechercher(cycle, limite=10, decalage=10)[1]
    assert page1[-1]["id"] > page2[0]["id"]
    contenu = audit.exporter_csv(lignes).decode("utf-8-sig")
    rangs = list(csv.reader(io.StringIO(contenu), delimiter=";"))
    assert rangs[0][:3] == ["id", "horodatage", "acteur"] and len(rangs) == len(lignes) + 1
    assert journal.verifier_chaine(cycle) == []


# ------------------------------------------------------------------ tableau de bord
def test_indicateurs_coherents(cycle):
    ind = tableau_bord.indicateurs(cycle)
    etats = moteur.etats(cycle)
    echues = [e for e in etats if e.solde > 0 and e.jours_retard > 0 and e.statut in tableau_bord.OUVERTS]
    assert ind["encours"]["factures_echues"] == len(echues)
    assert ind["encours"]["total_echu"]["XOF"]["montant"] == sum(e.solde for e in echues if e.devise == "XOF")
    assert sum(t["nombre"] for t in ind["tranches"]) == sum(
        1 for e in etats if e.solde > 0 and e.statut in tableau_bord.OUVERTS)
    soldes = [f["solde"] for f in ind["top10"]]
    assert len(soldes) == 10 and soldes == sorted(soldes, reverse=True)
    g = ind["garde_fous"]
    assert g["lignes_rejetees_a_l_import"] == cycle.execute(
        "SELECT count(*) FROM import_anomalies WHERE gravite = 'rejet'").fetchone()[0] == 23
    assert g["relances_annulees_avant_envoi"] >= 1 and g["doublons_detectes"] >= 5
    assert ind["relances"]["par_statut"]["envoyee"] > 0


def test_efficacite_apres_relance_et_promesses(cycle):
    v = cycle.execute("SELECT r.facture_id, f.client_id FROM relances r JOIN factures f ON f.id = r.facture_id"
                      " WHERE r.statut = 'envoyee' ORDER BY r.id LIMIT 2").fetchall()
    assert tableau_bord.indicateurs(cycle)["efficacite"]["paiements_apres_relance"] == 0
    reponses.enregistrer(cycle, v[1]["client_id"], "promesse", "gestionnaire", facture_id=v[1]["facture_id"],
                         date_promise="2026-12-20")
    demo.avancer(cycle, 3, "gestionnaire")
    demo.payer(cycle, v[0]["facture_id"], "gestionnaire")
    demo.payer(cycle, v[1]["facture_id"], "gestionnaire")
    demo.avancer(cycle, 10, "gestionnaire")
    eff = tableau_bord.indicateurs(cycle)["efficacite"]
    assert eff["paiements_apres_relance"] == 2 and eff["delai_moyen_jours"] == 3.0
    assert eff["recouvre_apres_relance"]["XOF"]["montant"] > 0
    assert eff["promesses"] == {"tenues": 1, "non_tenues": 0, "en_cours": 0}


def test_exports_tableau(cycle):
    ind = tableau_bord.indicateurs(cycle, client="C005")
    contenu = tableau_bord.exporter_csv(ind).decode("utf-8-sig")
    assert contenu.startswith("section;indicateur;valeur") and "Total échu (XOF)" in contenu
    pdf = tableau_bord.exporter_pdf(ind, "Distribution Atlantique SARL")
    assert pdf.startswith(b"%PDF") and b"Tableau de bord" in pdf


# ---------------------------------------------------------------------- démo
def test_scenario_de_demo(conn_prete):
    conn = conn_prete
    resultat = demo.charger(conn, "gestionnaire")
    assert resultat["imports"]["factures_lot1.csv"]["rejetees"] == 15 and resultat["rapprochement"]["RAPPROCHE"] == 30
    with pytest.raises(ErreurMetier) as exc:
        demo.charger(conn, "gestionnaire")
    assert exc.value.code == "DEJA_CHARGE"
    execution = demo.executer(conn, "gestionnaire")
    assert execution["preparation"]["relances"] > 0
    with pytest.raises(ErreurMetier):
        demo.avancer(conn, 0, "gestionnaire")
    avance = demo.avancer(conn, 20, "gestionnaire")
    assert avance["date"] == "2027-01-04" and avance["changements"].get("a_echoir->echue", 0) > 0
    parametres.ecrire(conn, "date_du_jour_simulee", None, "test")
    with pytest.raises(ErreurMetier) as exc:
        demo.avancer(conn, 1, "gestionnaire")
    assert exc.value.code == "MODE_REEL"
