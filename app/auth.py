"""Sessions : connexion par identifiant et mot de passe, jeton porteur (Bearer) à durée limitée.

Le jeton n'est jamais stocké : seule son empreinte SHA-256 l'est. Connexions réussies et refusées
sont journalisées (sans le mot de passe).
"""
from __future__ import annotations

import hashlib
import re
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone

from app import journal
from app.db import transaction
from app.erreurs import ErreurMetier
from app.securite import verifier_mot_de_passe

DUREE_SESSION = timedelta(hours=8)


def _empreinte(jeton: str) -> str:
    return hashlib.sha256(jeton.encode()).hexdigest()


def connexion(conn: sqlite3.Connection, identifiant: str, mot_de_passe: str) -> tuple[str, dict]:
    u = conn.execute("SELECT * FROM utilisateurs WHERE identifiant = ? AND actif = 1", (identifiant,)).fetchone()
    if u is None or not verifier_mot_de_passe(mot_de_passe, u["mot_de_passe_hash"]):
        with transaction(conn):
            journal.ajouter(conn, acteur=identifiant[:50] or "?", type_acteur="humain", action="connexion_refusee",
                            objet_type="session", regle="AUTHENTIFICATION")
        raise ErreurMetier("IDENTIFIANTS_INVALIDES", "Identifiant ou mot de passe incorrect")
    jeton = secrets.token_urlsafe(32)
    maintenant = datetime.now(timezone.utc)
    with transaction(conn):
        conn.execute("DELETE FROM sessions WHERE expire_le < ?", (maintenant.isoformat(),))
        conn.execute("INSERT INTO sessions (jeton_hash, utilisateur_id, cree_le, expire_le) VALUES (?,?,?,?)",
                     (_empreinte(jeton), u["id"], maintenant.isoformat(), (maintenant + DUREE_SESSION).isoformat()))
        journal.ajouter(conn, acteur=identifiant, type_acteur="humain", action="connexion", objet_type="session",
                        regle="AUTHENTIFICATION")
    return jeton, {"id": u["id"], "identifiant": u["identifiant"], "nom": u["nom"], "role": u["role"]}


def utilisateur_du_jeton(conn: sqlite3.Connection, jeton: str) -> dict | None:
    ligne = conn.execute(
        "SELECT u.id, u.identifiant, u.nom, u.role FROM sessions s JOIN utilisateurs u ON u.id = s.utilisateur_id"
        " WHERE s.jeton_hash = ? AND s.expire_le > ? AND u.actif = 1",
        (_empreinte(jeton), datetime.now(timezone.utc).isoformat())).fetchone()
    return dict(ligne) if ligne else None


def deconnexion(conn: sqlite3.Connection, jeton: str) -> None:
    with transaction(conn):
        conn.execute("DELETE FROM sessions WHERE jeton_hash = ?", (_empreinte(jeton),))


def masquer_telephone(telephone: str | None) -> str | None:
    """« +229 0190000001 » → « +229 01•••••••01 » : l'auditeur voit qu'un numéro existe, pas lequel."""
    if not telephone:
        return telephone
    chiffres = re.sub(r"\D", "", telephone)
    if len(chiffres) < 6:
        return "•" * len(chiffres)
    return f"+{chiffres[:3]} {chiffres[3:5]}{'•' * (len(chiffres) - 7)}{chiffres[-2:]}"
