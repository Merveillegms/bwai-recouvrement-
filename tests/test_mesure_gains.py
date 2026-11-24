"""Le comparatif « référence naïve / outil » reste vrai à chaque version : l'outil ne commet aucune des erreurs."""
from app import mesure_gains


def test_outil_sans_erreur_face_a_la_reference():
    r = mesure_gains.mesurer()
    naif, outil = r["reference_naive"]["erreurs"], r["outil"]["erreurs"]
    assert all(v == 0 for v in outil.values()), outil
    for piege in ("doublons_relances", "litiges_relances", "lignes_invalides_relancees", "paiement_recu_non_rapproche_relance"):
        assert naif[piege] > 0, piege  # le jeu piégé contient bien chaque piège
    assert r["outil"]["anomalies_signalees"] == naif["anomalies_non_signalees"]
    assert r["outil"]["du_traite_premiere_heure_fcfa"] > r["reference_naive"]["du_traite_premiere_heure_fcfa"]
    assert r["outil"]["messages"] < r["reference_naive"]["messages"]
