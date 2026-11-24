"""Verrou simple en base contre deux traitements concurrents (deux envois en parallèle, par exemple).

Le détenteur est « pid:identifiant ». Un verrou est repris s'il a expiré ou si le processus qui le
détenait n'existe plus (programme tué) : la reprise après interruption n'attend pas l'expiration.
"""
from __future__ import annotations

import os
import sqlite3
import sys
import uuid
from datetime import datetime, timedelta, timezone

from app.db import transaction


def _processus_vivant(pid: int) -> bool:
    if pid == os.getpid():
        return True
    if sys.platform == "win32":
        import ctypes

        noyau = ctypes.windll.kernel32
        poignee = noyau.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not poignee:
            return False
        try:
            code = ctypes.c_ulong()
            noyau.GetExitCodeProcess(poignee, ctypes.byref(code))
            return code.value == 259  # STILL_ACTIVE
        finally:
            noyau.CloseHandle(poignee)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def nouveau_detenteur() -> str:
    return f"{os.getpid()}:{uuid.uuid4().hex[:8]}"


def acquerir(conn: sqlite3.Connection, nom: str, detenteur: str, duree_s: int = 600) -> bool:
    maintenant = datetime.now(timezone.utc)
    with transaction(conn):
        actuel = conn.execute("SELECT * FROM verrous WHERE nom = ?", (nom,)).fetchone()
        if actuel is not None and actuel["detenteur"] != detenteur:
            echeance = datetime.fromisoformat(actuel["expire_le"])
            if echeance.tzinfo is None:
                echeance = echeance.replace(tzinfo=timezone.utc)
            expire = echeance <= maintenant
            pid = int(actuel["detenteur"].split(":")[0])
            if not expire and _processus_vivant(pid):
                return False
        conn.execute("INSERT OR REPLACE INTO verrous (nom, detenteur, acquis_le, expire_le) VALUES (?,?,?,?)",
                     (nom, detenteur, maintenant.isoformat(), (maintenant + timedelta(seconds=duree_s)).isoformat()))
    return True


def liberer(conn: sqlite3.Connection, nom: str, detenteur: str) -> None:
    with transaction(conn):
        conn.execute("DELETE FROM verrous WHERE nom = ? AND detenteur = ?", (nom, detenteur))
