"""Connexion SQLite, transactions et migrations versionnées."""
from __future__ import annotations

import hashlib
import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from app import config

_NOM_MIGRATION = re.compile(r"^\d{4}_[a-z0-9_]+$")


class MigrationModifiee(RuntimeError):
    """Une migration déjà appliquée a été modifiée après coup."""


def connecter(chemin: Path | str | None = None) -> sqlite3.Connection:
    """Ouvre la base en mode autocommit : les transactions sont toujours explicites."""
    chemin = Path(chemin) if chemin else config.chemin_base()
    chemin.parent.mkdir(parents=True, exist_ok=True)
    # check_same_thread=False : FastAPI peut ouvrir la connexion dans un thread et l'utiliser dans un autre.
    # Chaque requête a sa propre connexion, utilisée en série : pas d'accès concurrent à un même objet.
    conn = sqlite3.connect(chemin, isolation_level=None, timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Transaction IMMEDIATE : prend le verrou d'écriture dès le début (pas de course)."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def _empreinte(script: str) -> str:
    # Fins de ligne normalisées : la même migration a la même empreinte sous Windows et Linux.
    return hashlib.sha256(script.replace("\r\n", "\n").encode("utf-8")).hexdigest()


def migrer(conn: sqlite3.Connection, dossier: Path | None = None) -> list[str]:
    """Applique, dans l'ordre, les migrations non encore appliquées. Retourne leurs versions."""
    dossier = dossier or config.DOSSIER_MIGRATIONS
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        " version TEXT PRIMARY KEY, empreinte TEXT NOT NULL, appliquee_le TEXT NOT NULL)"
    )
    appliquees = {
        r["version"]: r["empreinte"] for r in conn.execute("SELECT version, empreinte FROM schema_migrations")
    }
    nouvelles: list[str] = []
    for fichier in sorted(dossier.glob("*.sql")):
        version = fichier.stem
        if not _NOM_MIGRATION.match(version):
            raise ValueError(f"Nom de migration invalide : {fichier.name}")
        script = fichier.read_text(encoding="utf-8")
        empreinte = _empreinte(script)
        if version in appliquees:
            if appliquees[version] != empreinte:
                raise MigrationModifiee(
                    f"La migration {version} a été modifiée après application : créer une nouvelle migration."
                )
            continue
        horodatage = datetime.now(timezone.utc).isoformat()
        try:
            conn.executescript(
                "BEGIN;\n"
                + script
                + f"\nINSERT INTO schema_migrations VALUES ('{version}', '{empreinte}', '{horodatage}');\nCOMMIT;"
            )
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        nouvelles.append(version)
    return nouvelles


def version_schema(conn: sqlite3.Connection) -> str | None:
    ligne = conn.execute("SELECT max(version) AS v FROM schema_migrations").fetchone()
    return ligne["v"] if ligne else None
