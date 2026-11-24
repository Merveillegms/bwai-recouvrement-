"""Statuts des factures : table des transitions autorisées et actions humaines.

Le statut enregistré n'est modifié QUE par `actualiser`, qui :
1. recalcule l'état réel (etat.calculer) ;
2. vérifie que la transition est autorisée, et pour qui (humain ou système) ;
3. incrémente la version de la facture (utilisée par la revalidation avant envoi) ;
4. journalise l'ancien et le nouveau statut avec la règle appliquée.
L'appelant ouvre la transaction.
"""
from __future__ import annotations

import sqlite3

from app import etat as moteur
from app import journal
from app.db import transaction
from app.erreurs import ErreurMetier, exiger_motif
from app.montants import formater

TRANSITIONS: dict[str, set[str]] = {
    "a_echoir": {"echue", "partiellement_payee", "payee", "en_litige", "suspendue", "cloturee"},
    "echue": {"a_echoir", "partiellement_payee", "payee", "en_litige", "suspendue", "cloturee"},
    "partiellement_payee": {"a_echoir", "echue", "payee", "en_litige", "suspendue", "cloturee"},
    "payee": {"a_echoir", "echue", "partiellement_payee", "en_litige", "cloturee"},
    "en_litige": {"a_echoir", "echue", "partiellement_payee", "payee", "suspendue", "cloturee"},
    "suspendue": {"a_echoir", "echue", "partiellement_payee", "payee", "en_litige", "cloturee"},
    "cloturee": set(),  # état final
}
# Seul un humain peut faire entrer en litige / suspension / clôture, en faire sortir,
# ou faire revenir une facture payée vers un état dû (annulation d'un rapprochement, avoir annulé…).
_DECISIONS_HUMAINES_ENTREE = {"en_litige", "suspendue", "cloturee"}
_DECISIONS_HUMAINES_SORTIE = {"en_litige", "suspendue", "payee"}


class TransitionInterdite(ErreurMetier):
    pass


def controler_transition(de: str, vers: str, type_acteur: str) -> None:
    if de == vers:
        return
    if vers not in TRANSITIONS[de]:
        raise TransitionInterdite("TRANSITION_INTERDITE", f"Passage de « {de} » à « {vers} » interdit")
    if type_acteur != "humain" and (vers in _DECISIONS_HUMAINES_ENTREE or de in _DECISIONS_HUMAINES_SORTIE):
        raise TransitionInterdite("DECISION_HUMAINE_REQUISE",
                                  f"Passage de « {de} » à « {vers} » réservé à une décision humaine")


def actualiser(conn: sqlite3.Connection, facture_id: int, *, auteur: str, type_acteur: str, regle: str,
               ctx: moteur.Contexte | None = None, donnees_modifiees: bool = False) -> moteur.EtatFacture:
    """Aligne le statut enregistré sur l'état réel. `donnees_modifiees` : le solde ou les champs ont changé,
    la version doit augmenter même si le statut reste le même."""
    e = moteur.etat(conn, facture_id, ctx)
    if e is None:
        raise ErreurMetier("INTROUVABLE", "Facture introuvable")
    change = e.statut != e.statut_enregistre
    if change:
        controler_transition(e.statut_enregistre, e.statut, type_acteur)
    if change or donnees_modifiees:
        conn.execute("UPDATE factures SET statut = ?, version = version + 1,"
                     " maj_le = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id = ?", (e.statut, facture_id))
    if change:
        journal.ajouter(conn, acteur=auteur, type_acteur=type_acteur, action="changement_statut",
                        objet_type="facture", objet_id=facture_id,
                        avant={"statut": e.statut_enregistre},
                        apres={"statut": e.statut, "solde": e.solde, "jours_retard": e.jours_retard}, regle=regle)
    return moteur.etat(conn, facture_id, ctx)


def recalculer_tout(conn: sqlite3.Connection, auteur: str = "systeme") -> dict[str, int]:
    """Recalcul quotidien (passage à échéance, etc.). Idempotent : relancé, il ne change plus rien."""
    changements: dict[str, int] = {}
    with transaction(conn):
        ctx = moteur.contexte(conn)
        for e in moteur.etats(conn, "f.statut <> 'cloturee'", ctx=ctx):
            if e.statut != e.statut_enregistre:
                actualiser(conn, e.id, auteur=auteur, type_acteur="systeme", regle="RECALCUL", ctx=ctx)
                cle = f"{e.statut_enregistre}->{e.statut}"
                changements[cle] = changements.get(cle, 0) + 1
    return changements


# ------------------------------------------------------------------ actions humaines
def _facture_modifiable(conn, facture_id) -> moteur.EtatFacture:
    e = moteur.etat(conn, facture_id)
    if e is None:
        raise ErreurMetier("INTROUVABLE", "Facture introuvable")
    if e.statut == "cloturee":
        raise ErreurMetier("DEJA_CLOTUREE", "Facture clôturée : aucune modification possible")
    return e


def _drapeau(conn, facture_id, colonne, valeur, auteur, motif, regle, action) -> moteur.EtatFacture:
    motif = exiger_motif(motif)
    with transaction(conn):
        e = _facture_modifiable(conn, facture_id)
        if bool(getattr(e, colonne)) == valeur:
            raise ErreurMetier("NON_APPLICABLE", "Aucun changement : la facture est déjà dans cet état")
        conn.execute(f"UPDATE factures SET {colonne} = ? WHERE id = ?", (int(valeur), facture_id))
        journal.ajouter(conn, acteur=auteur, type_acteur="humain", action=action, objet_type="facture",
                        objet_id=facture_id, avant={colonne: not valeur}, apres={colonne: valeur, "motif": motif},
                        regle=regle)
        return actualiser(conn, facture_id, auteur=auteur, type_acteur="humain", regle=regle, donnees_modifiees=True)


def declarer_litige(conn, facture_id: int, auteur: str, motif: str | None) -> moteur.EtatFacture:
    return _drapeau(conn, facture_id, "en_litige", True, auteur, motif, "LITIGE_DECLARE", "declaration_litige")


def lever_litige(conn, facture_id: int, auteur: str, motif: str | None) -> moteur.EtatFacture:
    return _drapeau(conn, facture_id, "en_litige", False, auteur, motif, "LITIGE_LEVE", "levee_litige")


def suspendre(conn, facture_id: int, auteur: str, motif: str | None) -> moteur.EtatFacture:
    return _drapeau(conn, facture_id, "suspendue", True, auteur, motif, "SUSPENSION", "suspension")


def reprendre(conn, facture_id: int, auteur: str, motif: str | None) -> moteur.EtatFacture:
    return _drapeau(conn, facture_id, "suspendue", False, auteur, motif, "REPRISE", "reprise")


def creer_avoir(conn, facture_id: int, montant: int, auteur: str, motif: str | None,
                date_avoir: str | None = None) -> moteur.EtatFacture:
    """Avoir lié à la facture (montant en unités mineures), au plus égal au solde restant."""
    motif = exiger_motif(motif)
    with transaction(conn):
        e = _facture_modifiable(conn, facture_id)
        if montant <= 0:
            raise ErreurMetier("MONTANT_INVALIDE", "Le montant de l'avoir doit être positif")
        if montant > e.solde:
            raise ErreurMetier("AVOIR_SUPERIEUR_AU_SOLDE",
                               f"Avoir de {formater(montant, e.devise, e.decimales)} supérieur au solde "
                               f"({formater(e.solde, e.devise, e.decimales)})")
        conn.execute("INSERT INTO avoirs (facture_id, montant, date_avoir, motif, cree_par) VALUES (?,?,?,?,?)",
                     (facture_id, montant, date_avoir or moteur.contexte(conn).reference.isoformat(), motif, auteur))
        journal.ajouter(conn, acteur=auteur, type_acteur="humain", action="creation_avoir", objet_type="facture",
                        objet_id=facture_id, avant={"solde": e.solde}, apres={"avoir": montant, "motif": motif},
                        regle="AVOIR")
        return actualiser(conn, facture_id, auteur=auteur, type_acteur="humain", regle="AVOIR",
                          donnees_modifiees=True)


def passer_en_perte(conn, facture_id: int, auteur: str, motif: str | None) -> moteur.EtatFacture:
    motif = exiger_motif(motif)
    with transaction(conn):
        e = _facture_modifiable(conn, facture_id)
        conn.execute("UPDATE factures SET motif_cloture = ? WHERE id = ?", (f"Passage en perte : {motif}", facture_id))
        journal.ajouter(conn, acteur=auteur, type_acteur="humain", action="passage_en_perte", objet_type="facture",
                        objet_id=facture_id, avant={"statut": e.statut, "solde": e.solde}, apres={"motif": motif},
                        regle="PASSAGE_EN_PERTE")
        return actualiser(conn, facture_id, auteur=auteur, type_acteur="humain", regle="PASSAGE_EN_PERTE",
                          donnees_modifiees=True)
