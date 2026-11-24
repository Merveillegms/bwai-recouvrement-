"""API FastAPI consommée par le frontend. Le frontend n'effectue aucun calcul : tout passe par ici.

Authentification : provisoire (en-tête X-Utilisateur), remplacée par de vraies sessions en phase 5.
Erreurs : toujours {"code", "message", "details"} avec un message lisible, jamais de trace technique.
"""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from dataclasses import asdict

from fastapi import Depends, FastAPI, File, Form, Header, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from app import etat as moteur
from app import fiche, importer, parametres, priorisation, rapprochement, relances, reponses, resolution, statuts
from app.db import connecter, version_schema
from app.erreurs import ErreurMetier
from app.montants import depuis_unites_mineures
from app.normalisation import ErreurValeur, lire_decimal, lire_montant

app = FastAPI(title="Recouvrement BWAI", version="0.2.0")

TAILLE_MAX_IMPORT = 20 * 1024 * 1024  # 20 Mo


class ErreurApi(Exception):
    def __init__(self, statut: int, code: str, message: str, details: dict | None = None) -> None:
        self.statut, self.code, self.message, self.details = statut, code, message, details or {}


@app.exception_handler(ErreurApi)
def _erreur_api(_: Request, e: ErreurApi) -> JSONResponse:
    return JSONResponse(status_code=e.statut, content={"code": e.code, "message": e.message, "details": e.details})


@app.exception_handler(importer.ImportRefuse)
def _import_refuse(_: Request, e: importer.ImportRefuse) -> JSONResponse:
    statut = 409 if e.code == "FICHIER_DEJA_IMPORTE" else 422
    return JSONResponse(status_code=statut, content={"code": e.code, "message": e.message, "details": e.details})


_STATUTS_ERREURS = {"INTROUVABLE": 404, "DEJA_RESOLUE": 409, "DEJA_CLOTUREE": 409, "FACTURE_ENGAGEE": 409,
                    "CLIENT_EN_ATTENTE": 409, "TRANSITION_INTERDITE": 409, "DECISION_HUMAINE_REQUISE": 409,
                    "NON_APPLICABLE": 409, "ARRET_URGENCE": 423, "HORS_PLAGE_HORAIRE": 409}


@app.exception_handler(ErreurMetier)
def _erreur_metier(_: Request, e: ErreurMetier) -> JSONResponse:
    return JSONResponse(status_code=_STATUTS_ERREURS.get(e.code, 422),
                        content={"code": e.code, "message": e.message, "details": {}})


def base() -> Iterator[sqlite3.Connection]:
    conn = connecter()
    try:
        yield conn
    finally:
        conn.close()


def utilisateur(x_utilisateur: str = Header(default="gestionnaire"), conn: sqlite3.Connection = Depends(base)) -> dict:
    ligne = conn.execute("SELECT identifiant, nom, role FROM utilisateurs WHERE identifiant = ? AND actif = 1",
                         (x_utilisateur,)).fetchone()
    if ligne is None:
        raise ErreurApi(401, "NON_AUTHENTIFIE", "Utilisateur inconnu ou inactif")
    return dict(ligne)


def _ecriture_autorisee(u: dict) -> None:
    if u["role"] == "auditeur":
        raise ErreurApi(403, "LECTURE_SEULE", "Le rôle auditeur est en lecture seule")


def _validateur_requis(u: dict) -> None:
    if u["role"] != "validateur":
        raise ErreurApi(403, "VALIDATEUR_REQUIS", "Cette décision est réservée au validateur")


async def _lire_fichier(fichier: UploadFile) -> bytes:
    contenu = await fichier.read(TAILLE_MAX_IMPORT + 1)
    if len(contenu) > TAILLE_MAX_IMPORT:
        raise ErreurApi(413, "FICHIER_TROP_GROS", "Fichier trop volumineux (20 Mo au maximum)")
    return contenu


# --------------------------------------------------------------------------- santé
@app.get("/api/sante")
def sante(conn: sqlite3.Connection = Depends(base)) -> dict:
    return {"statut": "ok", "schema": version_schema(conn)}


# -------------------------------------------------------------------------- imports
@app.post("/api/imports/{type_import}/apercu")
async def apercu_import(type_import: str, fichier: UploadFile = File(...), u: dict = Depends(utilisateur)) -> dict:
    return importer.apercu(type_import, await _lire_fichier(fichier), fichier.filename or "fichier")


@app.post("/api/imports/{type_import}", status_code=201)
async def importer_fichier(
    type_import: str,
    fichier: UploadFile = File(...),
    correspondance: str | None = Form(default=None, description="JSON {champ: en-tête du fichier}"),
    u: dict = Depends(utilisateur),
    conn: sqlite3.Connection = Depends(base),
) -> dict:
    _ecriture_autorisee(u)
    try:
        corr = json.loads(correspondance) if correspondance else None
    except json.JSONDecodeError:
        raise ErreurApi(422, "CORRESPONDANCE_INVALIDE", "La correspondance de colonnes n'est pas un JSON valide") from None
    contenu = await _lire_fichier(fichier)
    resultat = importer.importer(conn, type_import, contenu, fichier.filename or "fichier", u["identifiant"],
                                 corr).en_dict()
    if type_import == "paiements":  # rapprochement immédiat des paiements importés
        resultat["rapprochement"] = rapprochement.rapprocher_tout(conn)
    return resultat


@app.get("/api/imports")
def lister_imports(conn: sqlite3.Connection = Depends(base), u: dict = Depends(utilisateur)) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM imports ORDER BY id DESC")]


@app.get("/api/imports/{import_id}")
def detail_import(import_id: int, conn: sqlite3.Connection = Depends(base), u: dict = Depends(utilisateur)) -> dict:
    resultat = importer.rapport(conn, import_id)
    if resultat is None:
        raise ErreurApi(404, "INTROUVABLE", "Import introuvable")
    return resultat


@app.get("/api/imports/{import_id}/rejets.csv")
def rejets_csv(import_id: int, conn: sqlite3.Connection = Depends(base), u: dict = Depends(utilisateur)) -> Response:
    if importer.rapport(conn, import_id) is None:
        raise ErreurApi(404, "INTROUVABLE", "Import introuvable")
    return Response(importer.exporter_rejets_csv(conn, import_id), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="rejets_import_{import_id}.csv"'})


# ----------------------------------------------------------------------- résolution
class Decision(BaseModel):
    decision: str
    motif: str | None = None


class Motif(BaseModel):
    motif: str | None = None


class FicheClient(BaseModel):
    nom: str
    telephone: str | None = None
    email: str | None = None
    canal_prefere: str = "sms"
    sensible: bool = False


@app.get("/api/anomalies")
def lister_anomalies(non_resolues: bool = True, conn: sqlite3.Connection = Depends(base),
                     u: dict = Depends(utilisateur)) -> list[dict]:
    filtre = " WHERE a.resolution IS NULL AND a.gravite = 'rejet'" if non_resolues else ""
    lignes = conn.execute(
        "SELECT a.*, i.fichier, i.type FROM import_anomalies a JOIN imports i ON i.id = a.import_id"
        + filtre + " ORDER BY a.import_id, a.ligne")
    return [dict(r) | {"donnees": json.loads(r["donnees"])} for r in lignes]


@app.post("/api/anomalies/{anomalie_id}/resolution")
def resoudre(anomalie_id: int, corps: Decision, conn: sqlite3.Connection = Depends(base),
             u: dict = Depends(utilisateur)) -> dict:
    _ecriture_autorisee(u)
    return resolution.resoudre_anomalie(conn, anomalie_id, corps.decision, u["identifiant"], corps.motif)


@app.get("/api/factures/a-verifier")
def factures_a_verifier(conn: sqlite3.Connection = Depends(base), u: dict = Depends(utilisateur)) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT f.*, c.code AS code_client, c.nom AS nom_client FROM factures f JOIN clients c ON c.id = f.client_id"
        " WHERE f.a_verifier = 1 ORDER BY f.id")]


@app.post("/api/factures/{facture_id}/confirmer")
def confirmer(facture_id: int, corps: Motif, conn: sqlite3.Connection = Depends(base),
              u: dict = Depends(utilisateur)) -> dict:
    _ecriture_autorisee(u)
    resolution.confirmer_facture(conn, facture_id, u["identifiant"], corps.motif)
    return {"statut": "ok"}


@app.post("/api/factures/{facture_id}/annuler")
def annuler(facture_id: int, corps: Motif, conn: sqlite3.Connection = Depends(base),
            u: dict = Depends(utilisateur)) -> dict:
    _ecriture_autorisee(u)
    resolution.annuler_facture(conn, facture_id, u["identifiant"], corps.motif or "")
    return {"statut": "ok"}


@app.get("/api/clients")
def lister_clients(en_attente: bool = False, conn: sqlite3.Connection = Depends(base),
                   u: dict = Depends(utilisateur)) -> list[dict]:
    filtre = " WHERE statut_validation = 'en_attente'" if en_attente else ""
    return [dict(r) for r in conn.execute("SELECT * FROM clients" + filtre + " ORDER BY code")]


@app.post("/api/clients/{client_id}/valider")
def valider(client_id: int, corps: FicheClient, conn: sqlite3.Connection = Depends(base),
            u: dict = Depends(utilisateur)) -> dict:
    _ecriture_autorisee(u)
    liberees = resolution.valider_client(conn, client_id, u["identifiant"], **corps.model_dump())
    return {"statut": "ok", "factures_liberees": liberees}


# ------------------------------------------------------------- factures et statuts
@app.get("/api/factures")
def lister_factures(statut: str | None = None, tranche: str | None = None, client: str | None = None,
                    drapeau: str | None = None, conn: sqlite3.Connection = Depends(base),
                    u: dict = Depends(utilisateur)) -> list[dict]:
    """État calculé de chaque facture (le frontend n'a rien à calculer)."""
    condition, params = ("c.code = ?", (client.upper(),)) if client else ("", ())
    resultat = []
    for e in moteur.etats(conn, condition, params):
        if (statut and e.statut != statut) or (tranche and e.tranche != tranche) or (drapeau and drapeau not in e.drapeaux):
            continue
        resultat.append(e.en_dict())
    return resultat


@app.get("/api/factures/{facture_id}")
def detail_facture(facture_id: int, conn: sqlite3.Connection = Depends(base), u: dict = Depends(utilisateur)) -> dict:
    e = moteur.etat(conn, facture_id)
    if e is None:
        raise ErreurApi(404, "INTROUVABLE", "Facture introuvable")
    paiements = [dict(p) for p in conn.execute(
        "SELECT * FROM paiements WHERE facture_id = ? OR facture_proposee_id = ? ORDER BY date_paiement, id",
        (facture_id, facture_id))]
    avoirs = [dict(a) for a in conn.execute("SELECT * FROM avoirs WHERE facture_id = ? ORDER BY id", (facture_id,))]
    historique = [dict(j) for j in conn.execute(
        "SELECT id, horodatage, acteur, type_acteur, action, avant, apres, regle FROM journal"
        " WHERE objet_type = 'facture' AND objet_id = ? ORDER BY id", (str(facture_id),))]
    return e.en_dict() | {"paiements": paiements, "avoirs": avoirs, "historique": historique}


class Avoir(BaseModel):
    montant: str
    motif: str | None = None


@app.post("/api/factures/{facture_id}/litige")
def declarer_litige(facture_id: int, corps: Motif, conn: sqlite3.Connection = Depends(base),
                    u: dict = Depends(utilisateur)) -> dict:
    _ecriture_autorisee(u)
    return statuts.declarer_litige(conn, facture_id, u["identifiant"], corps.motif).en_dict()


@app.post("/api/factures/{facture_id}/lever-litige")
def lever_litige(facture_id: int, corps: Motif, conn: sqlite3.Connection = Depends(base),
                 u: dict = Depends(utilisateur)) -> dict:
    _validateur_requis(u)
    return statuts.lever_litige(conn, facture_id, u["identifiant"], corps.motif).en_dict()


@app.post("/api/factures/{facture_id}/suspendre")
def suspendre(facture_id: int, corps: Motif, conn: sqlite3.Connection = Depends(base),
              u: dict = Depends(utilisateur)) -> dict:
    _ecriture_autorisee(u)
    return statuts.suspendre(conn, facture_id, u["identifiant"], corps.motif).en_dict()


@app.post("/api/factures/{facture_id}/reprendre")
def reprendre(facture_id: int, corps: Motif, conn: sqlite3.Connection = Depends(base),
              u: dict = Depends(utilisateur)) -> dict:
    _ecriture_autorisee(u)
    return statuts.reprendre(conn, facture_id, u["identifiant"], corps.motif).en_dict()


@app.post("/api/factures/{facture_id}/avoirs")
def creer_avoir(facture_id: int, corps: Avoir, conn: sqlite3.Connection = Depends(base),
                u: dict = Depends(utilisateur)) -> dict:
    _validateur_requis(u)
    e = moteur.etat(conn, facture_id)
    if e is None:
        raise ErreurApi(404, "INTROUVABLE", "Facture introuvable")
    try:
        montant = lire_montant(corps.montant, e.decimales)
    except ErreurValeur as err:
        raise ErreurApi(422, err.code, err.message) from None
    return statuts.creer_avoir(conn, facture_id, montant, u["identifiant"], corps.motif).en_dict()


@app.post("/api/factures/{facture_id}/perte")
def passer_en_perte(facture_id: int, corps: Motif, conn: sqlite3.Connection = Depends(base),
                    u: dict = Depends(utilisateur)) -> dict:
    _validateur_requis(u)
    return statuts.passer_en_perte(conn, facture_id, u["identifiant"], corps.motif).en_dict()


@app.post("/api/recalcul")
def recalculer(conn: sqlite3.Connection = Depends(base), u: dict = Depends(utilisateur)) -> dict:
    return {"changements": statuts.recalculer_tout(conn)}


# --------------------------------------------------------------------- paiements
class AffectationPaiement(BaseModel):
    facture_id: int | None = None
    motif: str | None = None


@app.get("/api/paiements")
def lister_paiements(statut: str | None = None, conn: sqlite3.Connection = Depends(base),
                     u: dict = Depends(utilisateur)) -> list[dict]:
    sql, params = "SELECT * FROM paiements", ()
    if statut:
        sql, params = sql + " WHERE statut_rapprochement = ?", (statut,)
    return [dict(p) for p in conn.execute(sql + " ORDER BY id", params)]


@app.post("/api/rapprochement")
def lancer_rapprochement(conn: sqlite3.Connection = Depends(base), u: dict = Depends(utilisateur)) -> dict:
    _ecriture_autorisee(u)
    return {"resume": rapprochement.rapprocher_tout(conn)}


@app.post("/api/paiements/{paiement_id}/valider")
def valider_paiement(paiement_id: int, corps: AffectationPaiement, conn: sqlite3.Connection = Depends(base),
                     u: dict = Depends(utilisateur)) -> dict:
    _ecriture_autorisee(u)
    return rapprochement.valider_paiement(conn, paiement_id, u["identifiant"], corps.facture_id, corps.motif).en_dict()


@app.post("/api/paiements/{paiement_id}/rejeter")
def rejeter_paiement(paiement_id: int, corps: Motif, conn: sqlite3.Connection = Depends(base),
                     u: dict = Depends(utilisateur)) -> dict:
    _ecriture_autorisee(u)
    rapprochement.rejeter_paiement(conn, paiement_id, u["identifiant"], corps.motif)
    return {"statut": "ok"}


@app.post("/api/paiements/{paiement_id}/annuler-rapprochement")
def annuler_rapprochement(paiement_id: int, corps: Motif, conn: sqlite3.Connection = Depends(base),
                          u: dict = Depends(utilisateur)) -> dict:
    _validateur_requis(u)
    rapprochement.annuler_rapprochement(conn, paiement_id, u["identifiant"], corps.motif)
    return {"statut": "ok"}


# -------------------------------------------------------------------- priorisation
@app.get("/api/aujourdhui")
def file_aujourdhui(tranche: str | None = None, client: str | None = None, montant_min: str | None = None,
                    montant_max: str | None = None, etape: str | None = None, validation: bool | None = None,
                    conn: sqlite3.Connection = Depends(base), u: dict = Depends(utilisateur)) -> dict:
    """File de travail du jour, triée et expliquée, et factures écartées avec leur motif."""
    try:
        bornes = [lire_decimal(m) if m else None for m in (montant_min, montant_max)]
    except ErreurValeur as err:
        raise ErreurApi(422, err.code, err.message) from None
    ctx = moteur.contexte(conn)
    file, exclues = priorisation.file_du_jour(conn, ctx=ctx)

    def garde(p: priorisation.Priorite) -> bool:
        solde = depuis_unites_mineures(p.facture.solde, p.facture.decimales)
        return ((not tranche or p.facture.tranche == tranche) and (not client or p.facture.code_client == client.upper())
                and (not etape or p.etape["etape"] == etape)
                and (validation is None or p.validation_humaine == validation)
                and (bornes[0] is None or solde >= bornes[0]) and (bornes[1] is None or solde <= bornes[1]))

    retenues = [p for p in file if garde(p)]
    return {
        "date_reference": ctx.reference.isoformat(),
        "resume": {"a_relancer": len(file), "validation_humaine": sum(p.validation_humaine for p in file),
                   "exclues": len(exclues), "affichees": len(retenues)},
        "file": [p.en_dict() for p in retenues],
        "exclues": [x.en_dict() for x in exclues if not client or x.facture.code_client == client.upper()],
    }


@app.get("/api/factures/{facture_id}/priorite")
def pourquoi_cette_facture(facture_id: int, conn: sqlite3.Connection = Depends(base),
                           u: dict = Depends(utilisateur)) -> dict:
    """« Pourquoi cette facture est-elle ici ? » : son rang et le détail du calcul, ou le motif de son exclusion."""
    file, exclues = priorisation.file_du_jour(conn)
    for p in file:
        if p.facture.id == facture_id:
            return {"dans_la_file": True} | p.en_dict()
    for x in exclues:
        if x.facture.id == facture_id:
            return {"dans_la_file": False} | x.en_dict()
    raise ErreurApi(404, "INTROUVABLE", "Facture introuvable")


@app.get("/api/clients/{client_id}/historique")
def historique_client(client_id: int, conn: sqlite3.Connection = Depends(base), u: dict = Depends(utilisateur)) -> dict:
    ctx = moteur.contexte(conn)
    factures = moteur.etats(conn, "f.client_id = ?", (client_id,), ctx)
    if not factures:
        raise ErreurApi(404, "INTROUVABLE", "Client introuvable ou sans facture")
    hist = priorisation.historiques(conn, ctx, factures).get(client_id, priorisation.Historique())
    return {"historique": asdict(hist), "factures": [e.en_dict() for e in factures]}


class Poids(BaseModel):
    anciennete: str
    solde: str
    historique: str


@app.post("/api/priorisation/simulation")
def simuler_poids(corps: Poids, conn: sqlite3.Connection = Depends(base), u: dict = Depends(utilisateur)) -> list[dict]:
    try:
        return priorisation.simuler(conn, corps.model_dump())
    except (ValueError, ArithmeticError):
        raise ErreurApi(422, "POIDS_INVALIDES", "Les poids doivent être des nombres positifs de somme 1") from None


@app.put("/api/parametres/poids_priorite")
def modifier_poids(corps: Poids, conn: sqlite3.Connection = Depends(base), u: dict = Depends(utilisateur)) -> dict:
    _validateur_requis(u)
    try:
        priorisation.lire_poids(corps.model_dump())
    except (ValueError, ArithmeticError):
        raise ErreurApi(422, "POIDS_INVALIDES", "Les poids doivent être des nombres positifs de somme 1") from None
    parametres.ecrire(conn, "poids_priorite", {k: float(v) for k, v in corps.model_dump().items()}, u["identifiant"])
    return {"statut": "ok"}


# ------------------------------------------------------------------------ relances
@app.post("/api/relances/preparer")
def preparer_relances(conn: sqlite3.Connection = Depends(base), u: dict = Depends(utilisateur)) -> dict:
    _ecriture_autorisee(u)
    return relances.preparer(conn)


@app.get("/api/relances/lots")
def lots_de_relances(statut: str | None = None, conn: sqlite3.Connection = Depends(base),
                     u: dict = Depends(utilisateur)) -> list[dict]:
    """Un lot = un message (ou un dossier d'escalade) pour un client : aperçu avant validation."""
    lots: dict[str, dict] = {}
    for r in conn.execute("SELECT r.*, c.code AS code_client, c.nom AS nom_client, f.numero FROM relances r"
                          " JOIN clients c ON c.id = r.client_id JOIN factures f ON f.id = r.facture_id"
                          " ORDER BY r.id"):
        lot = lots.setdefault(r["lot_envoi"], {
            "lot": r["lot_envoi"], "client": {"id": r["client_id"], "code": r["code_client"], "nom": r["nom_client"]},
            "canal": r["canal"], "statut": r["statut"], "message": r["message"],
            "motif_validation": r["motif_validation"], "date_preparation": r["date_preparation"], "relances": []})
        lot["relances"].append({"id": r["id"], "facture_id": r["facture_id"], "numero": r["numero"],
                                "etape": r["etape"], "statut": r["statut"]})
    return [l for l in lots.values() if not statut or l["statut"] == statut]


@app.post("/api/relances/envoyer")
def envoyer_relances(conn: sqlite3.Connection = Depends(base), u: dict = Depends(utilisateur)) -> dict:
    _ecriture_autorisee(u)
    return relances.envoyer(conn, u["identifiant"])


@app.get("/api/messages")
def messages_sortants(conn: sqlite3.Connection = Depends(base), u: dict = Depends(utilisateur)) -> list[dict]:
    return [dict(m) for m in conn.execute("SELECT * FROM messages_sortants ORDER BY id DESC")]


@app.get("/api/factures/{facture_id}/fiche-paiement.pdf")
def fiche_paiement(facture_id: int, conn: sqlite3.Connection = Depends(base), u: dict = Depends(utilisateur)) -> Response:
    contenu = fiche.generer_fiche(conn, facture_id)
    return Response(contenu, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="fiche_paiement_{facture_id}.pdf"'})


class ReponseClient(BaseModel):
    type: str
    facture_id: int | None = None
    date_promise: str | None = None
    texte: str | None = None


@app.post("/api/clients/{client_id}/reponses", status_code=201)
def enregistrer_reponse(client_id: int, corps: ReponseClient, conn: sqlite3.Connection = Depends(base),
                        u: dict = Depends(utilisateur)) -> dict:
    _ecriture_autorisee(u)
    rid = reponses.enregistrer(conn, client_id, corps.type, u["identifiant"], facture_id=corps.facture_id,
                               date_promise=corps.date_promise, texte=corps.texte)
    return {"id": rid}
