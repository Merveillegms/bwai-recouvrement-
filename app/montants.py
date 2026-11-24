"""Conversion et affichage des montants. Une seule fonction d'arrondi pour tout le projet."""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal


def arrondir(valeur: Decimal, decimales: int) -> Decimal:
    """Arrondi demi-supérieur à l'unité mineure de la devise. Seule fonction d'arrondi du projet."""
    return valeur.quantize(Decimal(1).scaleb(-decimales), rounding=ROUND_HALF_UP)


def vers_unites_mineures(valeur: Decimal, decimales: int) -> int:
    return int(arrondir(valeur, decimales).scaleb(decimales))


def depuis_unites_mineures(mineur: int, decimales: int) -> Decimal:
    return Decimal(mineur).scaleb(-decimales)


def formater(mineur: int, devise: str, decimales: int) -> str:
    """1250000 XOF → « 1 250 000 FCFA » ; 125050 EUR → « 1 250,50 EUR »."""
    valeur = depuis_unites_mineures(mineur, decimales)
    entier, _, fraction = f"{valeur:.{decimales}f}".partition(".")
    signe = "-" if entier.startswith("-") else ""
    entier = entier.lstrip("-")
    groupes = []
    while entier:
        groupes.insert(0, entier[-3:])
        entier = entier[:-3]
    texte = signe + " ".join(groupes or ["0"])
    if fraction:
        texte += "," + fraction
    libelle = "FCFA" if devise in ("XOF", "XAF") else devise
    return f"{texte} {libelle}"
