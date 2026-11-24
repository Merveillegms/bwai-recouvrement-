"""Comptes de test. Idempotent : peut être rejoué sans créer de doublon."""
from __future__ import annotations

import sqlite3

from app import journal
from app.db import transaction
from app.securite import hacher_mot_de_passe

# Comptes de démonstration uniquement (documentés dans le README).
UTILISATEURS_TEST = (
    ("gestionnaire", "Gestionnaire Démo", "gestionnaire", "demo-gestionnaire"),
    ("validateur", "Validateur Démo", "validateur", "demo-validateur"),
    ("auditeur", "Auditeur Démo", "auditeur", "demo-auditeur"),
)


def initialiser(conn: sqlite3.Connection) -> int:
    crees = 0
    with transaction(conn):
        for identifiant, nom, role, mot_de_passe in UTILISATEURS_TEST:
            existe = conn.execute("SELECT 1 FROM utilisateurs WHERE identifiant = ?", (identifiant,)).fetchone()
            if existe:
                continue
            conn.execute(
                "INSERT INTO utilisateurs (identifiant, nom, role, mot_de_passe_hash) VALUES (?,?,?,?)",
                (identifiant, nom, role, hacher_mot_de_passe(mot_de_passe)),
            )
            journal.ajouter(
                conn,
                acteur="systeme",
                type_acteur="systeme",
                action="creation_compte_test",
                objet_type="utilisateur",
                objet_id=identifiant,
                apres={"role": role},
                regle="seed",
            )
            crees += 1
    return crees
