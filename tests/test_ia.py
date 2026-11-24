"""IA encadrée : la rédaction ne peut jamais introduire une valeur fausse ; la classification propose,
l'humain décide ; aucune donnée personnelle n'est envoyée au modèle distant."""
import json
from datetime import date, datetime

import httpx
import pytest

from app import etat as moteur
from app import parametres, priorisation, rapprochement, relances, validation
from app.erreurs import ErreurMetier
from app.ia import accueil, classification
from app.ia.evaluation import evaluer_classification
from app.ia.fournisseurs import ErreurIA, Faux, Gemini, HuggingFace, fournisseur_configure
from app.ia.redaction import RAISON_IA, rediger_lots_du_jour, revenir_au_gabarit
from app.montants import formater
from app.references import formater_reference

MATIN = datetime(2026, 12, 15, 10, 0)


class Adaptatif(Faux):
    """Rédige un message correct en utilisant exactement les marqueurs demandés."""

    def __init__(self, gabarit: str | None = None):
        super().__init__([])
        self.gabarit = gabarit

    def generer(self, systeme, demande):
        self.demandes.append((systeme, demande))
        marqueurs = json.loads(demande)["marqueurs_obligatoires"]
        corps = self.gabarit or ("Bonjour {CLIENT}, nous espérons que vous allez bien et que les affaires se portent "
                                 "bien.\nSauf erreur de notre part, le règlement suivant reste attendu :\n{RESTE}\n"
                                 "Bonne journée à vous.")
        reste = "\n".join(m for m in marqueurs if m != "[[CLIENT]]")
        return json.dumps({"message": corps.replace("{CLIENT}", "[[CLIENT]]").replace("{RESTE}", reste)})


@pytest.fixture
def base(demo):
    conn, _ = demo
    rapprochement.rapprocher_tout(conn)
    relances.preparer(conn)
    parametres.ecrire(conn, "ia_active", True, "validateur")
    return conn


def _validateur(conn):
    return dict(conn.execute("SELECT id, identifiant, role FROM utilisateurs WHERE role = 'validateur'").fetchone())


# ------------------------------------------------------------------- rédaction
def test_redaction_acceptee_puis_validation_humaine(base):
    avant = {r["lot_envoi"]: r["statut"] for r in base.execute("SELECT * FROM relances WHERE etape <> 'R5'")}
    resultat = rediger_lots_du_jour(base, Adaptatif(), "gestionnaire", limite=5)
    assert resultat["acceptes"] == 5 and resultat["rejetes"] == 0
    for l in resultat["lots"]:
        rel = base.execute("SELECT * FROM relances WHERE lot_envoi = ?", (l["lot"],)).fetchall()
        assert all(r["redige_par_ia"] == 1 and r["statut"] == "a_valider" for r in rel)
        assert RAISON_IA in rel[0]["motif_validation"]
        assert rel[0]["message_gabarit"] and "[[" not in rel[0]["message"]
        for r in rel:  # chaque valeur insérée par le code, à l'identique
            e = moteur.etat(base, r["facture_id"])
            assert formater(e.solde, e.devise, e.decimales) in r["message"]
            assert formater_reference(e.reference_paiement) in r["message"]
        assert avant[l["lot"]] in ("validee", "a_valider")
    assert base.execute("SELECT count(*) FROM ia_appels WHERE statut = 'accepte'").fetchone()[0] == 5
    ia = base.execute("SELECT * FROM journal WHERE action = 'redaction_ia'").fetchone()
    assert ia["type_acteur"] == "ia" and ia["acteur"].startswith("faux:")


def test_aucune_donnee_personnelle_envoyee_au_modele(base):
    f = Adaptatif()
    rediger_lots_du_jour(base, f, "gestionnaire", limite=30)
    noms = [r["nom"] for r in base.execute("SELECT nom FROM clients")]
    telephones = [r["telephone"] for r in base.execute("SELECT telephone FROM clients WHERE telephone IS NOT NULL")]
    for systeme, demande in f.demandes:
        envoye = systeme + demande
        assert not any(n in envoye for n in noms)
        assert not any(t in envoye for t in telephones)
        assert "FCFA" not in envoye and "RC" not in demande and "FAC-" not in envoye
        assert set(json.loads(demande)) >= {"etape", "canal", "marqueurs_obligatoires"}


@pytest.mark.parametrize("sortie, raison", [
    ('{"message": "Bonjour [[CLIENT]], merci de régler les 125 000 FCFA. [[FACTURES]] [[TOTAL]] [[PAIEMENT]] [[SIGNATURE]]"}', "chiffre"),
    ('{"message": "Bonjour [[CLIENT]]. [[PAIEMENT]] [[SIGNATURE]]"}', "[[FACTURES]]"),
    ('{"message": "Bonjour [[CLIENT]], sinon un huissier passera. [[FACTURES]] [[TOTAL]] [[PAIEMENT]] [[SIGNATURE]]"}', "huissier"),
    ('{"message": "Bonjour [[CLIENT]] [[NOM_GERANT]] [[FACTURES]] [[TOTAL]] [[PAIEMENT]] [[SIGNATURE]]"}', "inconnu"),
    ("Voici votre message de relance !", "illisible"),
])
def test_sortie_non_conforme_rejetee_et_gabarit_conserve(base, sortie, raison):
    lot = base.execute("SELECT lot_envoi, message FROM relances WHERE etape <> 'R5' ORDER BY id LIMIT 1").fetchone()
    resultat = rediger_lots_du_jour(base, Faux([sortie]), "gestionnaire", limite=1)
    assert resultat["lots"][0]["statut"] == "rejete"
    assert any(raison in r for r in resultat["lots"][0]["raisons"]), resultat
    apres = base.execute("SELECT message, redige_par_ia FROM relances WHERE lot_envoi = ?", (lot["lot_envoi"],)).fetchone()
    assert (apres["message"], apres["redige_par_ia"]) == (lot["message"], 0)  # repli sur le gabarit


def test_panne_du_modele_sans_consequence(base):
    resultat = rediger_lots_du_jour(base, Faux([ErreurIA("Gemini a répondu 503")]), "gestionnaire", limite=1)
    assert resultat["erreurs"] == 1
    assert base.execute("SELECT count(*) FROM relances WHERE redige_par_ia = 1").fetchone()[0] == 0
    assert base.execute("SELECT statut FROM ia_appels").fetchone()[0] == "erreur"


def test_interrupteur_global(base):
    parametres.ecrire(base, "ia_active", False, "validateur")
    with pytest.raises(ErreurMetier) as exc:
        rediger_lots_du_jour(base, Adaptatif(), "gestionnaire")
    assert exc.value.code == "IA_DESACTIVEE"
    # Sans IA, tout le reste fonctionne : préparation, validation, envoi.
    assert relances.envoyer(base, maintenant=MATIN)["envoyes"] >= 0


def test_retour_au_gabarit(base):
    resultat = rediger_lots_du_jour(base, Adaptatif(), "gestionnaire", limite=1)
    lot = resultat["lots"][0]["lot"]
    gabarit = base.execute("SELECT message_gabarit FROM relances WHERE lot_envoi = ?", (lot,)).fetchone()[0]
    revenir_au_gabarit(base, lot, "validateur")
    r = base.execute("SELECT message, redige_par_ia, motif_validation FROM relances WHERE lot_envoi = ?", (lot,)).fetchone()
    assert r["message"] == gabarit and r["redige_par_ia"] == 0 and RAISON_IA not in (r["motif_validation"] or "")


def test_message_ia_approuve_puis_envoye(base):
    lot = rediger_lots_du_jour(base, Adaptatif(), "gestionnaire", limite=1)["lots"][0]["lot"]
    assert validation.approuver(base, lot, _validateur(base))["statut"] == "validee"
    assert lot in relances.envoyer(base, maintenant=MATIN)["lots"]  # revérifié à l'envoi


# --------------------------------------------------------------- classification
def test_qualite_mesuree_sur_le_jeu_d_evaluation():
    ev = evaluer_classification()
    assert ev["exemples_evaluation"] >= 40
    assert ev["exactitude"] >= 0.8
    assert ev["litige"]["rappel_signalement"] == 1.0  # aucun litige manqué : priorité absolue


def test_classification_deterministe_et_explicable():
    a, b = classification.classer("La marchandise était abîmée, je refuse de payer"), classification.classer(
        "La marchandise était abîmée, je refuse de payer")
    assert a == b and a.categorie == "litige" and a.mots_decisifs
    assert abs(sum(a.probabilites.values()) - 1) < 0.01


@pytest.mark.parametrize("texte, attendu", [
    ("je paie vendredi", date(2026, 12, 18)), ("demain sans faute", date(2026, 12, 16)),
    ("après-demain", date(2026, 12, 17)), ("le 20", date(2026, 12, 20)), ("le 5", date(2027, 1, 5)),
    ("avant la fin du mois", date(2026, 12, 31)), ("dans 3 jours", date(2026, 12, 18)),
    ("le 05/01", date(2027, 1, 5)), ("le 20 janvier", date(2027, 1, 20)), ("mardi", date(2026, 12, 22)),
    ("semaine prochaine", date(2026, 12, 22)), ("bientôt", None),
])
def test_extraction_de_date(texte, attendu):
    assert classification.extraire_date(texte, date(2026, 12, 15)) == attendu  # mardi 15/12/2026


def test_reponse_entrante_proposee_puis_confirmee(base):
    e = priorisation.file_du_jour(base)[0][-1].facture
    r = accueil.recevoir(base, e.client_id, "Bonjour, je passe payer vendredi au bureau", "gestionnaire", e.id)
    p = r["proposition"]
    assert p["categorie"] == "promesse" and p["date"] == "2026-12-18"
    # rien n'a encore d'effet : la facture reste dans la file
    assert e.id in {x.facture.id for x in priorisation.file_du_jour(base)[0]}
    assert accueil.confirmer(base, r["id"], "promesse", "gestionnaire", date_promise=p["date"])["statut"] == "confirmee"
    assert {x.facture.id: x.code for x in priorisation.file_du_jour(base)[1]}[e.id] == "PROMESSE_EN_COURS"
    with pytest.raises(ErreurMetier) as exc:
        accueil.confirmer(base, r["id"], "promesse", "gestionnaire", date_promise=p["date"])
    assert exc.value.code == "DEJA_TRAITEE"


def test_litige_jamais_automatique(base):
    e = priorisation.file_du_jour(base)[0][-1].facture
    r = accueil.recevoir(base, e.client_id, "Les cartons étaient mouillés, je conteste la facture", "gestionnaire")
    assert r["proposition"]["litige_possible"]
    assert moteur.etat(base, e.id).statut != "en_litige"  # proposition seulement
    with pytest.raises(ErreurMetier) as exc:
        accueil.confirmer(base, r["id"], "litige", "gestionnaire")  # pas de facture désignée
    assert exc.value.code == "FACTURE_OBLIGATOIRE"
    accueil.confirmer(base, r["id"], "litige", "gestionnaire", facture_id=e.id)
    assert moteur.etat(base, e.id).statut == "en_litige"


def test_correction_humaine_et_ia_desactivee(base):
    client = base.execute("SELECT id FROM clients WHERE code = 'C001'").fetchone()[0]
    r = accueil.recevoir(base, client, "ok d'accord", "gestionnaire")
    assert accueil.confirmer(base, r["id"], "sans_rapport", "gestionnaire")["statut"] == "corrigee"
    parametres.ecrire(base, "ia_active", False, "validateur")
    sans = accueil.recevoir(base, client, "Je paie demain", "gestionnaire")
    assert sans["proposition"] is None
    with pytest.raises(ErreurMetier):
        accueil.ecarter(base, sans["id"], "gestionnaire", "")
    accueil.ecarter(base, sans["id"], "gestionnaire", "Doublon d'un message déjà saisi")


# ------------------------------------------------------------------ fournisseurs
def test_gemini_requete_et_reponse():
    vues = []

    def repondre(requete):
        vues.append(requete)
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": '{"message": "ok"}'}]}}]})

    g = Gemini("cle-secrete", "gemini-3.5-flash", httpx.Client(transport=httpx.MockTransport(repondre)))
    assert g.generer("système", "demande") == '{"message": "ok"}'
    assert vues[0].headers["x-goog-api-key"] == "cle-secrete" and "gemini-3.5-flash:generateContent" in str(vues[0].url)
    corps = json.loads(vues[0].content)
    assert corps["generationConfig"]["responseMimeType"] == "application/json"


def test_erreurs_fournisseurs_sans_fuite_de_cle():
    refus = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(429, json={})))
    with pytest.raises(ErreurIA) as exc:
        Gemini("cle-secrete", client=refus, pause_s=0).generer("s", "d")
    assert "429" in str(exc.value) and "cle-secrete" not in str(exc.value)
    with pytest.raises(ErreurIA):
        HuggingFace("hf_secret", client=refus).generer("s", "d")


def test_huggingface_format_openai():
    def repondre(requete):
        assert requete.headers["authorization"] == "Bearer hf_x"
        assert json.loads(requete.content)["model"] == "meta-llama/Llama-3.1-8B-Instruct"
        return httpx.Response(200, json={"choices": [{"message": {"content": "texte"}}]})

    hf = HuggingFace("hf_x", client=httpx.Client(transport=httpx.MockTransport(repondre)))
    assert hf.generer("s", "d") == "texte"


def test_choix_du_fournisseur(monkeypatch):
    for v in ("RECOUVREMENT_IA_FOURNISSEUR", "GEMINI_API_KEY", "HF_TOKEN"):
        monkeypatch.delenv(v, raising=False)
    assert fournisseur_configure() is None
    monkeypatch.setenv("HF_TOKEN", "hf_x")
    assert fournisseur_configure().nom == "huggingface"
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    assert fournisseur_configure().nom == "gemini"
    monkeypatch.setenv("RECOUVREMENT_IA_FOURNISSEUR", "aucun")
    assert fournisseur_configure() is None
