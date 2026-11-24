import pytest

from app import etat as moteur
from app import rapprochement
from app.erreurs import ErreurMetier
from app.rapprochement import numero_court


@pytest.fixture
def base(demo):
    conn, _ = demo
    rapprochement.rapprocher_tout(conn)
    return conn


def _paiement(conn, motif):
    return conn.execute("SELECT * FROM paiements WHERE motif_rapprochement = ?", (motif,)).fetchone()


def test_numero_court():
    assert numero_court("+229 01 90 00 00 01") == numero_court("0190000001") == numero_court("90000001")
    assert numero_court("123") is None and numero_court(None) is None


def test_confirmer_une_proposition(base):
    p = _paiement(base, "PROPOSITION_MONTANT_CLIENT")
    avant = moteur.etat(base, p["facture_proposee_id"])
    e = rapprochement.valider_paiement(base, p["id"], "gestionnaire")
    assert e.statut == "payee" and e.version == avant.version + 1
    with pytest.raises(ErreurMetier) as exc:
        rapprochement.valider_paiement(base, p["id"], "gestionnaire")
    assert exc.value.code == "NON_APPLICABLE"


def test_ambigu_exige_une_facture_et_un_motif(base):
    p = _paiement(base, "RAPPROCHEMENT_AMBIGU")
    with pytest.raises(ErreurMetier) as exc:
        rapprochement.valider_paiement(base, p["id"], "gestionnaire")
    assert exc.value.code == "FACTURE_REQUISE"
    cible = base.execute("SELECT id FROM factures WHERE montant_ttc = 72000 ORDER BY date_echeance LIMIT 1").fetchone()[0]
    with pytest.raises(ErreurMetier, match="motif"):
        rapprochement.valider_paiement(base, p["id"], "gestionnaire", cible)
    e = rapprochement.valider_paiement(base, p["id"], "gestionnaire", cible, "Client confirme : la plus ancienne")
    assert e.statut == "payee"


def test_rejeter_un_paiement_etranger(base):
    p = _paiement(base, "REFERENCE_INCONNUE")
    rapprochement.rejeter_paiement(base, p["id"], "gestionnaire", "Paiement destiné à un autre fournisseur")
    assert base.execute("SELECT statut_rapprochement FROM paiements WHERE id = ?", (p["id"],)).fetchone()[0] == "rejete"


def test_annuler_un_rapprochement_rend_la_facture_due(base):
    p = base.execute("SELECT p.* FROM paiements p JOIN factures f ON f.id = p.facture_id"
                     " WHERE f.statut = 'payee' AND p.montant = f.montant_ttc LIMIT 1").fetchone()
    e = rapprochement.annuler_rapprochement(base, p["id"], "validateur", "Mauvaise facture") or \
        moteur.etat(base, p["facture_id"])
    assert e.statut in ("echue", "a_echoir")
    ligne = base.execute("SELECT * FROM paiements WHERE id = ?", (p["id"],)).fetchone()
    assert (ligne["statut_rapprochement"], ligne["facture_proposee_id"]) == ("a_valider", p["facture_id"])
    # Une fois annulé, il peut être revalidé sur la même facture : retour à « payée ».
    assert rapprochement.valider_paiement(base, p["id"], "validateur").statut == "payee"


def test_paiement_sur_facture_deja_soldee_mis_a_valider(base):
    f = next(e for e in moteur.etats(base) if e.statut == "payee")
    base.execute("INSERT INTO paiements (id_transaction, date_paiement, montant, devise, reference_citee,"
                 " source) VALUES ('MPX1', '2026-12-14', 1000, ?, ?, 'mobile_money')", (f.devise, f.reference_paiement))
    assert rapprochement.rapprocher_tout(base) == {"FACTURE_DEJA_SOLDEE": 1}
    assert moteur.etat(base, f.id).trop_percu == f.trop_percu  # rien n'a été appliqué


def test_paiement_dans_une_autre_devise(base):
    f = next(e for e in moteur.etats(base) if e.devise == "EUR")
    base.execute("INSERT INTO paiements (id_transaction, date_paiement, montant, devise, reference_citee,"
                 " source) VALUES ('MPX2', '2026-12-14', 100000, 'XOF', ?, 'mobile_money')", (f.reference_paiement,))
    assert rapprochement.rapprocher_tout(base) == {"DEVISE_DIFFERENTE": 1}
