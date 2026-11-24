"""Priorisation : une hiérarchie de règles documentée, pas une prédiction.

Score (0 à 100) = 100 × (poids_anciennete × A + poids_solde × S + poids_historique × H), avec :
  A = min(jours de retard / plafond, 1)
  S = min(solde / seuil gros montant de la devise, 1)
  H = factures du client réglées en retard / factures du client réglées (0 sans historique)
Ordre de la file : gros montants d'abord (ils partent en validation humaine), puis score décroissant,
retard décroissant, solde décroissant, numéro de facture croissant (départage stable).
Chaque rang s'explique en une phrase générée par gabarit, sans IA. Règles : docs/regles_metier.md § 10.
"""
from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from app import etat as moteur
from app import parametres
from app.montants import formater

CENT = Decimal(100)
_Q = Decimal("0.0001")


def _q(x: Decimal, pas: Decimal = _Q) -> Decimal:
    return x.quantize(pas, rounding=ROUND_HALF_UP)


# ------------------------------------------------------------------ fonctions pures
@dataclass(frozen=True)
class Historique:
    nb_reglees: int = 0
    nb_reglees_en_retard: int = 0
    retard_moyen_reglement: int = 0  # jours, sur les factures réglées en retard
    nb_echues_ouvertes: int = 0
    derniere_relance: str | None = None
    promesse_jusqu_au: str | None = None


@dataclass(frozen=True)
class Facteurs:
    anciennete: Decimal
    solde: Decimal
    historique: Decimal


def calculer_facteurs(jours_retard: int, solde: int, seuil: int, hist: Historique, plafond_jours: int) -> Facteurs:
    a = min(Decimal(jours_retard) / Decimal(plafond_jours), Decimal(1))
    s = min(Decimal(solde) / Decimal(seuil), Decimal(1)) if seuil > 0 else Decimal(0)
    h = Decimal(hist.nb_reglees_en_retard) / Decimal(hist.nb_reglees) if hist.nb_reglees else Decimal(0)
    return Facteurs(_q(a), _q(s), _q(h))


def calculer_score(f: Facteurs, poids: dict[str, Decimal]) -> Decimal:
    brut = poids["anciennete"] * f.anciennete + poids["solde"] * f.solde + poids["historique"] * f.historique
    return _q(brut * CENT, Decimal("0.01"))


def lire_poids(valeurs: dict) -> dict[str, Decimal]:
    poids = {k: Decimal(str(valeurs[k])) for k in ("anciennete", "solde", "historique")}
    if any(p < 0 for p in poids.values()) or sum(poids.values()) != 1:
        raise ValueError("Les poids doivent être positifs et leur somme égale à 1")
    return poids


def etape_due(jours_retard: int, sequence: list[dict], deja_faites: set[str]) -> dict | None:
    """Étape la plus avancée atteinte par le retard. Si elle est déjà faite, rien de nouveau à faire.
    On ne rattrape pas les étapes intermédiaires manquées (pas de R1 puis R2 la même semaine)."""
    atteintes = [e for e in sequence if e["active"] and e["jours"] > 0 and jours_retard >= e["jours"]]
    if not atteintes:
        return None
    etape = max(atteintes, key=lambda e: e["jours"])
    return None if etape["etape"] in deja_faites else etape


# ------------------------------------------------------------------- lecture base
def historiques(conn: sqlite3.Connection, ctx: moteur.Contexte,
                etats: list[moteur.EtatFacture]) -> dict[int, Historique]:
    """Faits chiffrés par client : factures réglées (et en retard ou non), autres factures échues,
    dernière relance envoyée, promesse de paiement confirmée en cours."""
    date_reglement = {r["facture_id"]: r["d"] for r in conn.execute(
        "SELECT facture_id, max(date_paiement) AS d FROM paiements"
        " WHERE statut_rapprochement = 'rapproche' GROUP BY facture_id")}
    relances = {r["client_id"]: r["d"] for r in conn.execute(
        "SELECT client_id, max(maj_le) AS d FROM relances WHERE statut = 'envoyee' GROUP BY client_id")}
    promesses = {r["client_id"]: r["d"] for r in conn.execute(
        "SELECT client_id, max(date_promise) AS d FROM reponses_client"
        " WHERE type = 'promesse' AND confirme = 1 AND date_promise >= ? GROUP BY client_id",
        (ctx.reference.isoformat(),))}
    par_client: dict[int, dict] = {}
    for e in etats:
        h = par_client.setdefault(e.client_id, {"reglees": 0, "en_retard": 0, "jours": [], "echues": 0})
        if e.statut == "payee" and e.id in date_reglement:
            h["reglees"] += 1
            retard = (date.fromisoformat(date_reglement[e.id]) - date.fromisoformat(e.date_echeance)).days
            if retard > 0:
                h["en_retard"] += 1
                h["jours"].append(retard)
        elif e.jours_retard > 0 and e.statut not in moteur.STATUTS_SOLDES:
            h["echues"] += 1
    return {
        client: Historique(
            nb_reglees=h["reglees"], nb_reglees_en_retard=h["en_retard"],
            retard_moyen_reglement=round(sum(h["jours"]) / len(h["jours"])) if h["jours"] else 0,
            nb_echues_ouvertes=h["echues"], derniere_relance=relances.get(client),
            promesse_jusqu_au=promesses.get(client),
        )
        for client, h in par_client.items()
    }


@dataclass
class Priorite:
    rang: int
    facture: moteur.EtatFacture
    score: Decimal
    facteurs: Facteurs
    poids: dict[str, Decimal]
    historique: Historique
    etape: dict
    gros_montant: bool
    validation_humaine: bool
    raisons_validation: list[str]
    explication: str = ""
    detail: list[str] = field(default_factory=list)

    def cle_tri(self) -> tuple:
        return (not self.gros_montant, -self.score, -self.facture.jours_retard, -self.facture.solde,
                self.facture.numero, self.facture.id)

    def en_dict(self) -> dict:
        return {
            "rang": self.rang, "facture": self.facture.en_dict(), "score": str(self.score),
            "facteurs": {k: str(v) for k, v in asdict(self.facteurs).items()},
            "poids": {k: str(v) for k, v in self.poids.items()}, "historique": asdict(self.historique),
            "etape": self.etape, "validation_humaine": self.validation_humaine,
            "raisons_validation": self.raisons_validation, "explication": self.explication, "detail": self.detail,
        }


@dataclass
class Exclusion:
    facture: moteur.EtatFacture
    code: str
    motif: str

    def en_dict(self) -> dict:
        return {"facture": self.facture.en_dict(), "code": self.code, "motif": self.motif}


_RAISONS = {
    "gros_montant": "gros montant", "client_sensible": "client sensible", "sans_contact": "aucun contact connu",
    "etape": "étape soumise à validation",
}


def _pluriel(n: int, mot: str) -> str:
    return f"{n} {mot}{'s' if n > 1 else ''}"


def _expliquer(p: Priorite) -> None:
    f, h = p.facture, p.historique
    if h.nb_reglees:
        histo = f"{_pluriel(h.nb_reglees_en_retard, 'retard')} sur {_pluriel(h.nb_reglees, 'facture')} réglée{'s' if h.nb_reglees > 1 else ''}"
    else:
        histo = "aucun historique de règlement"
    p.explication = (f"Priorité {p.rang} : {_pluriel(f.jours_retard, 'jour')} de retard, solde de "
                     f"{formater(f.solde, f.devise, f.decimales)}, {histo}"
                     + (" — gros montant, placé en tête pour validation humaine" if p.gros_montant else ""))
    c = p.facteurs
    p.detail = [
        f"Ancienneté : {f.jours_retard} j → facteur {c.anciennete} × poids {p.poids['anciennete']}"
        f" = {_q(c.anciennete * p.poids['anciennete'] * CENT, Decimal('0.01'))} pts",
        f"Solde : {formater(f.solde, f.devise, f.decimales)} → facteur {c.solde} × poids {p.poids['solde']}"
        f" = {_q(c.solde * p.poids['solde'] * CENT, Decimal('0.01'))} pts",
        f"Historique : {histo} → facteur {c.historique} × poids {p.poids['historique']}"
        f" = {_q(c.historique * p.poids['historique'] * CENT, Decimal('0.01'))} pts",
        f"Score total : {p.score} / 100",
        f"Action proposée : {p.etape['etape']} (ton {p.etape['ton']}, à partir de {p.etape['jours']} j de retard)",
    ]
    if p.validation_humaine:
        p.detail.append("Validation humaine requise : " + ", ".join(p.raisons_validation))


def _exclusion(e: moteur.EtatFacture, hist: Historique, faites: set[str], derniere: str | None, sequence, delai,
               ctx) -> Exclusion | None:
    motifs = {
        "payee": ("PAYEE", "Facture payée : jamais relancée"),
        "cloturee": ("CLOTUREE", "Facture clôturée"),
        "en_litige": ("EN_LITIGE", "Litige en cours : traitement humain uniquement"),
        "suspendue": ("SUSPENDUE", "Relances suspendues par un humain"),
    }
    if e.statut in motifs:
        return Exclusion(e, *motifs[e.statut])
    if e.jours_retard < 1:
        return Exclusion(e, "NON_ECHUE", f"Échéance le {e.date_echeance} : pas encore due")
    if "a_verifier" in e.drapeaux:
        return Exclusion(e, "A_VERIFIER", f"Donnée à vérifier ({e.motif_verification}) : aucune relance avant décision")
    if hist.promesse_jusqu_au:
        return Exclusion(e, "PROMESSE_EN_COURS", f"Promesse de paiement jusqu'au {hist.promesse_jusqu_au}")
    if derniere and ctx.reference - date.fromisoformat(derniere[:10]) < timedelta(days=delai):
        return Exclusion(e, "RELANCE_RECENTE", f"Facture relancée le {derniere[:10]} (délai minimal {delai} j)")
    if etape_due(e.jours_retard, sequence, set()) is None:
        return Exclusion(e, "AVANT_PREMIERE_ETAPE", "Retard inférieur au déclencheur de la première relance")
    if etape_due(e.jours_retard, sequence, faites) is None:
        return Exclusion(e, "ETAPE_DEJA_FAITE", "Relance de cette étape déjà envoyée : attendre l'étape suivante")
    return None


def file_du_jour(conn: sqlite3.Connection, poids: dict[str, Decimal] | None = None,
                 ctx: moteur.Contexte | None = None) -> tuple[list[Priorite], list[Exclusion]]:
    """File de travail : factures à relancer aujourd'hui, triées et expliquées ; et factures écartées, avec motif."""
    ctx = ctx or moteur.contexte(conn)
    poids = poids or lire_poids(parametres.lire(conn, "poids_priorite"))
    plafond = parametres.lire(conn, "plafond_anciennete_jours")
    sequence = parametres.lire(conn, "sequence_relances")
    delai = parametres.lire(conn, "delai_min_entre_relances_jours")
    tous = moteur.etats(conn, ctx=ctx)
    hists = historiques(conn, ctx, tous)
    faites: dict[int, set[str]] = {}
    derniere: dict[int, str] = {}
    for r in conn.execute("SELECT facture_id, etape, maj_le FROM relances WHERE statut IN ('envoyee', 'en_cours_envoi')"):
        faites.setdefault(r["facture_id"], set()).add(r["etape"])
        derniere[r["facture_id"]] = max(derniere.get(r["facture_id"], ""), r["maj_le"])

    file: list[Priorite] = []
    exclues: list[Exclusion] = []
    for e in tous:
        hist = hists.get(e.client_id, Historique())
        exclusion = _exclusion(e, hist, faites.get(e.id, set()), derniere.get(e.id), sequence, delai, ctx)
        if exclusion:
            exclues.append(exclusion)
            continue
        etape = etape_due(e.jours_retard, sequence, faites.get(e.id, set()))
        seuil = ctx.seuils[e.devise] * 10 ** e.decimales
        facteurs = calculer_facteurs(e.jours_retard, e.solde, seuil, hist, plafond)
        raisons = [_RAISONS[d] for d in ("gros_montant", "client_sensible", "sans_contact") if d in e.drapeaux]
        if etape["validation"]:
            raisons.append(f"{_RAISONS['etape']} ({etape['etape']})")
        file.append(Priorite(0, e, calculer_score(facteurs, poids), facteurs, poids, hist, etape,
                             "gros_montant" in e.drapeaux, bool(raisons), raisons))
    file.sort(key=Priorite.cle_tri)
    for rang, p in enumerate(file, start=1):
        p.rang = rang
        _expliquer(p)
    return file, exclues


def simuler(conn: sqlite3.Connection, poids: dict) -> list[dict]:
    """Effet d'un changement de poids sur le classement, sans rien enregistrer."""
    actuel = {p.facture.id: p for p in file_du_jour(conn)[0]}
    nouveau = file_du_jour(conn, lire_poids(poids))[0]
    return [{"facture_id": p.facture.id, "numero": p.facture.numero, "client": p.facture.code_client,
             "rang": p.rang, "ancien_rang": actuel[p.facture.id].rang,
             "score": str(p.score), "ancien_score": str(actuel[p.facture.id].score)} for p in nouveau]
