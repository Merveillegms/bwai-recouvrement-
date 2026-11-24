from hypothesis import given
from hypothesis import strategies as st

from app.references import (
    chiffre_controle,
    formater_reference,
    generer_reference,
    normaliser_reference,
    reference_valide,
)


def test_exemple_connu_de_damm():
    assert chiffre_controle("572") == "4"


def test_reference_stable_et_valide():
    ref = generer_reference("C001", "FAC-2026-0001")
    assert ref == generer_reference(" c001 ", "fac-2026-0001")
    assert reference_valide(ref)
    assert len(ref) == 11 and ref.startswith("RC")


def test_saisie_libre_acceptee():
    ref = generer_reference("C001", "FAC-2026-0001")
    libre = f"{ref[:2].lower()} {ref[2:6]}-{ref[6:]}"
    assert normaliser_reference(libre) == ref
    assert reference_valide(libre)
    assert normaliser_reference(formater_reference(ref)) == ref


@given(st.text(alphabet="0123456789", min_size=8, max_size=8))
def test_toute_erreur_sur_un_chiffre_est_detectee(corps):
    ref = f"RC{corps}{chiffre_controle(corps)}"
    for i in range(2, len(ref)):
        for c in "0123456789":
            if c != ref[i]:
                assert not reference_valide(ref[:i] + c + ref[i + 1:])


@given(st.text(alphabet="0123456789", min_size=8, max_size=8))
def test_toute_inversion_de_chiffres_voisins_est_detectee(corps):
    ref = f"RC{corps}{chiffre_controle(corps)}"
    for i in range(2, len(ref) - 1):
        if ref[i] != ref[i + 1]:
            assert not reference_valide(ref[:i] + ref[i + 1] + ref[i] + ref[i + 2:])


def test_formats_invalides():
    for texte in ("", "RC", "RC12345678", "XX123456789", "RC1234567890"):
        assert not reference_valide(texte)
