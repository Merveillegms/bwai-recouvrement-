from datetime import date

import pytest

from app import etat as moteur
from app import rapprochement, statuts
from app.calculs import jours_feries, jours_ouvres_de_retard, paques
from app.erreurs import ErreurMetier
from app.statuts import TRANSITIONS, TransitionInterdite, controler_transition


@pytest.fixture
def base(demo):
    conn, _ = demo
    rapprochement.rapprocher_tout(conn)
    return conn


def _une(conn, statut):
    return next(e for e in moteur.etats(conn) if e.statut == statut and not e.drapeaux)


# ----------------------------------------------------------------- transitions
def test_cloturee_est_finale():
    for vers in TRANSITIONS:
        if vers != "cloturee":
            with pytest.raises(TransitionInterdite):
                controler_transition("cloturee", vers, "humain")


@pytest.mark.parametrize("de, vers", [("echue", "en_litige"), ("en_litige", "echue"), ("echue", "suspendue"),
                                      ("suspendue", "echue"), ("payee", "echue"), ("echue", "cloturee")])
def test_decisions_reservees_a_un_humain(de, vers):
    with pytest.raises(TransitionInterdite) as exc:
        controler_transition(de, vers, "systeme")
    assert exc.value.code == "DECISION_HUMAINE_REQUISE"
    controler_transition(de, vers, "humain")


@pytest.mark.parametrize("de, vers", [("a_echoir", "echue"), ("echue", "payee"), ("echue", "partiellement_payee"),
                                      ("partiellement_payee", "payee")])
def test_transitions_automatiques_autorisees(de, vers):
    controler_transition(de, vers, "systeme")


# ------------------------------------------------------------- actions humaines
def test_litige_declare_puis_leve(base):
    e = _une(base, "echue")
    with pytest.raises(ErreurMetier):
        statuts.declarer_litige(base, e.id, "gestionnaire", "")
    apres = statuts.declarer_litige(base, e.id, "gestionnaire", "Client conteste la livraison")
    assert apres.statut == "en_litige" and apres.version == e.version + 1
    assert statuts.recalculer_tout(base) == {}  # le système ne sort jamais seul d'un litige
    with pytest.raises(ErreurMetier) as exc:
        statuts.declarer_litige(base, e.id, "gestionnaire", "encore")
    assert exc.value.code == "NON_APPLICABLE"
    assert statuts.lever_litige(base, e.id, "validateur", "Livraison confirmée").statut == "echue"


def test_suspension_et_reprise(base):
    e = _une(base, "echue")
    assert statuts.suspendre(base, e.id, "gestionnaire", "Client hospitalisé").statut == "suspendue"
    assert statuts.reprendre(base, e.id, "gestionnaire", "Retour").statut == "echue"


def test_avoir_partiel_puis_total(base):
    e = _une(base, "echue")
    with pytest.raises(ErreurMetier) as exc:
        statuts.creer_avoir(base, e.id, e.solde + 1, "validateur", "Remise")
    assert exc.value.code == "AVOIR_SUPERIEUR_AU_SOLDE"
    partiel = statuts.creer_avoir(base, e.id, e.solde // 2, "validateur", "Geste commercial")
    assert partiel.statut == "partiellement_payee" and partiel.solde == e.solde - e.solde // 2
    total = statuts.creer_avoir(base, e.id, partiel.solde, "validateur", "Retour marchandise")
    # Les avoirs couvrent tout le montant, sans paiement : facture annulée, donc clôturée (et non « payée »).
    assert total.solde == 0 and total.statut == "cloturee"


def test_avoir_couvrant_tout_le_montant_cloture(base):
    e = _une(base, "echue")
    assert statuts.creer_avoir(base, e.id, e.montant_ttc, "validateur", "Facture émise par erreur").statut == "cloturee"
    with pytest.raises(ErreurMetier) as exc:
        statuts.suspendre(base, e.id, "gestionnaire", "x")
    assert exc.value.code == "DEJA_CLOTUREE"


def test_passage_en_perte(base):
    e = _une(base, "echue")
    apres = statuts.passer_en_perte(base, e.id, "validateur", "Entreprise liquidée")
    assert apres.statut == "cloturee" and apres.motif_cloture.startswith("Passage en perte")
    assert apres.tranche is None


# ------------------------------------------------------------------ calendrier
def test_paques_connues():
    assert [paques(a) for a in (2025, 2026, 2027)] == [date(2025, 4, 20), date(2026, 4, 5), date(2027, 3, 28)]


def test_feries_du_benin_2026():
    feries = jours_feries(2026, ["01-01", "08-01", "12-25"], ["lundi_paques", "ascension", "lundi_pentecote"],
                          ["2026-03-20", "2027-01-01"])
    assert {date(2026, 4, 6), date(2026, 5, 14), date(2026, 5, 25), date(2026, 8, 1), date(2026, 3, 20)} <= feries
    assert date(2027, 1, 1) not in feries


def test_jours_ouvres():
    # Échéance vendredi 24/04/2026 → lundi 27 … vendredi 1er mai (férié) : 4 jours ouvrés
    assert jours_ouvres_de_retard(date(2026, 4, 24), date(2026, 5, 1), {date(2026, 5, 1)}) == 4
    assert jours_ouvres_de_retard(date(2026, 5, 1), date(2026, 5, 1), set()) == 0
