"""Relances : chaque facture éligible génère le bon message, à la bonne étape, une seule fois."""
from collections import Counter
from datetime import datetime

import pytest

from app import etat as moteur
from app import fiche, journal, parametres, priorisation, rapprochement, relances, reponses
from app.connecteurs import BacASable, dossier_sortants
from app.erreurs import ErreurMetier
from app.montants import formater
from app.references import formater_reference

MATIN = datetime(2026, 12, 15, 10, 0)


@pytest.fixture
def base(demo):
    conn, _ = demo
    rapprochement.rapprocher_tout(conn)
    return conn


def _relances(conn):
    return conn.execute("SELECT r.*, f.numero FROM relances r JOIN factures f ON f.id = r.facture_id").fetchall()


def test_chaque_facture_eligible_une_seule_relance_a_la_bonne_etape(base):
    file, _ = priorisation.file_du_jour(base)
    resume = relances.preparer(base)
    par_facture = Counter(r["facture_id"] for r in _relances(base))
    ignorees = {i["facture_id"] for i in resume["ignorees"]}
    assert all(i["code"] == "SANS_CONTACT" for i in resume["ignorees"])
    for p in file:
        if p.facture.id in ignorees:
            assert "sans_contact" in p.facture.drapeaux
            continue
        assert par_facture[p.facture.id] == 1, p.facture.numero
        r = base.execute("SELECT * FROM relances WHERE facture_id = ?", (p.facture.id,)).fetchone()
        assert r["etape"] == p.etape["etape"]
        assert (r["version_facture"], r["solde_prepare"]) == (p.facture.version, p.facture.solde)
    assert resume["relances"] == len(file) - len(ignorees)
    # La validation se décide par lot : un lot part en validation si une seule de ses factures l'exige.
    besoin = {p.facture.id: p.validation_humaine or p.etape["etape"] == "R5" for p in file}
    for lot in {r["lot_envoi"] for r in _relances(base)}:
        lignes = base.execute("SELECT facture_id, statut, motif_validation FROM relances WHERE lot_envoi = ?",
                              (lot,)).fetchall()
        statuts_lot = {l["statut"] for l in lignes}
        assert len(statuts_lot) == 1
        if any(besoin[l["facture_id"]] for l in lignes):
            assert statuts_lot == {"a_valider"}
        elif statuts_lot == {"a_valider"}:
            assert "contrôle du message" in lignes[0]["motif_validation"]


def test_preparation_idempotente(base):
    premiere = relances.preparer(base)
    nb_journal = base.execute("SELECT count(*) FROM journal").fetchone()[0]
    seconde = relances.preparer(base)
    assert premiere["relances"] > 0 and seconde["relances"] == 0
    codes = {x.facture.id: x.code for x in priorisation.file_du_jour(base)[1]}
    en_attente = {r["facture_id"] for r in base.execute("SELECT facture_id FROM relances WHERE statut <> 'envoyee'")}
    assert all(codes[f] == "RELANCE_EN_ATTENTE" for f in en_attente)
    assert base.execute("SELECT count(*) FROM journal").fetchone()[0] == nb_journal


def test_un_seul_message_par_client_et_par_jour(base):
    relances.preparer(base)
    lots = base.execute("SELECT DISTINCT lot_envoi, client_id, etape = 'R5' AS escalade FROM relances").fetchall()
    assert len(lots) == len({(l["client_id"], l["escalade"]) for l in lots})
    for lot in {l["lot_envoi"] for l in lots}:
        messages = {r["message"] for r in base.execute("SELECT message FROM relances WHERE lot_envoi = ?", (lot,))}
        assert len(messages) == 1  # toutes les factures du lot partagent le même message


def test_le_message_contient_les_valeurs_calculees(base):
    relances.preparer(base)
    for r in _relances(base):
        if r["etape"] == "R5":
            assert r["message"].startswith("Dossier d'escalade (R5)")
            continue
        e = moteur.etat(base, r["facture_id"])
        assert e.numero in r["message"]
        assert formater(e.solde, e.devise, e.decimales) in r["message"]
        assert formater_reference(e.reference_paiement) in r["message"]


def test_aucune_facture_payee_litige_ou_douteuse_relancee(base):
    relances.preparer(base)
    for r in _relances(base):
        e = moteur.etat(base, r["facture_id"])
        assert e.statut in ("echue", "partiellement_payee") and "a_verifier" not in e.drapeaux


def test_envoi_des_seuls_lots_valides_puis_plus_rien(base):
    relances.preparer(base)
    valides = {r["lot_envoi"] for r in base.execute(
        "SELECT lot_envoi FROM relances GROUP BY lot_envoi HAVING sum(statut <> 'validee') = 0")}
    resume = relances.envoyer(base, maintenant=MATIN)
    assert resume["envoyes"] == len(valides) > 0 and set(resume["lots"]) == valides
    assert base.execute("SELECT count(*) FROM messages_sortants WHERE statut = 'envoye'").fetchone()[0] == len(valides)
    assert len(list(dossier_sortants().glob("*.txt"))) == len(valides)
    assert base.execute("SELECT count(*) FROM relances WHERE statut = 'a_valider'").fetchone()[0] > 0  # restent
    assert relances.envoyer(base, maintenant=MATIN)["envoyes"] == 0
    assert journal.verifier_chaine(base) == []


def test_apres_envoi_la_facture_sort_de_la_file(base):
    relances.preparer(base)
    relances.envoyer(base, maintenant=MATIN)
    envoyees = {r["facture_id"] for r in base.execute("SELECT facture_id FROM relances WHERE statut = 'envoyee'")}
    _, exclues = priorisation.file_du_jour(base)
    codes = {x.facture.id: x.code for x in exclues}
    assert all(codes.get(f) == "RELANCE_RECENTE" for f in envoyees)
    deja = {r["facture_id"] for r in base.execute("SELECT facture_id FROM relances")}
    parametres.ecrire(base, "date_du_jour_simulee", "2026-12-16", "test")  # le lendemain
    relances.preparer(base)
    nouvelles = base.execute("SELECT r.facture_id, f.date_echeance FROM relances r JOIN factures f"
                             " ON f.id = r.facture_id WHERE r.date_preparation = '2026-12-16'").fetchall()
    # Ni les factures relancées hier, ni celles en attente : seulement celles devenues échues entre-temps.
    assert not {n["facture_id"] for n in nouvelles} & deja
    assert all(n["date_echeance"] == "2026-12-15" for n in nouvelles)


def test_arret_urgence_et_plage_horaire(base):
    parametres.ecrire(base, "arret_urgence", True, "validateur")
    with pytest.raises(ErreurMetier) as exc:
        relances.preparer(base)
    assert exc.value.code == "ARRET_URGENCE"
    parametres.ecrire(base, "arret_urgence", False, "validateur")
    relances.preparer(base)
    with pytest.raises(ErreurMetier) as exc:
        relances.envoyer(base, maintenant=datetime(2026, 12, 15, 22, 30))
    assert exc.value.code == "HORS_PLAGE_HORAIRE"
    assert base.execute("SELECT count(*) FROM messages_sortants").fetchone()[0] == 0


def test_panne_du_fournisseur_tracee(base):
    class EnPanne(BacASable):
        nom = "en_panne"

        def envoyer(self, envoi):
            raise ConnectionError("fournisseur indisponible")

    relances.preparer(base)
    resume = relances.envoyer(base, connecteur=EnPanne(), maintenant=MATIN)
    assert resume["envoyes"] == 0 and resume["echecs"] > 0
    assert base.execute("SELECT count(*) FROM relances WHERE statut = 'echec'").fetchone()[0] > 0
    assert base.execute("SELECT count(*) FROM journal WHERE action = 'echec_envoi'").fetchone()[0] == resume["echecs"]


def test_bac_a_sable_deduplique():
    sable = BacASable()
    from app.connecteurs import Envoi
    envoi = Envoi("C1|2026-12-15|message|XOF", "sms", "+229 0190000001", None, "Bonjour")
    premier = sable.envoyer(envoi)
    assert sable.envoyer(envoi) == premier == sable.accuse(envoi.cle_envoi)
    assert len(list(dossier_sortants().glob("*.txt"))) == 1
    assert sable.accuse("inconnue") is None


# ------------------------------------------------------------------ fiche de paiement
def test_fiche_de_paiement_pdf(base):
    e = next(x for x in moteur.etats(base) if x.statut == "partiellement_payee")
    pdf = fiche.generer_fiche(base, e.id)
    assert pdf.startswith(b"%PDF")
    contenu = pdf.decode("latin-1")
    assert formater_reference(e.reference_paiement) in contenu
    assert formater(e.solde, e.devise, e.decimales) in contenu and e.numero in contenu
    payee = next(x for x in moteur.etats(base) if x.statut == "payee")
    with pytest.raises(ErreurMetier) as exc:
        fiche.generer_fiche(base, payee.id)
    assert exc.value.code == "RIEN_A_PAYER"


# ---------------------------------------------------------------- réponses clients
def _premiere_de_la_file(conn):
    return priorisation.file_du_jour(conn)[0][-1].facture


def test_promesse_suspend_puis_reprend(base):
    e = _premiere_de_la_file(base)
    with pytest.raises(ErreurMetier) as exc:
        reponses.enregistrer(base, e.client_id, "promesse", "gestionnaire", date_promise="2026-12-01")
    assert exc.value.code == "DATE_INVALIDE"
    reponses.enregistrer(base, e.client_id, "promesse", "gestionnaire", facture_id=e.id, date_promise="2026-12-20")
    codes = {x.facture.id: x.code for x in priorisation.file_du_jour(base)[1]}
    assert codes[e.id] == "PROMESSE_EN_COURS"
    parametres.ecrire(base, "date_du_jour_simulee", "2026-12-21", "test")  # promesse non tenue
    assert e.id in {p.facture.id for p in priorisation.file_du_jour(base)[0]}


def test_paiement_annonce_et_litige(base):
    e = _premiere_de_la_file(base)
    reponses.enregistrer(base, e.client_id, "paiement_annonce", "gestionnaire", texte="Payé hier par MoMo")
    assert {x.facture.id: x.code for x in priorisation.file_du_jour(base)[1]}[e.id] == "PROMESSE_EN_COURS"
    with pytest.raises(ErreurMetier) as exc:
        reponses.enregistrer(base, e.client_id, "litige", "gestionnaire")
    assert exc.value.code == "FACTURE_OBLIGATOIRE"
    reponses.enregistrer(base, e.client_id, "litige", "gestionnaire", facture_id=e.id, texte="Marchandise abîmée")
    assert moteur.etat(base, e.id).statut == "en_litige"


def test_reponse_sur_facture_d_un_autre_client(base):
    e = _premiere_de_la_file(base)
    autre = base.execute("SELECT id FROM factures WHERE client_id <> ? LIMIT 1", (e.client_id,)).fetchone()[0]
    with pytest.raises(ErreurMetier) as exc:
        reponses.enregistrer(base, e.client_id, "litige", "gestionnaire", facture_id=autre)
    assert exc.value.code == "FACTURE_INCONNUE"
