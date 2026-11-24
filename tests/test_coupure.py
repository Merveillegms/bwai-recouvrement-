"""Démonstration de sortie de la phase 5 : « je tue le programme en pleine file d'envoi, je le relance,
aucune relance en double ». Un vrai processus est lancé puis tué brutalement (TerminateProcess / SIGKILL),
à des instants différents."""
import os
import subprocess
import sys
import time
from datetime import datetime

import pytest

from app import config, journal, rapprochement, relances, validation
from app.connecteurs import dossier_sortants
from app.db import connecter, migrer
from app.erreurs import ErreurMetier
from tests.conftest import DATE_DEMO, importer_demo

MATIN = datetime(2026, 12, 15, 10, 0)


def _base_prete(chemin, attendus):
    from app import parametres, seed

    conn = connecter(chemin)
    migrer(conn)
    seed.initialiser(conn)
    parametres.ecrire(conn, "date_du_jour_simulee", DATE_DEMO, "test")
    importer_demo(conn, attendus)
    rapprochement.rapprocher_tout(conn)
    relances.preparer(conn)
    validateur = dict(conn.execute("SELECT id, identifiant, role FROM utilisateurs WHERE role = 'validateur'").fetchone())
    for lot in {r[0] for r in conn.execute("SELECT lot_envoi FROM relances WHERE statut = 'a_valider'")}:
        try:
            validation.approuver(conn, lot, validateur)
        except ErreurMetier as e:  # message à corriger à la main (SMS trop long) : reste en attente
            assert e.code == "MESSAGE_A_CORRIGER"
    return conn


@pytest.mark.parametrize("delai", [0.8, 1.6, 2.7])
def test_coupure_brutale_puis_reprise_sans_doublon(tmp_path, attendus, delai):
    chemin = tmp_path / "coupure.db"
    conn = _base_prete(chemin, attendus)
    lots = {r[0] for r in conn.execute("SELECT lot_envoi FROM relances WHERE statut = 'validee'")}
    assert len(lots) > 10

    env = os.environ | {"RECOUVREMENT_DB": str(chemin), "RECOUVREMENT_SORTANTS": str(dossier_sortants()),
                        "PYTHONPATH": str(config.RACINE)}
    processus = subprocess.Popen([sys.executable, str(config.RACINE / "tests" / "_processus_envoi.py")],
                                 env=env, cwd=config.RACINE)
    time.sleep(delai)
    processus.kill()  # coupure brutale : aucun « finally », aucun nettoyage
    processus.wait()
    envoyes_avant = conn.execute("SELECT count(DISTINCT lot_envoi) FROM relances WHERE statut = 'envoyee'").fetchone()[0]
    assert envoyes_avant < len(lots), "la coupure doit tomber en cours de file"

    resume = relances.envoyer(conn, maintenant=MATIN)  # redémarrage
    print(f"\n[coupure à {delai} s] envoyés avant : {envoyes_avant}/{len(lots)} ; reprise : {resume['reprise']}")

    fichiers = sorted(dossier_sortants().glob("*.txt"))
    assert len(fichiers) == len(lots), "chaque lot envoyé une et une seule fois"
    assert conn.execute("SELECT count(*) FROM messages_sortants WHERE statut = 'envoye'").fetchone()[0] == len(lots)
    marques = ",".join("?" * len(lots))
    assert conn.execute(f"SELECT count(*) FROM relances WHERE lot_envoi IN ({marques}) AND statut <> 'envoyee'",
                        tuple(lots)).fetchone()[0] == 0
    envois = conn.execute("SELECT count(*) FROM journal WHERE action IN ('envoi_relance', 'reprise_envoi_confirme')"
                          ).fetchone()[0]
    assert envois == len(lots)
    assert journal.verifier_chaine(conn) == []
    assert resume["reprise"]["confirmes"] + resume["reprise"]["remis_en_file"] <= 1
    # Relancer encore une fois ne change rien.
    assert relances.envoyer(conn, maintenant=MATIN)["envoyes"] == 0
    assert len(list(dossier_sortants().glob("*.txt"))) == len(lots)
    conn.close()
