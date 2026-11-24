"""Mode démonstration : montrer toute la séquence en 3 minutes.

- charger : importe le jeu de démo (base vide uniquement) à la date du 15/12/2026 ;
- avancer : fait avancer l'horloge métier de N jours (statuts recalculés, journalisé) ;
- payer : simule le paiement mobile money d'un client citant la référence de sa facture ;
- executer : prépare la file du jour puis envoie ce qui est validé (horaire simulé : 10 h).
Toute action passe par les mêmes règles et le même journal que l'usage réel.
"""
from __future__ import annotations

import sqlite3
from datetime import date, datetime, time, timedelta

from app import config, importer, journal, parametres, rapprochement, relances, statuts
from app import etat as moteur
from app.db import transaction
from app.erreurs import ErreurMetier

DATE_DEMO = "2026-12-15"
FICHIERS = (("clients.csv", "clients"), ("factures_lot1.csv", "factures"), ("factures_lot2.csv", "factures"),
            ("paiements_mobile_money.csv", "paiements"))


def charger(conn: sqlite3.Connection, auteur: str) -> dict:
    if conn.execute("SELECT 1 FROM factures LIMIT 1").fetchone():
        raise ErreurMetier("DEJA_CHARGE", "Des données existent déjà : réinitialisez d'abord (python tasks.py reset)")
    parametres.ecrire(conn, "date_du_jour_simulee", DATE_DEMO, auteur)
    rapports = {}
    for nom, type_ in FICHIERS:
        r = importer.importer(conn, type_, (config.DOSSIER_DEMO / nom).read_bytes(), nom, auteur)
        rapports[nom] = {"lues": r.lignes_lues, "acceptees": r.lignes_acceptees,
                         "avertissements": r.lignes_avertissement, "rejetees": r.lignes_rejetees}
    return {"date": DATE_DEMO, "imports": rapports, "rapprochement": rapprochement.rapprocher_tout(conn)}


def _exiger_simulation(conn) -> date:
    simulee = parametres.lire(conn, "date_du_jour_simulee")
    if not simulee:
        raise ErreurMetier("MODE_REEL", "Horloge réelle : les actions de démonstration sont désactivées")
    return date.fromisoformat(simulee)


def avancer(conn: sqlite3.Connection, jours: int, auteur: str) -> dict:
    if not 1 <= jours <= 90:
        raise ErreurMetier("VALEUR_INVALIDE", "Avancer de 1 à 90 jours")
    nouvelle = _exiger_simulation(conn) + timedelta(days=jours)
    parametres.ecrire(conn, "date_du_jour_simulee", nouvelle.isoformat(), auteur)
    return {"date": nouvelle.isoformat(), "changements": statuts.recalculer_tout(conn)}


def payer(conn: sqlite3.Connection, facture_id: int, auteur: str, montant: int | None = None) -> dict:
    """Le client paie par mobile money en citant la référence : le paiement suit le circuit normal."""
    jour = _exiger_simulation(conn)
    e = moteur.etat(conn, facture_id)
    if e is None:
        raise ErreurMetier("INTROUVABLE", "Facture introuvable")
    if e.solde == 0:
        raise ErreurMetier("RIEN_A_PAYER", "Facture déjà soldée")
    montant = montant or e.solde
    with transaction(conn):
        n = conn.execute("SELECT count(*) FROM paiements WHERE id_transaction LIKE 'DEMO-%'").fetchone()[0]
        tel = conn.execute("SELECT telephone FROM clients WHERE id = ?", (e.client_id,)).fetchone()[0]
        conn.execute("INSERT INTO paiements (id_transaction, date_paiement, montant, devise, reference_citee,"
                     " telephone_payeur, operateur, source) VALUES (?,?,?,?,?,?, 'MTN MoMo', 'mobile_money')",
                     (f"DEMO-{n + 1:04d}", jour.isoformat(), montant, e.devise, e.reference_paiement, tel))
        journal.ajouter(conn, acteur=auteur, type_acteur="humain", action="paiement_simule", objet_type="facture",
                        objet_id=facture_id, apres={"montant": montant}, regle="DEMO")
    resume = rapprochement.rapprocher_tout(conn)
    return {"rapprochement": resume, "facture": moteur.etat(conn, facture_id).en_dict()}


def executer(conn: sqlite3.Connection, auteur: str) -> dict:
    jour = _exiger_simulation(conn)
    preparation = relances.preparer(conn, auteur)
    envoi = relances.envoyer(conn, auteur, maintenant=datetime.combine(jour, time(10, 0)))
    return {"preparation": preparation, "envoi": envoi}
