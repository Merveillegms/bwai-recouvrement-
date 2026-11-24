"""Processus d'envoi « lent », lancé puis tué brutalement par tests/test_coupure.py.

Le connecteur attend avant ET après l'écriture du message : une coupure peut donc tomber
avant l'envoi, ou après l'envoi mais avant son enregistrement en base (le cas le plus piégeux).
"""
import time
from datetime import datetime

from app import relances
from app.connecteurs import BacASable
from app.db import connecter


class BacASableLent(BacASable):
    def envoyer(self, envoi):
        time.sleep(0.15)
        accuse = super().envoyer(envoi)
        time.sleep(0.15)
        return accuse


if __name__ == "__main__":
    conn = connecter()
    relances.envoyer(conn, connecteur=BacASableLent(), maintenant=datetime(2026, 12, 15, 10, 0))
