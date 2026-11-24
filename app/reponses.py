"""Réponses des clients aux relances, saisies par un humain (docs/regles_metier.md § 9).

- promesse / demande de délai : date obligatoire ; relances suspendues jusqu'à cette date, puis reprises ;
- paiement annoncé : relances suspendues quelques jours (paramètre), le temps que le paiement arrive ;
- litige : la facture passe en litige (décision humaine journalisée) ;
- injoignable, demande d'information, sans rapport : tracé au journal, sans effet sur les relances.
"""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta

from app import journal, parametres, statuts
from app.db import transaction
from app.erreurs import ErreurMetier

TYPES = ("promesse", "paiement_annonce", "litige", "injoignable", "demande_delai", "demande_info", "sans_rapport")
DELAI_MAX_PROMESSE_JOURS = 90


def enregistrer(conn: sqlite3.Connection, client_id: int, type_reponse: str, auteur: str, *,
                facture_id: int | None = None, date_promise: str | None = None, texte: str | None = None) -> int:
    if type_reponse not in TYPES:
        raise ErreurMetier("TYPE_INVALIDE", f"Type de réponse inconnu (attendu : {', '.join(TYPES)})")
    if not conn.execute("SELECT 1 FROM clients WHERE id = ?", (client_id,)).fetchone():
        raise ErreurMetier("INTROUVABLE", "Client introuvable")
    if facture_id is not None and not conn.execute(
            "SELECT 1 FROM factures WHERE id = ? AND client_id = ?", (facture_id, client_id)).fetchone():
        raise ErreurMetier("FACTURE_INCONNUE", "Cette facture n'appartient pas à ce client")
    aujourd_hui = parametres.date_du_jour(conn)

    if type_reponse in ("promesse", "demande_delai"):
        if not date_promise:
            raise ErreurMetier("DATE_OBLIGATOIRE", "Indiquez la date promise par le client")
        try:
            promise = date.fromisoformat(date_promise)
        except ValueError:
            raise ErreurMetier("DATE_INVALIDE", f"Date invalide : {date_promise}") from None
        if not aujourd_hui <= promise <= aujourd_hui + timedelta(days=DELAI_MAX_PROMESSE_JOURS):
            raise ErreurMetier("DATE_INVALIDE",
                               f"La date promise doit être entre aujourd'hui et {DELAI_MAX_PROMESSE_JOURS} jours")
    elif type_reponse == "paiement_annonce":
        date_promise = (aujourd_hui + timedelta(days=parametres.lire(conn, "delai_paiement_annonce_jours"))).isoformat()
    elif type_reponse == "litige":
        if facture_id is None:
            raise ErreurMetier("FACTURE_OBLIGATOIRE", "Un litige porte sur une facture : indiquez-la")
        date_promise = None
    else:
        date_promise = None

    if type_reponse == "litige":
        statuts.declarer_litige(conn, facture_id, auteur, texte or "Litige signalé par le client")
    with transaction(conn):
        rid = conn.execute(
            "INSERT INTO reponses_client (client_id, facture_id, type, date_promise, texte, source, confirme, saisi_par)"
            " VALUES (?,?,?,?,?, 'saisie', 1, ?)",
            (client_id, facture_id, type_reponse, date_promise, texte, auteur)).lastrowid
        journal.ajouter(conn, acteur=auteur, type_acteur="humain", action="reponse_client", objet_type="client",
                        objet_id=client_id,
                        apres={"type": type_reponse, "facture_id": facture_id, "date_promise": date_promise},
                        regle=f"REPONSE_{type_reponse.upper()}")
    return rid
