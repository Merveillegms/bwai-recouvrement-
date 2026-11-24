import pytest

from app import gabarits
from app.gabarits import LigneFacture, controler_ton, rendre
from app.montants import formater
from app.references import formater_reference, generer_reference

ENTREPRISE = {"nom": "Distribution Atlantique SARL", "ville": "Cotonou", "telephone": "+229 01 97 00 00 00",
              "email": "recouvrement@distribution-atlantique.example",
              "mobile_money": [{"operateur": "MTN MoMo", "numero": "01 97 00 00 00"},
                               {"operateur": "Moov Money", "numero": "01 95 00 00 00"}]}


def _lignes(n):
    return [LigneFacture(f"FAC-2026-00{i}", "2026-10-01", "2026-10-31", 45, 125_000 * i, "XOF", 0,
                         generer_reference("C001", f"FAC-2026-00{i}")) for i in range(1, n + 1)]


@pytest.mark.parametrize("etape", gabarits.ETAPES_MESSAGE)
@pytest.mark.parametrize("canal", ["sms", "whatsapp", "email"])
@pytest.mark.parametrize("nombre", [1, 3])
def test_message_complet_et_conforme(etape, canal, nombre):
    lignes = _lignes(nombre)
    m = rendre(etape, canal, "Boulangerie Les Délices", lignes, ENTREPRISE)
    texte = m.texte
    assert "{" not in texte and "}" not in texte and "None" not in texte
    for l in lignes:  # chaque valeur vient des données calculées, à l'identique
        assert l.numero in texte
        assert formater(l.solde, "XOF", 0) in texte
        assert formater_reference(l.reference) in texte
    if nombre > 1:
        assert f"Total à régler : {formater(sum(l.solde for l in lignes), 'XOF', 0)}." in texte
    assert "01 97 00 00 00" in texte and "Distribution Atlantique SARL" in texte
    assert controler_ton(texte) == []
    assert "vous" in texte.lower()  # vouvoiement
    assert len(texte) <= gabarits.LONGUEUR_MAX[canal]
    assert (m.objet is not None) == (canal == "email")


def test_accords_singulier_pluriel():
    un = rendre("R1", "whatsapp", "X", _lignes(1), ENTREPRISE).texte
    trois = rendre("R1", "whatsapp", "X", _lignes(3), ENTREPRISE).texte
    assert "la facture suivante est arrivée à échéance" in un
    assert "les factures suivantes sont arrivées à échéance" in trois
    assert rendre("R2", "email", "X", _lignes(3), ENTREPRISE).objet == "Deuxième rappel de règlement (3 factures)"


@pytest.mark.parametrize("etape", gabarits.ETAPES_MESSAGE)
@pytest.mark.parametrize("canal", ["sms", "email"])
def test_lot_a_etapes_mixtes_n_affirme_rien_de_faux(etape, canal):
    """Une facture jamais relancée ne doit pas lire « malgré nos rappels »."""
    texte = rendre(etape, canal, "X", _lignes(3), ENTREPRISE, etapes_mixtes=True).texte
    assert "rappel" not in texte.lower().replace("petit rappel", "")
    assert "restent à régler" in texte
    assert controler_ton(texte) == [] and len(texte) <= gabarits.LONGUEUR_MAX[canal]


def test_touche_locale_et_gradation():
    r1 = rendre("R1", "whatsapp", "Maquis Chez Awa", _lignes(1), ENTREPRISE).texte
    r4 = rendre("R4", "email", "Maquis Chez Awa", _lignes(1), ENTREPRISE).texte
    assert "les affaires se portent bien" in r1 and "bonne journée à vous" in r1.lower()
    assert "échéancier" in r4 and "salutations distinguées" in r4
    assert "les affaires" not in r4  # le ton se fait plus formel


def test_contrôle_du_ton():
    assert controler_ton("Nous transmettrons à un huissier") == ["mot interdit : « huissier »"]
    assert controler_ton("Tu dois payer") == ["tutoiement"]
    assert controler_ton("Merci de régler votre facture") == []


def test_refus():
    with pytest.raises(ValueError):
        rendre("R5", "sms", "X", _lignes(1), ENTREPRISE)
    with pytest.raises(ValueError):
        rendre("R1", "sms", "X", [], ENTREPRISE)



def test_deux_devises_dans_un_meme_message():
    """Un seul message par client et par jour, même avec deux devises : un total par devise."""
    eur = LigneFacture("F-E", "2026-10-01", "2026-10-31", 5, 125050, "EUR", 2, generer_reference("C1", "F-E"))
    texte = rendre("R1", "email", "X", _lignes(1) + [eur], ENTREPRISE).texte
    assert "Total à régler : 1 250,50 EUR et 125 000 FCFA." in texte
