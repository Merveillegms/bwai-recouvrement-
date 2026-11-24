"""File de validation humaine : approuver, modifier, rejeter, suspendre, validation groupée."""
from datetime import datetime

import pytest

from app import etat as moteur
from app import priorisation, rapprochement, relances, validation
from app.erreurs import ErreurMetier
from app.montants import formater

MATIN = datetime(2026, 12, 15, 10, 0)


@pytest.fixture
def base(demo):
    conn, _ = demo
    rapprochement.rapprocher_tout(conn)
    relances.preparer(conn)
    return conn


def _compte(conn, role):
    return dict(conn.execute("SELECT id, identifiant, role FROM utilisateurs WHERE role = ?", (role,)).fetchone())


def _lot(conn, condition="1=1"):
    return conn.execute(f"SELECT * FROM relances WHERE statut = 'a_valider' AND etape <> 'R5' AND {condition}"
                        " ORDER BY id LIMIT 1").fetchone()


def test_file_de_validation(base):
    lots = validation.file_de_validation(base)
    assert lots and all(l["raisons"] and l["factures"] and l["message"] for l in lots)
    assert any(l["escalade"] for l in lots) and any(l["groupable"] for l in lots)


def test_seul_le_validateur_decide(base):
    r = _lot(base)
    for role in ("gestionnaire", "auditeur"):
        with pytest.raises(ErreurMetier) as exc:
            validation.approuver(base, r["lot_envoi"], _compte(base, role))
        assert exc.value.code == "VALIDATEUR_REQUIS"


def test_approuver_puis_envoyer(base):
    r = _lot(base)
    v = _compte(base, "validateur")
    assert validation.approuver(base, r["lot_envoi"], v)["statut"] == "validee"
    traces = base.execute("SELECT * FROM validations WHERE relance_id = ?", (r["id"],)).fetchall()
    assert len(traces) == 1 and traces[0]["decideur_id"] == v["id"] and traces[0]["contenu_approuve"] == r["message"]
    assert r["lot_envoi"] in relances.envoyer(base, maintenant=MATIN)["lots"]
    with pytest.raises(ErreurMetier):
        validation.approuver(base, r["lot_envoi"], v)  # plus en attente


def test_modifier_le_message(base):
    r = _lot(base, "canal <> 'sms'")
    v = _compte(base, "validateur")
    e = moteur.etat(base, r["facture_id"])
    corps = r["message"].partition("\n\n")[2] if r["message"].startswith("Objet : ") else r["message"]
    faux = corps.replace(formater(e.solde, e.devise, e.decimales), formater(e.solde * 2, e.devise, e.decimales))
    with pytest.raises(ErreurMetier) as exc:
        validation.approuver(base, r["lot_envoi"], v, contenu=faux)
    assert exc.value.code == "MESSAGE_NON_CONFORME"
    modifie = corps + "\n\nNous vous remercions de votre fidélité."
    resultat = validation.approuver(base, r["lot_envoi"], v, contenu=modifie, motif="Ajout d'une formule")
    assert resultat["decision"] == "modifier"
    nouveau = base.execute("SELECT message FROM relances WHERE id = ?", (r["id"],)).fetchone()[0]
    assert nouveau.endswith("Nous vous remercions de votre fidélité.")
    assert base.execute("SELECT contenu_approuve FROM validations WHERE relance_id = ?", (r["id"],)).fetchone()[0] == nouveau


def test_rejeter_exige_un_motif_et_ecarte_l_etape(base):
    r = _lot(base)
    v = _compte(base, "validateur")
    with pytest.raises(ErreurMetier):
        validation.rejeter(base, r["lot_envoi"], v, " ")
    validation.rejeter(base, r["lot_envoi"], v, "Client déjà contacté par téléphone")
    codes = {x.facture.id: x.code for x in priorisation.file_du_jour(base)[1]}
    assert codes[r["facture_id"]] == "ETAPE_REJETEE"
    assert relances.preparer(base)["relances"] == 0


def test_suspendre_suspend_les_factures(base):
    r = _lot(base)
    resultat = validation.suspendre(base, r["lot_envoi"], _compte(base, "validateur"), "Client hospitalisé")
    assert all(moteur.etat(base, f).statut == "suspendue" for f in resultat["factures_suspendues"])


def test_validation_groupee_des_seuls_lots_ordinaires(base):
    v = _compte(base, "validateur")
    tous = [l["lot"] for l in validation.file_de_validation(base)]
    groupables = set(validation.lots_groupables(base))
    resultat = validation.approuver_groupe(base, tous, v)
    assert set(resultat["validees"]) | set(resultat["annulees"]) == groupables
    assert {x["lot"] for x in resultat["refusees"]} == set(tous) - groupables
    assert base.execute("SELECT count(*) FROM journal WHERE action = 'validation_groupee'").fetchone()[0] == 1


def test_lot_perime_annule_a_l_approbation(base):
    r = _lot(base)
    e = moteur.etat(base, r["facture_id"])
    base.execute("INSERT INTO paiements (id_transaction, date_paiement, montant, devise, reference_citee, source)"
                 " VALUES ('TX-X', '2026-12-15', ?, ?, ?, 'mobile_money')", (e.solde, e.devise, e.reference_paiement))
    rapprochement.rapprocher_tout(base)
    resultat = validation.approuver(base, r["lot_envoi"], _compte(base, "validateur"))
    assert resultat["statut"] == "annulee" and resultat["raisons"]
