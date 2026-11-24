"""Le jeu de données piégé est reproductible, couvre tous les pièges prévus et reste cohérent."""
import csv
import io
from collections import Counter
from datetime import date
from decimal import Decimal

import pytest

from app import generateur as g

CAS_OBLIGATOIRES = {
    # factures
    "a_echoir", "echeance_aujourd_hui", "echue_1j", "echue_7j", "echue_15j", "echue_30j", "echue_60j",
    "echue_90j", "payee_a_temps", "payee_en_retard", "partiellement_payee", "payee_en_deux_fois", "trop_percu",
    "litige", "litige_partiellement_payee", "montant_tres_petit", "gros_montant", "montant_aberrant",
    "client_sans_contact", "client_sensible", "client_inconnu", "fin_de_mois", "changement_annee",
    "echeance_jour_ferie_passee", "echeance_avant_emission", "dates_format_fr", "montant_avec_espaces",
    "espaces_parasites", "devise_eur_virgule", "doublon_exact", "conflit_numero", "quasi_doublon",
    "deja_importee", "conflit_numero_inter_fichiers", "lot2_nouvelle",
    # paiements
    "paiement_en_double", "reference_inconnue", "reference_mal_saisie", "sans_reference_proposition",
    "sans_reference_ambigu", "reference_saisie_libre",
}
CODES_CONNUS = {
    "CHAMP_MANQUANT", "MONTANT_NEGATIF", "MONTANT_NUL", "MONTANT_INVALIDE", "DECIMALES_INVALIDES",
    "DEVISE_INCONNUE", "DATE_INVALIDE", "DOUBLON_EXACT", "CONFLIT_NUMERO", "DOUBLON_IMPORT", "QUASI_DOUBLON",
    "CLIENT_INCONNU", "MONTANT_ABERRANT", "ECHEANCE_AVANT_EMISSION", "CANAL_INVALIDE", "DOUBLON_PAIEMENT",
    "REFERENCE_INCONNUE", "REFERENCE_INVALIDE", "PROPOSITION_MONTANT_CLIENT", "RAPPROCHEMENT_AMBIGU",
}


@pytest.fixture(scope="module")
def jeu(tmp_path_factory):
    dossier = tmp_path_factory.mktemp("demo")
    return dossier, g.generer(dossier)


def _lire(dossier, nom, attendus):
    info = attendus["fichiers"][nom]
    texte = (dossier / nom).read_bytes().decode(info["encodage"])
    return list(csv.reader(io.StringIO(texte), delimiter=info["separateur"]))


def test_reproductible(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    g.generer(a)
    g.generer(b)
    for fichier in sorted(a.iterdir()):
        assert fichier.read_bytes() == (b / fichier.name).read_bytes(), fichier.name


def test_une_autre_graine_change_le_jeu(tmp_path):
    g.generer(tmp_path / "a")
    g.generer(tmp_path / "b", graine=1)
    assert (tmp_path / "a" / g.LOT1).read_bytes() != (tmp_path / "b" / g.LOT1).read_bytes()


def test_taille_conforme(jeu):
    _, attendus = jeu
    assert 50 <= len(attendus["factures"]) <= 200


def test_tous_les_pieges_sont_presents(jeu):
    _, attendus = jeu
    cas = {x["cas"] for x in attendus["factures"]} | {p["cas"] for p in attendus["paiements"]}
    assert CAS_OBLIGATOIRES <= cas, CAS_OBLIGATOIRES - cas


def test_codes_connus_et_issues_coherentes(jeu):
    _, attendus = jeu
    for x in attendus["factures"] + attendus["clients"]:
        assert set(x["codes"]) <= CODES_CONNUS
        assert (x["issue"] == "acceptee") == (x["codes"] == []), x
    for p in attendus["paiements"]:
        assert set(p["codes"]) <= CODES_CONNUS
        assert (p["issue"] == "rapproche_auto") == (p["codes"] == []), p


def test_chaque_attendu_pointe_sur_la_bonne_ligne(jeu):
    dossier, attendus = jeu
    for nom in (g.LOT1, g.LOT2):
        lignes = _lire(dossier, nom, attendus)
        lot = [x for x in attendus["factures"] if x["fichier"] == nom]
        assert len(lignes) == len(lot) + 1  # + en-tête
        for x in lot:
            assert lignes[x["ligne"] - 1][0].strip() == x["numero"]
    paiements = _lire(dossier, g.FICHIER_PAIEMENTS, attendus)
    assert len(paiements) == len(attendus["paiements"]) + 1
    for p in attendus["paiements"]:
        assert paiements[p["ligne"] - 1][0] == p["id_transaction"]


def test_lot2_vient_d_un_autre_logiciel(jeu):
    dossier, attendus = jeu
    brut = (dossier / g.LOT2).read_bytes()
    with pytest.raises(UnicodeDecodeError):
        brut.decode("utf-8")
    entete = _lire(dossier, g.LOT2, attendus)[0]
    assert entete == g.ENTETE_FACTURES_LOT2


def test_retards_coherents_avec_les_dates_du_fichier(jeu):
    """Recalcul indépendant à partir des dates ISO brutes du lot 1."""
    dossier, attendus = jeu
    reference = date.fromisoformat(attendus["date_reference"])
    lignes = _lire(dossier, g.LOT1, attendus)
    for x in attendus["factures"]:
        if x["fichier"] != g.LOT1 or x["issue"] == "rejetee" or x["statut"] == "payee":
            continue
        brute = lignes[x["ligne"] - 1][3]
        if "-" not in brute:
            continue  # format jj/mm/aaaa, couvert par l'import
        assert x["jours_retard"] == max((reference - date.fromisoformat(brute)).days, 0), x["cas"]


def test_bornes_de_tranches(jeu):
    _, attendus = jeu
    par_cas = {x["cas"]: x for x in attendus["factures"]}
    attendu = {"echue_1j": "1-15", "echue_15j": "1-15", "echue_16j": "16-30", "echue_30j": "16-30",
               "echue_31j": "31-60", "echue_60j": "31-60", "echue_61j": "61-90", "echue_90j": "61-90",
               "echue_91j": "plus_90", "echeance_aujourd_hui": "non_echue"}
    for cas, tr in attendu.items():
        assert par_cas[cas]["tranche"] == tr, cas
    assert par_cas["echeance_aujourd_hui"]["statut"] == "a_echoir"
    assert par_cas["changement_annee"]["jours_retard"] == (date(2026, 12, 15) - date(2026, 1, 14)).days


def test_soldes_et_statuts(jeu):
    _, attendus = jeu
    for x in attendus["factures"]:
        if x["issue"] == "rejetee":
            continue
        montant, paye, solde = Decimal(x["montant_ttc"]), Decimal(x["total_paye"]), Decimal(x["solde"])
        assert solde == max(montant - paye, 0)
        assert Decimal(x["trop_percu"]) == max(paye - montant, 0)
        if x["statut"] == "payee":
            assert solde == 0 and x["tranche"] is None
        if x["statut"] in ("echue", "a_echoir"):
            assert paye == 0
    par_cas = {x["cas"]: x for x in attendus["factures"]}
    assert par_cas["trop_percu"]["trop_percu"] == "5000"
    assert par_cas["litige_partiellement_payee"]["statut"] == "en_litige"
    assert Decimal(par_cas["litige_partiellement_payee"]["total_paye"]) > 0
    assert par_cas["devise_eur_virgule"]["solde"] == "1250.50"


def test_paiements_non_automatiques_ne_comptent_pas(jeu):
    _, attendus = jeu
    par_cas = {x["cas"]: x for x in attendus["factures"]}
    # La facture visée par une référence mal saisie ou un paiement sans référence reste due.
    assert par_cas["echue_30j"]["statut"] == "echue"
    assert par_cas["echue_7j"]["statut"] == "echue"


def test_drapeaux(jeu):
    _, attendus = jeu
    acceptees = [x for x in attendus["factures"] if x["issue"] != "rejetee"]
    par_cas = {x["cas"]: x for x in acceptees}
    assert "gros_montant" in par_cas["gros_montant_extreme"]["drapeaux"]
    assert "a_verifier" in par_cas["montant_aberrant"]["drapeaux"]
    assert {"a_verifier", "sans_contact"} <= set(par_cas["client_inconnu"]["drapeaux"])
    assert "client_sensible" in par_cas["client_sensible"]["drapeaux"]
    assert "gros_montant" not in par_cas["devise_eur_virgule"]["drapeaux"]
    assert all(("gros_montant" in x["drapeaux"]) == (Decimal(x["solde"]) >= 1_000_000)
               for x in acceptees if x["devise"] == "XOF")


def test_aucun_quasi_doublon_involontaire(jeu):
    """Seuls les cas prévus partagent client + montant + émission proche."""
    _, attendus = jeu
    acceptees = [x for x in attendus["factures"] if x["issue"] != "rejetee"]
    paires = Counter((x["code_client"], x["montant_ttc"]) for x in acceptees)
    repetees = {k for k, n in paires.items() if n > 1}
    cas = {x["cas"] for x in acceptees if (x["code_client"], x["montant_ttc"]) in repetees}
    assert cas <= {"original_quasi_doublon", "quasi_doublon", "montant_identique_ambigu"}


def test_references_de_paiement_uniques(jeu):
    _, attendus = jeu
    refs = [x["reference_paiement"] for x in attendus["factures"] if x["issue"] != "rejetee"]
    assert len(refs) == len(set(refs))
