"""Lecture tolérante des valeurs saisies par un humain : textes, dates, montants, booléens.

Chaque fonction renvoie une valeur propre ou lève `ErreurValeur` avec un code métier
(voir docs/regles_metier.md § 6). Aucune n'invente de valeur : dans le doute, elle refuse.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import date
from decimal import Decimal


class ErreurValeur(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


_ESPACES = re.compile(r"[\s  ]+")
_DATE_ISO = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})(?:[ T]\d{1,2}:\d{2}(?::\d{2}(?:\.\d+)?)?)?$")
_DATE_FR = re.compile(r"^(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})$")
_NOMBRE = re.compile(r"^[+-]?\d+(\.\d+)?$")
_VRAI = {"oui", "o", "1", "vrai", "true", "yes", "y", "x"}
_FAUX = {"non", "n", "0", "faux", "false", "no", ""}


def nettoyer(valeur: object) -> str:
    """Supprime les espaces parasites (y compris insécables) et réduit les espaces multiples."""
    if valeur is None:
        return ""
    return _ESPACES.sub(" ", str(valeur)).strip()


def cle_entete(texte: str) -> str:
    """« N° Échéance » → « necheance » : comparaison d'en-têtes insensible aux accents et à la casse."""
    texte = unicodedata.normalize("NFKD", texte)
    texte = "".join(c for c in texte if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", texte.lower())


def lire_date(valeur: object) -> date:
    texte = nettoyer(valeur)
    if m := _DATE_ISO.match(texte):
        annee, mois, jour = m.groups()
    elif m := _DATE_FR.match(texte):
        jour, mois, annee = m.groups()
    else:
        raise ErreurValeur("DATE_INVALIDE", f"Date illisible « {texte} » (formats acceptés : AAAA-MM-JJ ou JJ/MM/AAAA)")
    try:
        resultat = date(int(annee), int(mois), int(jour))
    except ValueError:
        raise ErreurValeur("DATE_INVALIDE", f"Date inexistante « {texte} »") from None
    if not 2000 <= resultat.year <= 2100:
        raise ErreurValeur("DATE_INVALIDE", f"Date hors période plausible « {texte} »")
    return resultat


def lire_decimal(valeur: object) -> Decimal:
    """Accepte « 1 250 000 », « 1250,50 », « 1.250,50 », « 1,250.50 ». Refuse tout le reste."""
    texte = nettoyer(valeur)
    s = _ESPACES.sub("", texte).replace("'", "")
    virgules, points = s.count(","), s.count(".")
    if virgules and points:
        decimal_sep = "," if s.rfind(",") > s.rfind(".") else "."
        milliers = "." if decimal_sep == "," else ","
        s = s.replace(milliers, "").replace(decimal_sep, ".")
    elif virgules:
        s = s.replace(",", "") if virgules > 1 else s.replace(",", ".")
    elif points > 1:
        s = s.replace(".", "")
    if not _NOMBRE.match(s):
        raise ErreurValeur("MONTANT_INVALIDE", f"Montant non numérique « {texte} »")
    return Decimal(s)


def lire_montant(valeur: object, decimales: int) -> int:
    """Montant strictement positif, converti en unités mineures de la devise."""
    texte = nettoyer(valeur)
    montant = lire_decimal(texte)
    if montant < 0:
        raise ErreurValeur("MONTANT_NEGATIF", f"Montant négatif « {texte} »")
    if montant == 0:
        raise ErreurValeur("MONTANT_NUL", f"Montant nul « {texte} »")
    mineur = montant.scaleb(decimales)
    if mineur != mineur.to_integral_value():
        raise ErreurValeur(
            "DECIMALES_INVALIDES", f"« {texte} » : cette devise accepte {decimales} décimale(s) au plus"
        )
    return int(mineur)


def lire_booleen(valeur: object) -> bool:
    texte = nettoyer(valeur).lower()
    if texte in _VRAI:
        return True
    if texte in _FAUX:
        return False
    raise ErreurValeur("VALEUR_INVALIDE", f"Valeur « {texte} » : attendu oui ou non")
