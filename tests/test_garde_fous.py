"""Garde-fous : vérification des messages, revalidation avant envoi, reprise, verrou, arrêt d'urgence."""
from datetime import datetime

import pytest

from app import etat as moteur
from app import garde_fous, parametres, rapprochement, relances, statuts, validation, verrous
from app.connecteurs import BacASable, dossier_sortants
from app.erreurs import ErreurMetier
from app.montants import formater
from app.references import formater_reference

MATIN = datetime(2026, 12, 15, 10, 0)


@pytest.fixture
def validateur(demo):
    conn, _ = demo
    return dict(conn.execute("SELECT id, identifiant, role FROM utilisateurs WHERE role = 'validateur'").fetchone())


@pytest.fixture
def prete(demo, validateur):
    """Relances préparées et toutes approuvées (sauf message à corriger)."""
    conn, _ = demo
    rapprochement.rapprocher_tout(conn)
    relances.preparer(conn)
    for lot in {r[0] for r in conn.execute("SELECT lot_envoi FROM relances WHERE statut = 'a_valider'")}:
        try:
            validation.approuver(conn, lot, validateur)
        except ErreurMetier:
            pass
    return conn


def _lot_valide(conn, etape_max="R4"):
    r = conn.execute("SELECT * FROM relances WHERE statut = 'validee' AND etape <= ? ORDER BY id LIMIT 1",
                     (etape_max,)).fetchone()
    return r["lot_envoi"], r["facture_id"]


# ---------------------------------------------------------------- vérification
def test_message_conforme(prete):
    lot, _ = _lot_valide(prete)
    rel = prete.execute("SELECT * FROM relances WHERE lot_envoi = ?", (lot,)).fetchall()
    etats = [moteur.etat(prete, r["facture_id"]) for r in rel]
    texte = garde_fous.corps_du_message(rel[0]["message"])
    assert garde_fous.verifier_message(texte, etats, rel[0]["canal"]) == []


def test_message_altere_detecte(prete):
    lot, fid = _lot_valide(prete)
    rel = prete.execute("SELECT * FROM relances WHERE lot_envoi = ?", (lot,)).fetchall()
    etats = [moteur.etat(prete, r["facture_id"]) for r in rel]
    e = moteur.etat(prete, fid)
    texte = garde_fous.corps_du_message(rel[0]["message"])
    solde = formater(e.solde, e.devise, e.decimales)
    faux = texte.replace(solde, formater(e.solde + 1000, e.devise, e.decimales))
    ecarts = garde_fous.verifier_message(faux, etats, rel[0]["canal"])
    assert any("absent ou différent" in x for x in ecarts) and any("non justifié" in x for x in ecarts)
    sans_ref = texte.replace(formater_reference(e.reference_paiement), "RC-0000-0000-0")
    ecarts = garde_fous.verifier_message(sans_ref, etats, rel[0]["canal"])
    assert any("référence inconnue" in x for x in ecarts)
    assert garde_fous.verifier_message(texte + "\nTu dois payer.", etats, rel[0]["canal"]) == ["ton : tutoiement"]


# --------------------------------------------------------- revalidation avant envoi
def test_paiement_arrive_entre_validation_et_envoi(prete):
    lot, fid = _lot_valide(prete)
    e = moteur.etat(prete, fid)
    prete.execute("INSERT INTO paiements (id_transaction, date_paiement, montant, devise, reference_citee, source)"
                  " VALUES ('TX-TARDIF', '2026-12-15', ?, ?, ?, 'mobile_money')",
                  (e.solde // 2, e.devise, e.reference_paiement))
    rapprochement.rapprocher_tout(prete)
    resume = relances.envoyer(prete, maintenant=MATIN)
    assert resume["annules"] >= 1 and lot not in resume["lots"]
    r = prete.execute("SELECT * FROM relances WHERE facture_id = ?", (fid,)).fetchone()
    assert r["statut"] == "annulee" and "solde changé" in r["motif_annulation"]
    assert not prete.execute("SELECT 1 FROM messages_sortants WHERE cle_envoi = ?", (lot,)).fetchone()
    # La clé est libérée : la facture, toujours due, peut être relancée avec son nouveau solde.
    relances.preparer(prete)
    nouvelle = prete.execute("SELECT * FROM relances WHERE facture_id = ? AND statut <> 'annulee'", (fid,)).fetchone()
    assert nouvelle is not None and nouvelle["solde_prepare"] == moteur.etat(prete, fid).solde


def test_litige_declare_apres_validation(prete):
    lot, fid = _lot_valide(prete)
    statuts.declarer_litige(prete, fid, "gestionnaire", "Client conteste")
    relances.envoyer(prete, maintenant=MATIN)
    r = prete.execute("SELECT * FROM relances WHERE facture_id = ?", (fid,)).fetchone()
    assert r["statut"] == "annulee" and "en_litige" in r["motif_annulation"]


def test_promesse_apres_validation(prete):
    lot, fid = _lot_valide(prete)
    client = prete.execute("SELECT client_id FROM factures WHERE id = ?", (fid,)).fetchone()[0]
    from app import reponses
    reponses.enregistrer(prete, client, "promesse", "gestionnaire", date_promise="2026-12-20")
    relances.envoyer(prete, maintenant=MATIN)
    assert prete.execute("SELECT statut FROM relances WHERE facture_id = ?", (fid,)).fetchone()[0] == "annulee"


# ------------------------------------------------------------------ reprise
class _Mort(BaseException):
    """Simule la mort du processus (n'est pas interceptée comme une panne ordinaire)."""


def test_mort_avant_envoi_puis_reprise(prete):
    class MeurtAvant(BacASable):
        def envoyer(self, envoi):
            raise _Mort

    with pytest.raises(_Mort):
        relances.envoyer(prete, connecteur=MeurtAvant(), maintenant=MATIN)
    assert prete.execute("SELECT count(DISTINCT lot_envoi) FROM relances WHERE statut = 'en_cours_envoi'").fetchone()[0] == 1
    resume = relances.envoyer(prete, maintenant=MATIN)
    assert resume["reprise"] == {"confirmes": 0, "remis_en_file": 1}
    lots = prete.execute("SELECT count(DISTINCT lot_envoi) FROM relances WHERE statut = 'envoyee'").fetchone()[0]
    assert len(list(dossier_sortants().glob("*.txt"))) == lots


def test_mort_apres_envoi_avant_enregistrement(prete):
    appels = []

    class MeurtApres(BacASable):
        def envoyer(self, envoi):
            appels.append(envoi.cle_envoi)
            super().envoyer(envoi)
            raise _Mort

    with pytest.raises(_Mort):
        relances.envoyer(prete, connecteur=MeurtApres(), maintenant=MATIN)

    class Compteur(BacASable):
        def envoyer(self, envoi):
            appels.append(envoi.cle_envoi)
            return super().envoyer(envoi)

    resume = relances.envoyer(prete, connecteur=Compteur(), maintenant=MATIN)
    assert resume["reprise"] == {"confirmes": 1, "remis_en_file": 0}
    assert len(appels) == len(set(appels))  # le lot interrompu n'a jamais été renvoyé
    assert len(list(dossier_sortants().glob("*.txt"))) == len(set(appels))


def test_echec_fournisseur_puis_nouvel_essai(prete):
    class EnPanne(BacASable):
        def envoyer(self, envoi):
            raise ConnectionError("réseau indisponible")

    relances.envoyer(prete, connecteur=EnPanne(), maintenant=MATIN)
    lot = prete.execute("SELECT lot_envoi FROM relances WHERE statut = 'echec' LIMIT 1").fetchone()[0]
    relances.reessayer(prete, lot, "gestionnaire")
    assert lot in relances.envoyer(prete, maintenant=MATIN)["lots"]
    with pytest.raises(ErreurMetier):
        relances.reessayer(prete, lot, "gestionnaire")


# ------------------------------------------------------------- verrou et arrêt
def test_deux_envois_concurrents_refuses(prete):
    detenteur = verrous.nouveau_detenteur()
    assert verrous.acquerir(prete, "envoi", detenteur)
    with pytest.raises(ErreurMetier) as exc:
        relances.envoyer(prete, maintenant=MATIN)
    assert exc.value.code == "TRAITEMENT_EN_COURS"
    verrous.liberer(prete, "envoi", detenteur)
    assert relances.envoyer(prete, maintenant=MATIN)["envoyes"] > 0


def test_verrou_d_un_processus_mort_repris(prete):
    prete.execute("INSERT INTO verrous VALUES ('envoi', '999999:mort', '2026-01-01', '2999-01-01')")
    assert relances.envoyer(prete, maintenant=MATIN)["envoyes"] > 0


def test_arret_urgence_entre_validation_et_envoi(prete):
    parametres.ecrire(prete, "arret_urgence", True, "validateur")
    with pytest.raises(ErreurMetier) as exc:
        relances.envoyer(prete, maintenant=MATIN)
    assert exc.value.code == "ARRET_URGENCE"
    assert not list(dossier_sortants().glob("*.txt"))
