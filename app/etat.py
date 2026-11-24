"""État calculé d'une facture : solde, retard, tranche, statut et drapeaux.

Lit la base, puis délègue tout calcul aux fonctions pures de `calculs`. Rien n'est stocké ici :
la seule valeur dérivée conservée en base est le statut (voir `statuts.actualiser`).
"""
from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import date

from app import calculs, parametres
from app.montants import depuis_unites_mineures, formater

STATUTS_SOLDES = ("payee", "cloturee")

_SQL = """
SELECT f.*, c.code AS code_client, c.nom AS nom_client, c.telephone, c.email, c.sensible,
       c.statut_validation AS validation_client, c.canal_prefere, d.decimales,
       COALESCE((SELECT SUM(p.montant) FROM paiements p
                 WHERE p.facture_id = f.id AND p.statut_rapprochement = 'rapproche'), 0) AS total_paye,
       COALESCE((SELECT SUM(a.montant) FROM avoirs a WHERE a.facture_id = f.id), 0) AS total_avoirs
FROM factures f
JOIN clients c ON c.id = f.client_id
JOIN devises d ON d.code = f.devise
"""


@dataclass
class Contexte:
    """Paramètres du calcul, lus une fois par traitement."""
    reference: date
    seuils: dict[str, int]
    jours_ouvres: bool
    fixes: list[str]
    mobiles: list[str]
    supplementaires: list[str]
    _feries: dict[int, set[date]] = field(default_factory=dict)

    def feries(self, debut: date, fin: date) -> set[date]:
        resultat: set[date] = set()
        for annee in range(debut.year, fin.year + 1):
            if annee not in self._feries:
                self._feries[annee] = calculs.jours_feries(annee, self.fixes, self.mobiles, self.supplementaires)
            resultat |= self._feries[annee]
        return resultat


def contexte(conn: sqlite3.Connection, reference: date | None = None) -> Contexte:
    return Contexte(
        reference=reference or parametres.date_du_jour(conn),
        seuils=parametres.lire(conn, "seuil_gros_montant"),
        jours_ouvres=parametres.lire(conn, "retard_jours_ouvres"),
        fixes=parametres.lire(conn, "jours_feries_fixes"),
        mobiles=parametres.lire(conn, "jours_feries_mobiles"),
        supplementaires=parametres.lire(conn, "jours_feries_supplementaires"),
    )


@dataclass(frozen=True)
class EtatFacture:
    id: int
    numero: str
    client_id: int
    code_client: str
    nom_client: str
    devise: str
    decimales: int
    date_emission: str
    date_echeance: str
    reference_paiement: str
    montant_ttc: int
    total_paye: int
    total_avoirs: int
    solde: int
    trop_percu: int
    jours_retard: int
    tranche: str | None
    statut: str
    statut_enregistre: str
    version: int
    en_litige: bool
    suspendue: bool
    a_verifier: bool
    motif_verification: str | None
    motif_cloture: str | None
    drapeaux: tuple[str, ...]

    def montant(self, mineur: int) -> str:
        return str(depuis_unites_mineures(mineur, self.decimales))

    def en_dict(self) -> dict:
        d = asdict(self)
        for champ in ("montant_ttc", "total_paye", "total_avoirs", "solde", "trop_percu"):
            d[f"{champ}_affiche"] = formater(getattr(self, champ), self.devise, self.decimales)
        d["drapeaux"] = list(self.drapeaux)
        return d


def calculer(ligne: sqlite3.Row, ctx: Contexte) -> EtatFacture:
    echeance = date.fromisoformat(ligne["date_echeance"])
    montant, paye, avoirs = ligne["montant_ttc"], ligne["total_paye"], ligne["total_avoirs"]
    statut = calculs.statut(
        montant_ttc=montant, total_paye=paye, total_avoirs=avoirs, echeance=echeance, reference=ctx.reference,
        en_litige=bool(ligne["en_litige"]), suspendue=bool(ligne["suspendue"]),
        cloturee=ligne["motif_cloture"] is not None,
    )
    solde = calculs.solde(montant, paye, avoirs)
    if statut in STATUTS_SOLDES:
        jours, tranche = 0, None
    else:
        if ctx.jours_ouvres:
            jours = calculs.jours_ouvres_de_retard(echeance, ctx.reference, ctx.feries(echeance, ctx.reference))
        else:
            jours = calculs.jours_de_retard(echeance, ctx.reference)
        tranche = calculs.tranche(jours)
    drapeaux = []
    if ligne["a_verifier"]:
        drapeaux.append("a_verifier")
    seuil = ctx.seuils.get(ligne["devise"])
    if solde > 0 and seuil is not None and solde >= seuil * 10 ** ligne["decimales"]:
        drapeaux.append("gros_montant")
    if (not ligne["telephone"] and not ligne["email"]) or ligne["validation_client"] == "en_attente":
        drapeaux.append("sans_contact")
    if ligne["sensible"]:
        drapeaux.append("client_sensible")
    return EtatFacture(
        id=ligne["id"], numero=ligne["numero"], client_id=ligne["client_id"], code_client=ligne["code_client"],
        nom_client=ligne["nom_client"], devise=ligne["devise"], decimales=ligne["decimales"],
        date_emission=ligne["date_emission"], date_echeance=ligne["date_echeance"],
        reference_paiement=ligne["reference_paiement"], montant_ttc=montant, total_paye=paye, total_avoirs=avoirs,
        solde=solde, trop_percu=calculs.trop_percu(montant, paye, avoirs), jours_retard=jours, tranche=tranche,
        statut=statut, statut_enregistre=ligne["statut"], version=ligne["version"],
        en_litige=bool(ligne["en_litige"]), suspendue=bool(ligne["suspendue"]), a_verifier=bool(ligne["a_verifier"]),
        motif_verification=ligne["motif_verification"], motif_cloture=ligne["motif_cloture"], drapeaux=tuple(drapeaux),
    )


def etat(conn: sqlite3.Connection, facture_id: int, ctx: Contexte | None = None) -> EtatFacture | None:
    ligne = conn.execute(_SQL + " WHERE f.id = ?", (facture_id,)).fetchone()
    return None if ligne is None else calculer(ligne, ctx or contexte(conn))


def etats(conn: sqlite3.Connection, condition: str = "", params: tuple = (), ctx: Contexte | None = None) -> list[EtatFacture]:
    """Toutes les factures (filtre SQL optionnel sur les alias f. et c.), ordre stable par identifiant."""
    ctx = ctx or contexte(conn)
    sql = _SQL + (f" WHERE {condition}" if condition else "") + " ORDER BY f.id"
    return [calculer(l, ctx) for l in conn.execute(sql, params)]
