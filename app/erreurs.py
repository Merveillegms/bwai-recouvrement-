"""Erreur métier commune : un code stable (pour le frontend et les tests) et un message lisible."""
from __future__ import annotations


class ErreurMetier(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code, self.message = code, message


def exiger_motif(motif: str | None) -> str:
    if not motif or not motif.strip():
        raise ErreurMetier("MOTIF_OBLIGATOIRE", "Un motif est obligatoire pour cette décision")
    return motif.strip()
