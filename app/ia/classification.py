"""Classification des réponses clients : bayésien naïf multinomial, entraîné localement.

Pourquoi ce modèle : petit, hors ligne, déterministe, explicable (on peut dire quels mots ont pesé),
entraînable en une fraction de seconde sur des exemples étiquetés à la main (data/ia/entrainement.csv).
Il ne fait que PROPOSER une catégorie et une date : un humain confirme toujours, et aucune catégorie
(en particulier « litige ») ne change seule le statut d'une facture.

Le texte du client n'est jamais traité comme une instruction : ce n'est qu'un sac de mots.
"""
from __future__ import annotations

import csv
import math
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

from app import config

CATEGORIES = ("promesse", "paiement_annonce", "litige", "demande_delai", "demande_info", "sans_rapport")
FICHIER_ENTRAINEMENT = config.RACINE / "data" / "ia" / "entrainement.csv"
FICHIER_EVALUATION = config.RACINE / "data" / "ia" / "evaluation.csv"
VERSION_MODELE = "nb-multinomial-1"

_JOURS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
_MOIS = ("janvier", "fevrier", "mars", "avril", "mai", "juin", "juillet", "aout", "septembre", "octobre",
         "novembre", "decembre")
_OPERATEURS = {"momo", "mtn", "moov", "celtiis", "wave", "flooz"}


def normaliser(texte: str) -> str:
    texte = unicodedata.normalize("NFKD", texte.lower())
    texte = "".join(c for c in texte if not unicodedata.combining(c))
    return re.sub(r"[’'`]", " ", texte)


def jetons(texte: str) -> list[str]:
    """Mots normalisés + classes (<jour>, <mois>, <nombre>, <operateur>) + bigrammes."""
    mots = []
    for m in re.findall(r"[a-z0-9]+", normaliser(texte)):
        if m.isdigit():
            m = "<nombre>"
        elif m in _JOURS:
            m = "<jour>"
        elif m in _MOIS:
            m = "<mois>"
        elif m in _OPERATEURS:
            m = "<operateur>"
        elif len(m) > 4 and m.endswith(("s", "x")):
            m = m[:-1]
        mots.append(m)
    return mots + [f"{a}_{b}" for a, b in zip(mots, mots[1:])]


@dataclass
class Prediction:
    categorie: str
    confiance: float
    probabilites: dict[str, float]
    mots_decisifs: list[str] = field(default_factory=list)


class ModeleBayesien:
    def __init__(self, lissage: float = 0.5) -> None:
        self.lissage = lissage
        self.a_priori: dict[str, float] = {}
        self.comptes: dict[str, Counter] = defaultdict(Counter)
        self.totaux: dict[str, int] = {}
        self.vocabulaire: set[str] = set()

    def entrainer(self, exemples: list[tuple[str, str]]) -> "ModeleBayesien":
        par_classe = Counter(c for _, c in exemples)
        for texte, categorie in exemples:
            for j in jetons(texte):
                self.comptes[categorie][j] += 1
                self.vocabulaire.add(j)
        n = len(exemples)
        self.a_priori = {c: math.log(par_classe[c] / n) for c in CATEGORIES if par_classe[c]}
        self.totaux = {c: sum(self.comptes[c].values()) for c in self.a_priori}
        return self

    def _log_vraisemblance(self, j: str, c: str) -> float:
        return math.log((self.comptes[c][j] + self.lissage) / (self.totaux[c] + self.lissage * len(self.vocabulaire)))

    def predire(self, texte: str) -> Prediction:
        connus = [j for j in jetons(texte) if j in self.vocabulaire]
        scores = {c: self.a_priori[c] + sum(self._log_vraisemblance(j, c) for j in connus) for c in self.a_priori}
        maximum = max(scores.values())
        exp = {c: math.exp(s - maximum) for c, s in scores.items()}
        somme = sum(exp.values())
        probas = {c: round(v / somme, 4) for c, v in sorted(exp.items())}
        meilleure = max(probas, key=lambda c: (probas[c], c))
        # Mots qui ont le plus poussé vers la catégorie retenue (explicabilité).
        autres = [c for c in self.a_priori if c != meilleure]
        poids = {j: self._log_vraisemblance(j, meilleure) - max(self._log_vraisemblance(j, c) for c in autres)
                 for j in set(connus)}
        decisifs = [j for j, p in sorted(poids.items(), key=lambda x: -x[1]) if p > 0.5 and "_" not in j][:4]
        return Prediction(meilleure, probas[meilleure], probas, decisifs)


def lire_exemples(chemin: Path) -> list[tuple[str, str]]:
    with chemin.open(encoding="utf-8", newline="") as f:
        return [(l["texte"], l["categorie"]) for l in csv.DictReader(f, delimiter=";")]


@lru_cache(maxsize=1)
def modele() -> ModeleBayesien:
    return ModeleBayesien().entrainer(lire_exemples(FICHIER_ENTRAINEMENT))


def classer(texte: str) -> Prediction:
    return modele().predire(texte)


# --------------------------------------------------------------- extraction de date
_MOIS_NUM = {m: i + 1 for i, m in enumerate(_MOIS)}


def _fin_de_mois(d: date) -> date:
    suivant = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    return suivant - timedelta(days=1)


def _jour_du_mois(reference: date, jour: int, mois: int | None = None) -> date | None:
    annee, m = reference.year, mois or reference.month
    for _ in range(13):
        try:
            candidat = date(annee, m, jour)
        except ValueError:
            candidat = None
        if candidat and candidat >= reference:
            return candidat
        if mois:  # mois explicite déjà passé : l'année suivante
            annee += 1
        else:
            m, annee = (1, annee + 1) if m == 12 else (m + 1, annee)
    return None


def extraire_date(texte: str, reference: date) -> date | None:
    """Date de paiement évoquée (« vendredi », « demain », « le 20 », « fin du mois », « 05/01 »…).
    Une simple proposition : l'humain la confirme ou la corrige."""
    t = normaliser(texte)
    if m := re.search(r"\b(\d{1,2})[/.-](\d{1,2})(?:[/.-](\d{2,4}))?\b", t):
        j, mo, a = int(m.group(1)), int(m.group(2)), m.group(3)
        try:
            if a:
                return date(int(a) + (2000 if len(a) == 2 else 0), mo, j)
            return _jour_du_mois(reference, j, mo)
        except ValueError:
            return None
    if re.search(r"apres[ -]?demain", t):
        return reference + timedelta(days=2)
    if "demain" in t:
        return reference + timedelta(days=1)
    if "aujourd hui" in t or "ce soir" in t:
        return reference
    if m := re.search(r"dans (\d{1,2}) jours?", t):
        return reference + timedelta(days=int(m.group(1)))
    if re.search(r"fin (du|de) (mois|ce mois)", t) and "prochain" not in t:
        fin = _fin_de_mois(reference)
        return fin if fin > reference else _fin_de_mois(reference + timedelta(days=1))
    if re.search(r"fin du mois prochain", t):
        return _fin_de_mois(_fin_de_mois(reference) + timedelta(days=1))
    if m := re.search(r"\b(\d{1,2}) (" + "|".join(_MOIS) + r")\b", t):
        return _jour_du_mois(reference, int(m.group(1)), _MOIS_NUM[m.group(2)])
    for i, jour in enumerate(_JOURS):
        if re.search(rf"\b{jour}\b", t):
            ecart = (i - reference.weekday()) % 7 or 7
            if "prochain" in t and ecart < 7 and f"{jour} prochain" in t:
                ecart += 7 if ecart <= 2 else 0
            return reference + timedelta(days=ecart)
    if "semaine prochaine" in t:
        return reference + timedelta(days=7)
    if "fin de la semaine" in t or "fin de semaine" in t:
        return reference + timedelta(days=(4 - reference.weekday()) % 7 or 7)
    if m := re.search(r"\b(?:le|au) (\d{1,2})\b", t):
        return _jour_du_mois(reference, int(m.group(1)))
    return None
