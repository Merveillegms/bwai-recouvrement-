"""API FastAPI consommée par le frontend. Le frontend n'effectue aucun calcul : tout passe par ici.

Authentification : provisoire (en-tête X-Utilisateur), remplacée par de vraies sessions en phase 5.
Erreurs : toujours {"code", "message", "details"} avec un message lisible, jamais de trace technique.
"""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator

from fastapi import Depends, FastAPI, File, Form, Header, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from app import importer, resolution
from app.db import connecter, version_schema

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


_STATUTS_RESOLUTION = {"INTROUVABLE": 404, "DEJA_RESOLUE": 409, "DEJA_CLOTUREE": 409, "FACTURE_ENGAGEE": 409,
                       "CLIENT_EN_ATTENTE": 409}


@app.exception_handler(resolution.ResolutionImpossible)
def _resolution_impossible(_: Request, e: resolution.ResolutionImpossible) -> JSONResponse:
    return JSONResponse(status_code=_STATUTS_RESOLUTION.get(e.code, 422),
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
    return importer.importer(conn, type_import, contenu, fichier.filename or "fichier", u["identifiant"], corr).en_dict()


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
