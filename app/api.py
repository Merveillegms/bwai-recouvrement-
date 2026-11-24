"""API FastAPI consommée par le frontend. Les routes métier arrivent phase par phase."""
from __future__ import annotations

from fastapi import FastAPI

from app.db import connecter, version_schema

app = FastAPI(title="Recouvrement BWAI", version="0.1.0")


@app.get("/api/sante")
def sante() -> dict:
    conn = connecter()
    try:
        return {"statut": "ok", "schema": version_schema(conn)}
    finally:
        conn.close()
