import pytest

from app import journal, resolution
from app.resolution import ResolutionImpossible


def _anomalie(conn, code, fichier="factures_lot1.csv"):
    return conn.execute("SELECT a.* FROM import_anomalies a JOIN imports i ON i.id = a.import_id"
                        " WHERE a.code = ? AND i.fichier = ?", (code, fichier)).fetchone()


def _facture(conn, motif):
    return conn.execute("SELECT * FROM factures WHERE motif_verification = ?", (motif,)).fetchone()


def test_remplacer_un_conflit(demo):
    conn, _ = demo
    a = _anomalie(conn, "CONFLIT_NUMERO")
    with pytest.raises(ResolutionImpossible, match="motif"):
        resolution.resoudre_anomalie(conn, a["id"], "remplacer", "validateur")
    resolution.resoudre_anomalie(conn, a["id"], "remplacer", "validateur", "Montant corrigé par le client")
    import json
    donnees = json.loads(a["donnees"])
    f = conn.execute("SELECT * FROM factures WHERE numero = ?", (donnees["numero_facture"],)).fetchone()
    assert f["montant_ttc"] == int(donnees["montant_ttc"])
    assert f["version"] == 2
    with pytest.raises(ResolutionImpossible) as exc:
        resolution.resoudre_anomalie(conn, a["id"], "ignorer", "validateur")
    assert exc.value.code == "DEJA_RESOLUE"
    assert conn.execute("SELECT count(*) FROM journal WHERE action = 'remplacement_facture'").fetchone()[0] == 1
    assert journal.verifier_chaine(conn) == []


def test_ignorer_un_doublon(demo):
    conn, _ = demo
    a = _anomalie(conn, "DOUBLON_EXACT")
    resolution.resoudre_anomalie(conn, a["id"], "ignorer", "gestionnaire")
    assert conn.execute("SELECT resolution FROM import_anomalies WHERE id = ?", (a["id"],)).fetchone()[0] == "ignoree"


def test_seul_un_conflit_peut_remplacer(demo):
    conn, _ = demo
    a = _anomalie(conn, "DOUBLON_EXACT")
    with pytest.raises(ResolutionImpossible) as exc:
        resolution.resoudre_anomalie(conn, a["id"], "remplacer", "validateur", "essai")
    assert exc.value.code == "NON_APPLICABLE"


def test_remplacement_refuse_si_facture_engagee(demo):
    conn, _ = demo
    a = _anomalie(conn, "CONFLIT_NUMERO")
    import json
    numero = json.loads(a["donnees"])["numero_facture"]
    fid = conn.execute("SELECT id FROM factures WHERE numero = ?", (numero,)).fetchone()[0]
    conn.execute("INSERT INTO paiements (id_transaction, date_paiement, montant, devise, source, statut_rapprochement,"
                 " facture_id) VALUES ('X1', '2026-12-01', 1000, 'XOF', 'manuel', 'rapproche', ?)", (fid,))
    with pytest.raises(ResolutionImpossible) as exc:
        resolution.resoudre_anomalie(conn, a["id"], "remplacer", "validateur", "essai")
    assert exc.value.code == "FACTURE_ENGAGEE"


def test_confirmer_un_quasi_doublon(demo):
    conn, _ = demo
    f = _facture(conn, "QUASI_DOUBLON")
    resolution.confirmer_facture(conn, f["id"], "validateur", "Deux livraisons distinctes")
    apres = conn.execute("SELECT * FROM factures WHERE id = ?", (f["id"],)).fetchone()
    assert apres["a_verifier"] == 0 and apres["version"] == f["version"] + 1
    with pytest.raises(ResolutionImpossible):
        resolution.confirmer_facture(conn, f["id"], "validateur")


def test_annuler_exige_un_motif_et_cloture(demo):
    conn, _ = demo
    f = _facture(conn, "QUASI_DOUBLON")
    with pytest.raises(ResolutionImpossible, match="motif"):
        resolution.annuler_facture(conn, f["id"], "validateur", "  ")
    resolution.annuler_facture(conn, f["id"], "validateur", "Doublon de saisie")
    apres = conn.execute("SELECT * FROM factures WHERE id = ?", (f["id"],)).fetchone()
    assert (apres["statut"], apres["a_verifier"], apres["motif_cloture"]) == ("cloturee", 0, "Doublon de saisie")


def test_client_inconnu_a_valider_avant_ses_factures(demo):
    conn, _ = demo
    f = _facture(conn, "CLIENT_INCONNU")
    with pytest.raises(ResolutionImpossible) as exc:
        resolution.confirmer_facture(conn, f["id"], "validateur")
    assert exc.value.code == "CLIENT_EN_ATTENTE"
    with pytest.raises(ResolutionImpossible):
        resolution.valider_client(conn, f["client_id"], "validateur", nom="X", canal_prefere="fax")
    liberees = resolution.valider_client(conn, f["client_id"], "validateur", nom="Menuiserie Dossou",
                                         telephone="+229 0190000099", canal_prefere="sms")
    assert liberees == 1
    assert conn.execute("SELECT a_verifier FROM factures WHERE id = ?", (f["id"],)).fetchone()[0] == 0
