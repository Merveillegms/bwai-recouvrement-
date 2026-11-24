from datetime import date, timedelta

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app import calculs

REF = date(2026, 12, 15)


@pytest.mark.parametrize("jours, tranche", [
    (-5, "non_echue"), (0, "non_echue"), (1, "1-15"), (15, "1-15"), (16, "16-30"), (30, "16-30"),
    (31, "31-60"), (60, "31-60"), (61, "61-90"), (90, "61-90"), (91, "plus_90"), (400, "plus_90"),
])
def test_tranches(jours, tranche):
    assert calculs.tranche(jours) == tranche


def test_retard():
    assert calculs.jours_de_retard(REF, REF) == 0
    assert calculs.jours_de_retard(REF + timedelta(days=3), REF) == 0
    assert calculs.jours_de_retard(date(2026, 1, 14), REF) == 335


def _statut(**kw):
    base = dict(montant_ttc=100_000, total_paye=0, echeance=REF - timedelta(days=10), reference=REF)
    return calculs.statut(**(base | kw))


def test_ordre_des_statuts():
    assert _statut() == "echue"
    assert _statut(echeance=REF) == "a_echoir"
    assert _statut(total_paye=40_000) == "partiellement_payee"
    assert _statut(total_paye=100_000) == "payee"
    assert _statut(total_paye=120_000) == "payee"
    assert _statut(total_paye=100_000, en_litige=True) == "en_litige"
    assert _statut(en_litige=True, cloturee=True) == "cloturee"
    assert _statut(suspendue=True) == "suspendue"
    assert _statut(total_paye=60_000, total_avoirs=40_000) == "payee"


@given(st.integers(1, 10**9), st.integers(0, 2 * 10**9), st.integers(0, 10**9))
def test_solde_et_trop_percu_coherents(montant, paye, avoirs):
    s, t = calculs.solde(montant, paye, avoirs), calculs.trop_percu(montant, paye, avoirs)
    assert s >= 0 and t >= 0
    assert s == 0 or t == 0  # jamais les deux à la fois
    assert montant - paye - avoirs == s - t  # rien ne se perd
