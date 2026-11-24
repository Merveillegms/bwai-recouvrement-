"""Priorisation : ordre identique au calcul fait à la main, explications, exclusions."""
from datetime import date, timedelta
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app import importer, parametres, priorisation, rapprochement
from app.priorisation import Facteurs, Historique, calculer_facteurs, calculer_score, etape_due, lire_poids
from app.references import generer_reference

REF = date(2026, 12, 15)
POIDS = lire_poids({"anciennete": 0.5, "solde": 0.3, "historique": 0.2})


def _csv(lignes):
    return "\n".join(";".join(map(str, l)) for l in lignes).encode("utf-8")


def _ech(jours):
    return (REF - timedelta(days=jours)).isoformat()


def _em(jours):
    return (REF - timedelta(days=jours + 30)).isoformat()


@pytest.fixture
def petit_jeu(conn_prete):
    """Cinq factures ouvertes dont l'ordre a été calculé à la main (voir test ci-dessous)."""
    conn = conn_prete
    clients = [["code_client", "nom", "telephone", "email", "canal_prefere", "langue", "sensible", "notes"]]
    for code in ("K1", "K2", "K3", "K4"):
        clients.append([code, f"Client {code}", f"+229 01900001{code[1]}0", "", "sms", "fr", "non", ""])
    importer.importer(conn, "clients", _csv(clients), "k.csv", "g")
    factures = [["numero_facture", "code_client", "date_emission", "date_echeance", "montant_ttc", "devise"],
                ["A-002", "K1", _em(60), _ech(60), 500000, "XOF"],
                ["D-001", "K4", _em(60), _ech(60), 500000, "XOF"],
                ["B-001", "K1", _em(120), _ech(120), 100000, "XOF"],
                ["C-001", "K2", _em(30), _ech(30), 800000, "XOF"],
                ["E-001", "K3", _em(10), _ech(10), 2000000, "XOF"],
                ["H-001", "K2", "2026-05-31", "2026-06-30", 50000, "XOF"],
                ["H-002", "K2", "2026-04-30", "2026-05-30", 60000, "XOF"]]
    importer.importer(conn, "factures", _csv(factures), "f.csv", "g")
    paiements = [["id_transaction", "date", "montant", "devise", "reference", "telephone_payeur", "operateur"],
                 ["T1", "2026-07-20", 50000, "XOF", generer_reference("K2", "H-001"), "", "MTN MoMo"],
                 ["T2", "2026-07-20", 60000, "XOF", generer_reference("K2", "H-002"), "", "MTN MoMo"]]
    importer.importer(conn, "paiements", _csv(paiements), "p.csv", "g")
    rapprochement.rapprocher_tout(conn)
    return conn


def test_ordre_identique_au_calcul_manuel(petit_jeu):
    # Calcul à la main (poids 0,5 / 0,3 / 0,2 ; plafond 120 j ; seuil 1 000 000 FCFA) :
    #   E-001 : A = 10/120 = 0,0833 ; S = 1 (plafonné) ; H = 0   → 4,165 + 30   = 34,17 (gros montant : en tête)
    #   C-001 : A = 30/120 = 0,25   ; S = 0,8          ; H = 2/2 → 12,5 + 24 + 20 = 56,50
    #   B-001 : A = 1               ; S = 0,1          ; H = 0   → 50 + 3       = 53,00
    #   D-001 : A = 0,5             ; S = 0,5          ; H = 0   → 25 + 15      = 40,00
    #   A-002 : idem D-001 (40,00, même retard, même solde) → départage par numéro : A-002 avant D-001
    file, _ = priorisation.file_du_jour(petit_jeu)
    assert [(p.facture.numero, str(p.score)) for p in file] == [
        ("E-001", "34.17"), ("C-001", "56.50"), ("B-001", "53.00"), ("A-002", "40.00"), ("D-001", "40.00")]
    assert [p.rang for p in file] == [1, 2, 3, 4, 5]


def test_explications(petit_jeu):
    file, _ = priorisation.file_du_jour(petit_jeu)
    par_numero = {p.facture.numero: p for p in file}
    assert par_numero["C-001"].explication == (
        "Priorité 2 : 30 jours de retard, solde de 800 000 FCFA, 2 retards sur 2 factures réglées")
    assert par_numero["B-001"].explication == (
        "Priorité 3 : 120 jours de retard, solde de 100 000 FCFA, aucun historique de règlement")
    assert par_numero["E-001"].explication.endswith(". Gros montant, placé en tête pour validation humaine")
    detail = par_numero["C-001"].detail
    assert detail[0] == "Ancienneté : 30 j → facteur 0.2500 × poids 0.5 = 12.50 pts"
    assert detail[3] == "Score total : 56.50 / 100"
    assert "R3" in detail[4] and par_numero["C-001"].validation_humaine  # R3 : validation obligatoire
    assert par_numero["B-001"].etape["etape"] == "R5"


def test_historique_chiffre(petit_jeu):
    file, _ = priorisation.file_du_jour(petit_jeu)
    h = next(p for p in file if p.facture.numero == "C-001").historique
    assert (h.nb_reglees, h.nb_reglees_en_retard, h.retard_moyen_reglement) == (2, 2, 36)  # 20 j et 51 j


def test_relance_recente_etape_faite_et_promesse(petit_jeu):
    conn = petit_jeu
    file, _ = priorisation.file_du_jour(conn)
    b = next(p for p in file if p.facture.numero == "B-001").facture

    def relance(etape, il_y_a):
        conn.execute("INSERT INTO relances (facture_id, client_id, etape, canal, periode, cle_idempotence, statut,"
                     " version_facture, solde_prepare, date_envoi) VALUES (?,?,?,?,?,?,?,?,?,?)",
                     (b.id, b.client_id, etape, "sms", "p", f"{etape}-{il_y_a}", "envoyee", b.version, b.solde,
                      (REF - timedelta(days=il_y_a)).isoformat()))

    relance("R4", 2)
    motifs = {x.facture.numero: x.code for x in priorisation.file_du_jour(conn)[1]}
    assert motifs["B-001"] == "RELANCE_RECENTE"
    conn.execute("DELETE FROM relances")
    relance("R5", 20)
    motifs = {x.facture.numero: x.code for x in priorisation.file_du_jour(conn)[1]}
    assert motifs["B-001"] == "ETAPE_DEJA_FAITE"
    conn.execute("INSERT INTO reponses_client (client_id, type, date_promise, source, confirme, saisi_par)"
                 " VALUES (?, 'promesse', '2026-12-20', 'saisie', 1, 'g')", (b.client_id,))
    motifs = {x.facture.numero: x.code for x in priorisation.file_du_jour(conn)[1]}
    assert motifs["A-002"] == "PROMESSE_EN_COURS"


def test_simulation_sans_enregistrement(petit_jeu):
    resultat = priorisation.simuler(petit_jeu, {"anciennete": 1, "solde": 0, "historique": 0})
    ordre = [r["numero"] for r in resultat]
    assert ordre == ["E-001", "B-001", "A-002", "D-001", "C-001"]
    assert next(r for r in resultat if r["numero"] == "C-001")["ancien_rang"] == 2
    assert parametres.lire(petit_jeu, "poids_priorite")["anciennete"] == 0.5  # rien n'a changé


@pytest.mark.parametrize("poids", [{"anciennete": 0.5, "solde": 0.5, "historique": 0.5},
                                   {"anciennete": -0.2, "solde": 0.6, "historique": 0.6}])
def test_poids_invalides(poids):
    with pytest.raises(ValueError):
        lire_poids(poids)


# ------------------------------------------------------------- jeu de démo complet
@pytest.fixture
def demo_rapprochee(demo):
    conn, _ = demo
    rapprochement.rapprocher_tout(conn)
    return conn


def test_file_de_demo_coherente(demo_rapprochee):
    file, exclues = priorisation.file_du_jour(demo_rapprochee)
    assert file and exclues
    for p in file:
        assert p.facture.statut in ("echue", "partiellement_payee")
        assert "a_verifier" not in p.facture.drapeaux and p.facture.jours_retard >= 1
        assert p.explication.startswith(f"Priorité {p.rang} :")
    gros = [p.gros_montant for p in file]
    assert gros == sorted(gros, reverse=True)  # tous les gros montants en tête
    codes = {x.code for x in exclues}
    assert {"PAYEE", "EN_LITIGE", "NON_ECHUE", "A_VERIFIER"} <= codes
    assert not [x for x in exclues if x.facture.statut == "payee" and x.code != "PAYEE"]
    # aucune facture ni oubliée, ni comptée deux fois
    ids = [p.facture.id for p in file] + [x.facture.id for x in exclues]
    assert len(ids) == len(set(ids)) == demo_rapprochee.execute("SELECT count(*) FROM factures").fetchone()[0]


def test_ordre_deterministe(demo_rapprochee):
    premier = [p.facture.id for p in priorisation.file_du_jour(demo_rapprochee)[0]]
    assert premier == [p.facture.id for p in priorisation.file_du_jour(demo_rapprochee)[0]]


# --------------------------------------------------------------- propriétés
@given(st.integers(0, 400), st.integers(0, 400), st.integers(1, 10**9))
def test_plus_de_retard_jamais_moins_prioritaire(j1, j2, solde):
    h = Historique()
    s1 = calculer_score(calculer_facteurs(min(j1, j2), solde, 1_000_000, h, 120), POIDS)
    s2 = calculer_score(calculer_facteurs(max(j1, j2), solde, 1_000_000, h, 120), POIDS)
    assert s1 <= s2


@given(st.integers(0, 400), st.integers(0, 10**10), st.integers(0, 50), st.integers(0, 50))
def test_score_borne(jours, solde, reglees, en_retard):
    h = Historique(nb_reglees=max(reglees, en_retard), nb_reglees_en_retard=en_retard)
    assert Decimal(0) <= calculer_score(calculer_facteurs(jours, solde, 1_000_000, h, 120), POIDS) <= Decimal(100)


def test_etape_due():
    sequence = [
        {"etape": "R0", "jours": -3, "active": False}, {"etape": "R1", "jours": 1, "active": True},
        {"etape": "R2", "jours": 10, "active": True}, {"etape": "R3", "jours": 30, "active": True}]
    assert etape_due(0, sequence, set()) is None
    assert etape_due(1, sequence, set())["etape"] == "R1"
    assert etape_due(29, sequence, set())["etape"] == "R2"
    assert etape_due(45, sequence, set())["etape"] == "R3"  # pas de rattrapage de R1/R2
    assert etape_due(45, sequence, {"R3"}) is None
    assert etape_due(45, sequence, {"R1"})["etape"] == "R3"
