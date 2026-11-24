"""Calculs métier purs : mêmes entrées, mêmes sorties, aucun accès à la base.

Règles : docs/regles_metier.md § 2 à 4. Les montants sont des entiers en unités mineures.
"""
from __future__ import annotations

from datetime import date

TRANCHES = ("non_echue", "1-15", "16-30", "31-60", "61-90", "plus_90")


def jours_de_retard(echeance: date, reference: date) -> int:
    """Jours calendaires de retard ; 0 si l'échéance n'est pas dépassée (échéance aujourd'hui = 0)."""
    return max((reference - echeance).days, 0)


def tranche(jours_retard: int) -> str:
    if jours_retard <= 0:
        return "non_echue"
    for borne, nom in ((15, "1-15"), (30, "16-30"), (60, "31-60"), (90, "61-90")):
        if jours_retard <= borne:
            return nom
    return "plus_90"


def solde(montant_ttc: int, total_paye: int, total_avoirs: int = 0) -> int:
    return max(montant_ttc - total_paye - total_avoirs, 0)


def trop_percu(montant_ttc: int, total_paye: int, total_avoirs: int = 0) -> int:
    return max(total_paye + total_avoirs - montant_ttc, 0)


def statut(
    *,
    montant_ttc: int,
    total_paye: int,
    echeance: date,
    reference: date,
    total_avoirs: int = 0,
    en_litige: bool = False,
    suspendue: bool = False,
    cloturee: bool = False,
) -> str:
    """Première règle vraie dans l'ordre documenté (§ 4)."""
    if cloturee:
        return "cloturee"
    if en_litige:
        return "en_litige"
    if suspendue:
        return "suspendue"
    if solde(montant_ttc, total_paye, total_avoirs) == 0:
        return "payee"
    if total_paye + total_avoirs > 0:
        return "partiellement_payee"
    if jours_de_retard(echeance, reference) >= 1:
        return "echue"
    return "a_echoir"
