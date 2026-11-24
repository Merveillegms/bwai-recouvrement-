"""Calculs métier purs : mêmes entrées, mêmes sorties, aucun accès à la base.

Règles : docs/regles_metier.md § 2 à 4. Les montants sont des entiers en unités mineures.
"""
from __future__ import annotations

from collections.abc import Iterable
from datetime import date, timedelta

TRANCHES = ("non_echue", "1-15", "16-30", "31-60", "61-90", "plus_90")


def jours_de_retard(echeance: date, reference: date) -> int:
    """Jours calendaires de retard ; 0 si l'échéance n'est pas dépassée (échéance aujourd'hui = 0)."""
    return max((reference - echeance).days, 0)


def paques(annee: int) -> date:
    """Dimanche de Pâques (algorithme grégorien anonyme, dit de Meeus/Jones/Butcher)."""
    a, b, c = annee % 19, annee // 100, annee % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mois = (h + l - 7 * m + 114) // 31
    jour = (h + l - 7 * m + 114) % 31 + 1
    return date(annee, mois, jour)


_MOBILES = {"lundi_paques": 1, "ascension": 39, "lundi_pentecote": 50}


def jours_feries(annee: int, fixes: Iterable[str], mobiles: Iterable[str], supplementaires: Iterable[str]) -> set[date]:
    """Fériés d'une année : fixes « MM-JJ », mobiles liés à Pâques, dates ISO supplémentaires (fêtes musulmanes…)."""
    resultat = {date(annee, int(f[:2]), int(f[3:])) for f in fixes}
    resultat |= {paques(annee) + timedelta(days=_MOBILES[m]) for m in mobiles}
    resultat |= {d for d in map(date.fromisoformat, supplementaires) if d.year == annee}
    return resultat


def jours_ouvres_de_retard(echeance: date, reference: date, feries: set[date]) -> int:
    """Jours ouvrés (lundi-vendredi hors fériés) écoulés après l'échéance, jusqu'à la référence incluse."""
    jours, courant = 0, echeance + timedelta(days=1)
    while courant <= reference:
        if courant.weekday() < 5 and courant not in feries:
            jours += 1
        courant += timedelta(days=1)
    return jours


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
    """Première règle vraie dans l'ordre documenté (§ 4). Un avoir couvrant tout le montant clôture la facture."""
    if cloturee or total_avoirs >= montant_ttc:
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
