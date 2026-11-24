"""API FastAPI consommée par le frontend. Le frontend n'effectue aucun calcul : tout passe par ici.

Authentification : POST /api/auth/connexion renvoie un jeton, à passer ensuite dans l'en-tête
« Authorization: Bearer <jeton> ». Rôles : gestionnaire (prépare), validateur (décide), auditeur (lecture
seule, numéros de téléphone masqués).
Anti double-clic : toute requête POST/PUT peut porter un en-tête « Idempotency-Key » ; la même clé rejoue
la même réponse sans refaire l'action.
Erreurs : toujours {"code", "message", "details"} avec un message lisible, jamais de trace technique.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterator
from dataclasses import asdict
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, File, Form, Header, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from app import etat as moteur
from app import (auth, fiche, importer, parametres, priorisation, rapprochement, relances, reponses, resolution,
                 statuts, validation)
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
                    "NON_APPLICABLE": 409, "ARRET_URGENCE": 423, "HORS_PLAGE_HORAIRE": 409,
                    "TRAITEMENT_EN_COURS": 409, "IDENTIFIANTS_INVALIDES": 401, "VALIDATEUR_REQUIS": 403}


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


def _jeton(authorization: str | None) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip() or None
    return None


def utilisateur(authorization: str | None = Header(default=None), conn: sqlite3.Connection = Depends(base)) -> dict:
    jeton = _jeton(authorization)
    u = auth.utilisateur_du_jeton(conn, jeton) if jeton else None
    if u is None:
        raise ErreurApi(401, "NON_AUTHENTIFIE", "Session absente ou expirée : reconnectez-vous")
    return u


def _masquer(u: dict, ligne: dict, *champs: str) -> dict:
    """L'auditeur ne voit pas les numéros de téléphone en clair."""
    if u["role"] == "auditeur":
        for champ in champs:
            ligne[champ] = auth.masquer_telephone(ligne.get(champ))
    return ligne


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


# ------------------------------------------------------------------- anti double-clic
@app.middleware("http")
async def requetes_idempotentes(request: Request, call_next):
    """Même « Idempotency-Key » (par utilisateur) → même réponse, l'action n'est pas rejouée."""
    cle = request.headers.get("idempotency-key")
    jeton = _jeton(request.headers.get("authorization"))
    if request.method not in ("POST", "PUT") or not cle or not jeton:
        return await call_next(request)
    proprietaire = hashlib.sha256(jeton.encode()).hexdigest()[:16]
    conn = connecter()
    try:
        deja = conn.execute("SELECT * FROM requetes_idempotentes WHERE cle = ? AND utilisateur = ?",
                            (cle[:100], proprietaire)).fetchone()
        if deja is not None:
            if (deja["methode"], deja["chemin"]) != (request.method, request.url.path):
                return JSONResponse(status_code=422, content={
                    "code": "CLE_DEJA_UTILISEE", "message": "Clé d'idempotence déjà utilisée pour une autre action",
                    "details": {}})
            return Response(deja["reponse"], status_code=deja["statut_http"], media_type=deja["type_contenu"],
                            headers={"Idempotent-Replay": "true"})
        reponse = await call_next(request)
        corps = b"".join([morceau async for morceau in reponse.body_iterator])
        if reponse.status_code < 500:
            conn.execute("INSERT OR IGNORE INTO requetes_idempotentes VALUES (?,?,?,?,?,?,?,?)",
                         (cle[:100], proprietaire, request.method, request.url.path, reponse.status_code, corps,
                          reponse.headers.get("content-type"), datetime.now(timezone.utc).isoformat()))
        return Response(corps, status_code=reponse.status_code, headers=dict(reponse.headers))
    finally:
        conn.close()


# --------------------------------------------------------------------------- santé
@app.get("/api/sante")
def sante(conn: sqlite3.Connection = Depends(base)) -> dict:
    return {"statut": "ok", "schema": version_schema(conn)}


# ------------------------------------------------------------------ authentification
class Identifiants(BaseModel):
    identifiant: str
    mot_de_passe: str


@app.post("/api/auth/connexion")
def connexion(corps: Identifiants, conn: sqlite3.Connection = Depends(base)) -> dict:
    jeton, u = auth.connexion(conn, corps.identifiant, corps.mot_de_passe)
    return {"jeton": jeton, "utilisateur": u, "expire_dans_s": int(auth.DUREE_SESSION.total_seconds())}


@app.post("/api/auth/deconnexion")
def deconnexion(authorization: str | None = Header(default=None), conn: sqlite3.Connection = Depends(base)) -> dict:
    if jeton := _jeton(authorization):
        auth.deconnexion(conn, jeton)
    return {"statut": "ok"}


@app.get("/api/auth/moi")
def moi(u: dict = Depends(utilisateur)) -> dict:
    return u


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
    return [_masquer(u, dict(r), "telephone") for r in conn.execute("SELECT * FROM clients" + filtre + " ORDER BY code")]


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
    return [_masquer(u, dict(p), "telephone_payeur") for p in conn.execute(sql + " ORDER BY id", params)]


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
    return [_masquer(u, dict(m), "destinataire") for m in conn.execute("SELECT * FROM messages_sortants ORDER BY id DESC")]


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


# ---------------------------------------------------------------------- validation
class DecisionLot(BaseModel):
    lot: str
    contenu: str | None = None
    motif: str | None = None


class LotsGroupes(BaseModel):
    lots: list[str]
    motif: str | None = None


@app.get("/api/validation")
def file_validation(conn: sqlite3.Connection = Depends(base), u: dict = Depends(utilisateur)) -> dict:
    return {"lots": validation.file_de_validation(conn), "groupables": validation.lots_groupables(conn)}


@app.post("/api/validation/approuver")
def approuver_lot(corps: DecisionLot, conn: sqlite3.Connection = Depends(base), u: dict = Depends(utilisateur)) -> dict:
    return validation.approuver(conn, corps.lot, u, corps.contenu, corps.motif)


@app.post("/api/validation/rejeter")
def rejeter_lot(corps: DecisionLot, conn: sqlite3.Connection = Depends(base), u: dict = Depends(utilisateur)) -> dict:
    return validation.rejeter(conn, corps.lot, u, corps.motif)


@app.post("/api/validation/suspendre")
def suspendre_lot(corps: DecisionLot, conn: sqlite3.Connection = Depends(base), u: dict = Depends(utilisateur)) -> dict:
    return validation.suspendre(conn, corps.lot, u, corps.motif)


@app.post("/api/validation/approuver-groupe")
def approuver_groupe(corps: LotsGroupes, conn: sqlite3.Connection = Depends(base),
                     u: dict = Depends(utilisateur)) -> dict:
    return validation.approuver_groupe(conn, corps.lots, u, corps.motif)


class Lot(BaseModel):
    lot: str


@app.post("/api/relances/reessayer")
def reessayer_lot(corps: Lot, conn: sqlite3.Connection = Depends(base), u: dict = Depends(utilisateur)) -> dict:
    _ecriture_autorisee(u)
    relances.reessayer(conn, corps.lot, u["identifiant"])
    return {"statut": "ok"}


# ---------------------------------------------------------------- arrêt d'urgence
class ArretUrgence(BaseModel):
    actif: bool
    motif: str | None = None


@app.post("/api/arret-urgence")
def arret_urgence(corps: ArretUrgence, conn: sqlite3.Connection = Depends(base), u: dict = Depends(utilisateur)) -> dict:
    """Suspend (ou rétablit) toute préparation et tout envoi, en un clic, avec motif journalisé."""
    _validateur_requis(u)
    if corps.actif and not (corps.motif or "").strip():
        raise ErreurApi(422, "MOTIF_OBLIGATOIRE", "Indiquez le motif de l'arrêt d'urgence")
    parametres.ecrire(conn, "arret_urgence", corps.actif, u["identifiant"])
    return {"arret_urgence": corps.actif}


@app.get("/api/etat-systeme")
def etat_systeme(conn: sqlite3.Connection = Depends(base), u: dict = Depends(utilisateur)) -> dict:
    compte = {r["statut"]: r["n"] for r in conn.execute("SELECT statut, count(*) AS n FROM relances GROUP BY statut")}
    return {"date_du_jour": parametres.date_du_jour(conn).isoformat(),
            "arret_urgence": parametres.lire(conn, "arret_urgence"), "ia_active": parametres.lire(conn, "ia_active"),
            "relances": compte, "verrous": [dict(v) for v in conn.execute("SELECT nom, acquis_le, expire_le FROM verrous")]}
