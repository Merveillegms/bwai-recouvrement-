"""Fiche de paiement PDF : facture, solde, référence à citer et modalités mobile money.

Toutes les valeurs viennent de l'état calculé (etat.EtatFacture) : aucune n'est recalculée ici.
Polices PDF standard (Latin-1) : les caractères hors Latin-1 sont remplacés proprement.
"""
from __future__ import annotations

import sqlite3
from datetime import date

from fpdf import FPDF

from app import etat as moteur
from app import parametres
from app.erreurs import ErreurMetier
from app.montants import formater
from app.references import formater_reference

_REMPLACEMENTS = {"’": "'", "–": "-", "—": "-", " ": " ", " ": " ", "…": "..."}


def _latin1(texte: str) -> str:
    for a, b in _REMPLACEMENTS.items():
        texte = texte.replace(a, b)
    return texte.encode("latin-1", "replace").decode("latin-1")


def _date(iso: str) -> str:
    return date.fromisoformat(iso).strftime("%d/%m/%Y")


def generer_fiche(conn: sqlite3.Connection, facture_id: int) -> bytes:
    e = moteur.etat(conn, facture_id)
    if e is None:
        raise ErreurMetier("INTROUVABLE", "Facture introuvable")
    if e.solde == 0:
        raise ErreurMetier("RIEN_A_PAYER", "Cette facture est soldée : aucune fiche de paiement à émettre")
    entreprise = parametres.lire(conn, "entreprise")
    reference_jour = parametres.date_du_jour(conn).isoformat()

    pdf = FPDF(format="A4")
    pdf.set_compression(False)  # texte lisible dans le fichier : vérifiable par les tests et l'audit
    pdf.set_title(_latin1(f"Fiche de paiement {e.numero}"))
    pdf.add_page()
    pdf.set_margins(18, 18, 18)

    def ligne(texte: str, taille: int = 11, gras: bool = False, hauteur: float = 7) -> None:
        pdf.set_font("Helvetica", "B" if gras else "", taille)
        pdf.multi_cell(0, hauteur, _latin1(texte), new_x="LMARGIN", new_y="NEXT")

    ligne(entreprise["nom"], 16, True, 9)
    ligne(f"{entreprise['ville']} - {entreprise['telephone']} - {entreprise['email']}", 9)
    pdf.ln(6)
    ligne("FICHE DE PAIEMENT", 14, True)
    ligne(f"Éditée le {_date(reference_jour)}", 9)
    pdf.ln(4)
    ligne(f"Client : {e.nom_client} ({e.code_client})")
    ligne(f"Facture : {e.numero} du {_date(e.date_emission)}, échéance le {_date(e.date_echeance)}")
    pdf.ln(2)
    for libelle, valeur in (("Montant TTC", e.montant_ttc), ("Déjà réglé", e.total_paye),
                            ("Avoirs", e.total_avoirs)):
        if valeur or libelle == "Montant TTC":
            ligne(f"{libelle} : {formater(valeur, e.devise, e.decimales)}")
    ligne(f"Reste à payer : {formater(e.solde, e.devise, e.decimales)}", 13, True, 9)
    pdf.ln(4)
    ligne("Référence à indiquer dans le motif du paiement :", 11, True)
    ligne(formater_reference(e.reference_paiement), 22, True, 12)
    pdf.ln(4)
    ligne("Modalités de paiement par mobile money :", 11, True)
    for o in entreprise["mobile_money"]:
        ligne(f"- {o['operateur']} : numéro marchand {o['numero']}")
    pdf.ln(2)
    ligne("Merci d'indiquer la référence ci-dessus : elle permet d'enregistrer votre paiement sans erreur. "
          "Pour un paiement partiel ou un échéancier, contactez notre service recouvrement.", 9)
    return bytes(pdf.output())
