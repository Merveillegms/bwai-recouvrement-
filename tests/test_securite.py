from app.securite import hacher_mot_de_passe, verifier_mot_de_passe


def test_mot_de_passe():
    h = hacher_mot_de_passe("secret")
    assert verifier_mot_de_passe("secret", h)
    assert not verifier_mot_de_passe("Secret", h)
    assert hacher_mot_de_passe("secret") != h  # sel aléatoire
    assert not verifier_mot_de_passe("secret", "format-invalide")
