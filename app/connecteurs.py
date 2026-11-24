"""Connecteurs d'envoi. Une seule interface ; le bac à sable écrit les messages dans un dossier
au lieu de les envoyer. Brancher un vrai fournisseur (SMS, WhatsApp, e-mail) = écrire une classe
de plus, sans rien changer ailleurs.

Comme un vrai fournisseur, le bac à sable déduplique par clé d'envoi : renvoyer la même clé
renvoie le même accusé sans produire un second message (base de la reprise après interruption).
"""
from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app import config


@dataclass(frozen=True)
class Envoi:
    cle_envoi: str
    canal: str
    destinataire: str
    objet: str | None
    texte: str


class Connecteur(Protocol):
    nom: str

    def envoyer(self, envoi: Envoi) -> str:
        """Envoie et retourne l'accusé du fournisseur. Idempotent pour une même clé d'envoi."""

    def accuse(self, cle_envoi: str) -> str | None:
        """Accusé d'un envoi déjà effectué pour cette clé, ou None s'il n'a pas eu lieu."""


def dossier_sortants() -> Path:
    return Path(os.environ.get("RECOUVREMENT_SORTANTS", config.RACINE / "data" / "sortants"))


class BacASable:
    nom = "bac_a_sable"

    def __init__(self, dossier: Path | None = None) -> None:
        self.dossier = dossier or dossier_sortants()

    def _fichier(self, cle_envoi: str) -> Path:
        return self.dossier / (re.sub(r"[^A-Za-z0-9_-]", "_", cle_envoi) + ".txt")

    def accuse(self, cle_envoi: str) -> str | None:
        fichier = self._fichier(cle_envoi)
        if not fichier.exists():
            return None
        return fichier.read_text(encoding="utf-8").splitlines()[0].removeprefix("ACCUSE: ")

    def envoyer(self, envoi: Envoi) -> str:
        deja = self.accuse(envoi.cle_envoi)
        if deja:
            return deja
        self.dossier.mkdir(parents=True, exist_ok=True)
        accuse = "SBX-" + hashlib.sha256(envoi.cle_envoi.encode()).hexdigest()[:12].upper()
        entete = [f"ACCUSE: {accuse}", f"CANAL: {envoi.canal}", f"A: {envoi.destinataire}"]
        if envoi.objet:
            entete.append(f"OBJET: {envoi.objet}")
        # Écriture atomique : un fichier partiel n'est jamais pris pour un envoi réussi.
        temporaire = self._fichier(envoi.cle_envoi).with_suffix(".tmp")
        temporaire.write_text("\n".join(entete) + "\n\n" + envoi.texte + "\n", encoding="utf-8")
        temporaire.replace(self._fichier(envoi.cle_envoi))
        return accuse


def connecteur_par_defaut() -> Connecteur:
    return BacASable()
