from datetime import date
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.montants import arrondir, formater
from app.normalisation import ErreurValeur, cle_entete, lire_booleen, lire_date, lire_decimal, lire_montant


@pytest.mark.parametrize("texte, attendu", [
    ("2026-12-15", date(2026, 12, 15)), ("15/12/2026", date(2026, 12, 15)), ("5/1/2026", date(2026, 1, 5)),
    ("15-12-2026", date(2026, 12, 15)), (" 2026-12-15 00:00:00 ", date(2026, 12, 15)),
    ("29/02/2024", date(2024, 2, 29)),
])
def test_dates_acceptees(texte, attendu):
    assert lire_date(texte) == attendu


@pytest.mark.parametrize("texte", ["", "2026-13-45", "31/02/2026", "29/02/2026", "demain", "12/2026", "1899-01-01"])
def test_dates_refusees(texte):
    with pytest.raises(ErreurValeur) as exc:
        lire_date(texte)
    assert exc.value.code == "DATE_INVALIDE"


@pytest.mark.parametrize("texte, decimales, attendu", [
    ("150000", 0, 150000), ("1 250 000", 0, 1250000), ("1 250 000", 0, 1250000),
    ("150000.00", 0, 150000), ("1250,50", 2, 125050), ("1.250,50", 2, 125050), ("1,250.50", 2, 125050),
    ("1.250.000", 0, 1250000), ("12", 2, 1200),
])
def test_montants_acceptes(texte, decimales, attendu):
    assert lire_montant(texte, decimales) == attendu


@pytest.mark.parametrize("texte, decimales, code", [
    ("-45000", 0, "MONTANT_NEGATIF"), ("0", 0, "MONTANT_NUL"), ("0,00", 2, "MONTANT_NUL"),
    ("12a00", 0, "MONTANT_INVALIDE"), ("", 0, "MONTANT_INVALIDE"), ("150000,50", 0, "DECIMALES_INVALIDES"),
    ("1.234", 2, "DECIMALES_INVALIDES"), ("1e5", 0, "MONTANT_INVALIDE"),
])
def test_montants_refuses(texte, decimales, code):
    with pytest.raises(ErreurValeur) as exc:
        lire_montant(texte, decimales)
    assert exc.value.code == code


@given(st.integers(min_value=1, max_value=10**12))
def test_montant_avec_separateurs_de_milliers(n):
    assert lire_montant(f"{n:,}".replace(",", " "), 0) == n


@given(st.integers(min_value=1, max_value=10**11))
def test_montant_eur_virgule_decimale(centimes):
    texte = f"{centimes // 100},{centimes % 100:02d}"
    assert lire_montant(texte, 2) == centimes


def test_booleens():
    assert lire_booleen("Oui") and lire_booleen("x") and not lire_booleen("") and not lire_booleen("NON")
    with pytest.raises(ErreurValeur):
        lire_booleen("peut-être")


def test_cle_entete():
    assert cle_entete("N° facture") == "nfacture"
    assert cle_entete(" Échéance ") == "echeance"


def test_arrondi_demi_superieur_et_format():
    assert arrondir(Decimal("2.5"), 0) == 3 and arrondir(Decimal("0.125"), 2) == Decimal("0.13")
    assert formater(1250000, "XOF", 0) == "1 250 000 FCFA"
    assert formater(125050, "EUR", 2) == "1 250,50 EUR"
    assert lire_decimal("1 250,50") == Decimal("1250.50")
