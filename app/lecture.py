"""Lecture des fichiers d'import (CSV ou XLSX) et correspondance des colonnes.

- Encodage détecté : UTF-8 (avec ou sans BOM), sinon Windows-1252, sinon Latin-1.
- Séparateur détecté sur la ligne d'en-tête : « ; », « , », tabulation ou « | ».
- Les en-têtes sont rapprochés des champs attendus par synonymes, sans tenir compte
  des accents, de la casse ni de la ponctuation (« N° facture » → numero_facture).
"""
from __future__ import annotations

import codecs
import csv
import io
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from app.normalisation import cle_entete

SEPARATEURS = (";", ",", "\t", "|")


@dataclass
class Tableau:
    entetes: list[str]
    lignes: list[tuple[int, list[str]]]  # (numéro de ligne dans le fichier, cellules)
    format: str
    encodage: str | None = None
    separateur: str | None = None


class FichierIllisible(ValueError):
    pass


# Champ → (obligatoire, synonymes déjà normalisés par cle_entete)
CHAMPS: dict[str, dict[str, tuple[bool, set[str]]]] = {
    "clients": {
        "code_client": (True, {"codeclient", "code", "idclient", "refclient", "client", "numeroclient"}),
        "nom": (True, {"nom", "nomclient", "raisonsociale", "societe", "entreprise"}),
        "telephone": (False, {"telephone", "tel", "phone", "mobile", "portable", "numerotelephone"}),
        "email": (False, {"email", "mail", "courriel", "adresseemail"}),
        "canal_prefere": (False, {"canalprefere", "canal", "moyencontact"}),
        "langue": (False, {"langue", "language"}),
        "sensible": (False, {"sensible", "clientsensible"}),
        "notes": (False, {"notes", "note", "commentaire", "remarques"}),
    },
    "factures": {
        "numero_facture": (True, {"numerofacture", "nfacture", "nofacture", "numfacture", "facture", "numero",
                                  "reffacture"}),
        "code_client": (True, {"codeclient", "client", "idclient", "refclient", "numeroclient"}),
        "date_emission": (True, {"dateemission", "datefacture", "emission", "datedefacture", "date"}),
        "date_echeance": (True, {"dateecheance", "echeance", "datelimite", "dateexigibilite", "datedecheance"}),
        "montant_ttc": (True, {"montantttc", "montant", "totalttc", "ttc", "montanttotal", "net"}),
        "devise": (True, {"devise", "monnaie", "currency"}),
        "litige": (False, {"litige", "enlitige", "contestation", "conteste"}),
    },
    "paiements": {
        "id_transaction": (True, {"idtransaction", "transaction", "reftransaction", "idtx", "numerotransaction"}),
        "date": (True, {"date", "datepaiement", "dateoperation"}),
        "montant": (True, {"montant", "montantpaye", "somme"}),
        "devise": (False, {"devise", "monnaie", "currency"}),
        "reference": (False, {"reference", "refpaiement", "referencepaiement", "motif", "libelle"}),
        "telephone_payeur": (False, {"telephonepayeur", "telephone", "payeur", "expediteur", "numeropayeur"}),
        "operateur": (False, {"operateur", "reseau", "fournisseur"}),
    },
}


def detecter_encodage(contenu: bytes) -> str:
    if contenu.startswith(codecs.BOM_UTF8):
        return "utf-8-sig"
    for encodage in ("utf-8", "cp1252"):
        try:
            contenu.decode(encodage)
            return encodage
        except UnicodeDecodeError:
            continue
    return "latin-1"


def detecter_separateur(premiere_ligne: str) -> str:
    comptes = {sep: premiere_ligne.count(sep) for sep in SEPARATEURS}
    meilleur = max(comptes, key=lambda s: comptes[s])
    if comptes[meilleur] == 0:
        raise FichierIllisible("Aucun séparateur de colonnes reconnu (; , tabulation |)")
    return meilleur


def _cellule_xlsx(valeur: object) -> str:
    if valeur is None:
        return ""
    if isinstance(valeur, bool):
        return "oui" if valeur else "non"
    if isinstance(valeur, datetime):
        return valeur.date().isoformat()
    if isinstance(valeur, date):
        return valeur.isoformat()
    if isinstance(valeur, int):
        return str(valeur)
    if isinstance(valeur, float):
        return str(int(valeur)) if valeur.is_integer() else format(Decimal(repr(valeur)), "f")
    return str(valeur)


def _lire_xlsx(contenu: bytes) -> Tableau:
    from openpyxl import load_workbook

    try:
        classeur = load_workbook(io.BytesIO(contenu), read_only=True, data_only=True)
    except Exception as exc:  # fichier corrompu ou pas un vrai XLSX
        raise FichierIllisible(f"Classeur Excel illisible : {exc}") from None
    try:
        lignes = [
            (numero, [_cellule_xlsx(v) for v in valeurs])
            for numero, valeurs in enumerate(classeur.active.iter_rows(values_only=True), start=1)
        ]
    finally:
        classeur.close()
    return _construire(lignes, "xlsx")


def _lire_csv(contenu: bytes) -> Tableau:
    encodage = detecter_encodage(contenu)
    texte = contenu.decode(encodage)
    premiere = next((l for l in texte.splitlines() if l.strip()), "")
    if not premiere:
        raise FichierIllisible("Fichier vide")
    separateur = detecter_separateur(premiere)
    lecteur = csv.reader(io.StringIO(texte, newline=""), delimiter=separateur)
    try:
        lignes = [(lecteur.line_num, cellules) for cellules in lecteur]
    except csv.Error as exc:
        raise FichierIllisible(f"CSV mal formé : {exc}") from None
    return _construire(lignes, "csv", encodage, separateur)


def _construire(lignes, format_, encodage=None, separateur=None) -> Tableau:
    non_vides = [(n, c) for n, c in lignes if any(str(x).strip() for x in c)]
    if not non_vides:
        raise FichierIllisible("Fichier vide")
    (_, entetes), *donnees = non_vides
    entetes = [str(e).strip() for e in entetes]
    largeur = len(entetes)
    donnees = [(n, (c + [""] * largeur)[:largeur]) for n, c in donnees]
    return Tableau(entetes, donnees, format_, encodage, separateur)


def lire_tableau(contenu: bytes, nom_fichier: str) -> Tableau:
    if contenu[:4] == b"PK\x03\x04" or nom_fichier.lower().endswith((".xlsx", ".xlsm")):
        return _lire_xlsx(contenu)
    return _lire_csv(contenu)


def proposer_correspondance(type_import: str, entetes: list[str]) -> dict[str, str | None]:
    """Champ attendu → en-tête du fichier (ou None). Chaque en-tête ne sert qu'une fois."""
    utilises: set[str] = set()
    correspondance: dict[str, str | None] = {}
    for champ, (_, synonymes) in CHAMPS[type_import].items():
        candidats = synonymes | {cle_entete(champ)}
        trouve = next((e for e in entetes if e not in utilises and cle_entete(e) in candidats), None)
        if trouve:
            utilises.add(trouve)
        correspondance[champ] = trouve
    return correspondance


def champs_obligatoires_manquants(type_import: str, correspondance: dict[str, str | None]) -> list[str]:
    return [c for c, (obligatoire, _) in CHAMPS[type_import].items() if obligatoire and not correspondance.get(c)]


def appliquer_correspondance(
    tableau: Tableau, correspondance: dict[str, str | None]
) -> list[tuple[int, dict[str, str]]]:
    index = {e: i for i, e in enumerate(tableau.entetes)}
    resultat = []
    for numero, cellules in tableau.lignes:
        ligne = {champ: (cellules[index[entete]] if entete else "") for champ, entete in correspondance.items()}
        resultat.append((numero, ligne))
    return resultat
