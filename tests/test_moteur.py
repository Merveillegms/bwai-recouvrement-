"""Non-régression : après import + rapprochement, chaque facture et chaque paiement du jeu piégé
obtient exactement le résultat fixé par l'oracle (attendus.json)."""
from decimal import Decimal

import pytest

from app import etat as moteur
from app import journal, rapprochement, statuts
from app.montants import depuis_unites_mineures


@pytest.fixture
def moteur_demo(demo):
    conn, rapports = demo
    resume = rapprochement.rapprocher_tout(conn)
    return conn, resume


def _par_cle(conn):
    return {(e.code_client, e.numero): e for e in moteur.etats(conn)}


def test_chaque_facture_conforme_a_l_oracle(moteur_demo, attendus):
    conn, _ = moteur_demo
    etats = _par_cle(conn)
    erreurs = []
    for x in attendus["factures"]:
        if x["issue"] == "rejetee":
            continue
        e = etats[(x["code_client"], x["numero"])]
        obtenu = {
            "statut": e.statut, "jours_retard": e.jours_retard, "tranche": e.tranche,
            "solde": depuis_unites_mineures(e.solde, e.decimales),
            "total_paye": depuis_unites_mineures(e.total_paye, e.decimales),
            "trop_percu": depuis_unites_mineures(e.trop_percu, e.decimales),
            "drapeaux": sorted(e.drapeaux),
        }
        attendu = {
            "statut": x["statut"], "jours_retard": x["jours_retard"], "tranche": x["tranche"],
            "solde": Decimal(x["solde"]), "total_paye": Decimal(x["total_paye"]),
            "trop_percu": Decimal(x["trop_percu"]), "drapeaux": sorted(x["drapeaux"]),
        }
        if obtenu != attendu:
            ecarts = {k: (attendu[k], obtenu[k]) for k in attendu if attendu[k] != obtenu[k]}
            erreurs.append(f"{x['cas']} {x['numero']} : {ecarts}")
    assert not erreurs, "\n".join(erreurs)


def test_statut_enregistre_aligne(moteur_demo):
    conn, _ = moteur_demo
    assert all(e.statut == e.statut_enregistre for e in moteur.etats(conn))


def test_chaque_paiement_conforme_a_l_oracle(moteur_demo, attendus):
    conn, _ = moteur_demo
    erreurs = []
    for p in attendus["paiements"]:
        if p["issue"] == "rejete":
            continue  # rejeté dès l'import (doublon de transaction)
        ligne = conn.execute(
            "SELECT p.*, f.numero, c.code FROM paiements p"
            " LEFT JOIN factures f ON f.id = coalesce(p.facture_id, p.facture_proposee_id)"
            " LEFT JOIN clients c ON c.id = f.client_id WHERE p.id_transaction = ?", (p["id_transaction"],)).fetchone()
        if p["issue"] == "rapproche_auto":
            obtenu = (ligne["statut_rapprochement"], ligne["methode_rapprochement"], ligne["code"], ligne["numero"])
            attendu = ("rapproche", "reference", p["facture"]["code_client"], p["facture"]["numero"])
        else:
            facture = (p["facture"]["code_client"], p["facture"]["numero"]) if p["facture"] else (None, None)
            obtenu = (ligne["statut_rapprochement"], ligne["motif_rapprochement"], ligne["code"], ligne["numero"])
            attendu = ("a_valider", p["codes"][0], *facture)
        if obtenu != attendu:
            erreurs.append(f"{p['cas']} : attendu {attendu}, obtenu {obtenu}")
    assert not erreurs, "\n".join(erreurs)


def test_rapprochement_idempotent(moteur_demo):
    conn, resume = moteur_demo
    assert resume["RAPPROCHE"] == 30
    versions = {e.id: e.version for e in moteur.etats(conn)}
    nb_journal = conn.execute("SELECT count(*) FROM journal").fetchone()[0]
    assert rapprochement.rapprocher_tout(conn) == {}
    assert {e.id: e.version for e in moteur.etats(conn)} == versions
    assert conn.execute("SELECT count(*) FROM journal").fetchone()[0] == nb_journal


def test_recalcul_idempotent_et_passage_a_echeance(moteur_demo):
    conn, _ = moteur_demo
    assert statuts.recalculer_tout(conn) == {}
    from app import parametres
    parametres.ecrire(conn, "date_du_jour_simulee", "2027-03-01", "test")  # tout est échu
    changements = statuts.recalculer_tout(conn)
    assert changements.get("a_echoir->echue", 0) > 0
    assert statuts.recalculer_tout(conn) == {}
    assert not [e for e in moteur.etats(conn) if e.statut == "a_echoir"]


def test_aucune_facture_payee_sans_paiement(moteur_demo):
    conn, _ = moteur_demo
    for e in moteur.etats(conn):
        if e.statut == "payee":
            assert e.total_paye + e.total_avoirs >= e.montant_ttc


def test_journal_explique_chaque_changement_de_statut(moteur_demo):
    conn, _ = moteur_demo
    assert journal.verifier_chaine(conn) == []
    payees = [e for e in moteur.etats(conn) if e.statut == "payee"]
    for e in payees:
        entree = conn.execute("SELECT * FROM journal WHERE action = 'changement_statut' AND objet_id = ?"
                              " ORDER BY id DESC LIMIT 1", (str(e.id),)).fetchone()
        assert entree is not None and '"payee"' in entree["apres"] and entree["regle"].startswith("RAPPROCHEMENT")


def test_jours_ouvres_en_option(moteur_demo):
    conn, _ = moteur_demo
    from app import parametres
    parametres.ecrire(conn, "retard_jours_ouvres", True, "test")
    e = next(x for x in moteur.etats(conn) if x.date_echeance == "2026-11-30")  # fin de mois, 15 j calendaires
    assert e.jours_retard == 11  # 1er-15 décembre 2026 : 11 jours ouvrés, aucun férié
