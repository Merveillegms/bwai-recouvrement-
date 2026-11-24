"""Import des clients, factures et paiements, avec contrôle ligne à ligne.

Garanties :
- Un fichier (même empreinte SHA-256) n'est importé qu'une fois.
- L'import est transactionnel : une erreur technique annule tout, rien n'est importé à moitié.
- Chaque ligne rejetée ou douteuse est conservée avec son code et son motif (import_anomalies).
- Chaque création passe au journal d'audit.
Règles : docs/regles_metier.md § 6.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal

from app import calculs, journal, parametres
from app.db import transaction
from app.lecture import (
    FichierIllisible,
    appliquer_correspondance,
    champs_obligatoires_manquants,
    lire_tableau,
    proposer_correspondance,
)
from app.normalisation import ErreurValeur, lire_booleen, lire_date, lire_montant, nettoyer
from app.references import generer_reference

TYPES = ("clients", "factures", "paiements")
CANAUX = ("sms", "whatsapp", "email")

LIBELLES_CHAMPS = {
    "numero_facture": "numéro de facture", "code_client": "code client", "date_emission": "date d'émission",
    "date_echeance": "date d'échéance", "montant_ttc": "montant TTC", "devise": "devise", "nom": "nom",
    "id_transaction": "identifiant de transaction", "date": "date", "montant": "montant",
}


class ImportRefuse(Exception):
    """Le fichier entier est refusé (rien n'est importé)."""

    def __init__(self, code: str, message: str, details: dict | None = None) -> None:
        super().__init__(message)
        self.code, self.message, self.details = code, message, details or {}


@dataclass
class Anomalie:
    ligne: int
    gravite: str  # rejet | avertissement
    code: str
    message: str
    donnees: dict


@dataclass
class RapportImport:
    import_id: int
    type: str
    fichier: str
    empreinte: str
    format: str
    encodage: str | None
    separateur: str | None
    correspondance: dict
    lignes_lues: int
    lignes_acceptees: int
    lignes_avertissement: int
    lignes_rejetees: int
    anomalies: list[Anomalie] = field(default_factory=list)

    def en_dict(self) -> dict:
        return asdict(self)


def _maintenant() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _rejet(ligne: int, brut: dict, code: str, message: str) -> Anomalie:
    return Anomalie(ligne, "rejet", code, message, brut)


def _champ_manquant(ligne: int, brut: dict, valeurs: dict, champs: tuple[str, ...]) -> Anomalie | None:
    for champ in champs:
        if not valeurs[champ]:
            return _rejet(ligne, brut, "CHAMP_MANQUANT", f"Champ obligatoire vide : {LIBELLES_CHAMPS.get(champ, champ)}")
    return None


# --------------------------------------------------------------------------- clients
def _traiter_clients(conn, import_id, lignes, auteur) -> tuple[list[Anomalie], int, int]:
    anomalies: list[Anomalie] = []
    acceptees = 0
    vus: dict[str, tuple] = {}
    for numero, brut in lignes:
        v = {k: nettoyer(x) for k, x in brut.items()}
        v["code_client"] = v["code_client"].upper()
        if a := _champ_manquant(numero, brut, v, ("code_client", "nom")):
            anomalies.append(a)
            continue
        canal = v["canal_prefere"].lower() or ("whatsapp" if v["telephone"] else "email" if v["email"] else "sms")
        if canal not in CANAUX:
            anomalies.append(_rejet(numero, brut, "CANAL_INVALIDE",
                                    f"Canal « {v['canal_prefere']} » inconnu (attendu : sms, whatsapp, email)"))
            continue
        try:
            sensible = lire_booleen(v["sensible"])
        except ErreurValeur as e:
            anomalies.append(_rejet(numero, brut, e.code, f"Champ sensible : {e.message}"))
            continue
        fiche = (v["nom"], v["telephone"] or None, v["email"] or None, canal, v["langue"] or "fr", int(sensible),
                 v["notes"] or None)
        code = v["code_client"]
        if code in vus:
            if vus[code] == fiche:
                anomalies.append(_rejet(numero, brut, "DOUBLON_EXACT", f"Client {code} déjà présent plus haut dans le fichier"))
            else:
                anomalies.append(_rejet(numero, brut, "CONFLIT_CODE",
                                        f"Client {code} présent deux fois avec des informations différentes"))
            continue
        vus[code] = fiche
        existant = conn.execute("SELECT * FROM clients WHERE code = ?", (code,)).fetchone()
        if existant and existant["statut_validation"] == "en_attente":
            # Client créé « en attente » par un import de factures : le fichier clients le complète.
            conn.execute(
                "UPDATE clients SET nom=?, telephone=?, email=?, canal_prefere=?, langue=?, sensible=?, notes=?,"
                " statut_validation='valide', import_id=? WHERE id=?",
                (*fiche, import_id, existant["id"]),
            )
            journal.ajouter(conn, acteur=auteur, type_acteur="humain", action="completion_client",
                            objet_type="client", objet_id=code, avant=dict(existant), apres={"nom": fiche[0]},
                            regle="IMPORT_CLIENT_EN_ATTENTE")
            acceptees += 1
            continue
        if existant:
            actuel = tuple(existant[c] for c in ("nom", "telephone", "email", "canal_prefere", "langue", "sensible", "notes"))
            if actuel == fiche:
                anomalies.append(_rejet(numero, brut, "DOUBLON_IMPORT", f"Client {code} déjà en base, identique"))
            else:
                anomalies.append(_rejet(numero, brut, "CONFLIT_CODE",
                                        f"Client {code} déjà en base avec des informations différentes"))
            continue
        conn.execute(
            "INSERT INTO clients (code, nom, telephone, email, canal_prefere, langue, sensible, notes, import_id)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (code, *fiche, import_id),
        )
        journal.ajouter(conn, acteur=auteur, type_acteur="humain", action="creation_client", objet_type="client",
                        objet_id=code, apres={"nom": fiche[0], "canal": canal, "sensible": bool(sensible)},
                        regle="IMPORT")
        acceptees += 1
    return anomalies, acceptees, 0


# -------------------------------------------------------------------------- factures
@dataclass
class _FactureLue:
    ligne: int
    brut: dict
    numero: str
    code_client: str
    emission: date
    echeance: date
    montant: int
    devise: str
    litige: bool
    avertissements: list[Anomalie] = field(default_factory=list)

    def valeurs(self) -> tuple:
        return (self.emission, self.echeance, self.montant, self.devise, self.litige)


def lire_ligne_facture(numero: int, brut: dict, devises: dict[str, int]) -> _FactureLue | Anomalie:
    """Valide une ligne brute de facture (sans contrôle de doublon). Réutilisée par la résolution humaine."""
    v = {k: nettoyer(x) for k, x in brut.items()}
    if a := _champ_manquant(numero, brut, v, ("numero_facture", "code_client", "date_emission", "date_echeance",
                                               "montant_ttc", "devise")):
        return a
    devise = v["devise"].upper()
    if devise not in devises:
        return _rejet(numero, brut, "DEVISE_INCONNUE", f"Devise « {v['devise']} » non autorisée ({', '.join(devises)})")
    try:
        emission = lire_date(v["date_emission"])
        echeance = lire_date(v["date_echeance"])
        montant = lire_montant(v["montant_ttc"], devises[devise])
        litige = lire_booleen(v.get("litige", ""))
    except ErreurValeur as e:
        return _rejet(numero, brut, e.code, e.message)
    return _FactureLue(numero, brut, v["numero_facture"], v["code_client"].upper(), emission, echeance, montant,
                       devise, litige)


def _mediane(valeurs: list[int]) -> Decimal:
    s = sorted(valeurs)
    milieu = len(s) // 2
    return Decimal(s[milieu]) if len(s) % 2 else (Decimal(s[milieu - 1]) + Decimal(s[milieu])) / 2


def _traiter_factures(conn, import_id, lignes, auteur) -> tuple[list[Anomalie], int, int]:
    devises = {r["code"]: r["decimales"] for r in conn.execute("SELECT code, decimales FROM devises")}
    fenetre = parametres.lire(conn, "fenetre_quasi_doublon_jours")
    facteur = Decimal(str(parametres.lire(conn, "facteur_montant_aberrant")))
    minimum = parametres.lire(conn, "min_factures_montant_aberrant")
    reference = parametres.date_du_jour(conn)

    anomalies: list[Anomalie] = []
    candidates: list[_FactureLue] = []
    vues: dict[tuple[str, str], tuple] = {}

    # Passe 1 : validité de chaque ligne et doublons sur le numéro.
    for numero, brut in lignes:
        lue = lire_ligne_facture(numero, brut, devises)
        if isinstance(lue, Anomalie):
            anomalies.append(lue)
            continue
        cle = (lue.code_client, lue.numero)
        if cle in vues:
            if vues[cle] == lue.valeurs():
                anomalies.append(_rejet(numero, brut, "DOUBLON_EXACT",
                                        f"Facture {lue.numero} ({lue.code_client}) déjà présente plus haut dans le fichier"))
            else:
                anomalies.append(_rejet(numero, brut, "CONFLIT_NUMERO",
                                        f"Facture {lue.numero} ({lue.code_client}) présente deux fois avec des valeurs "
                                        "différentes : à arbitrer"))
            continue
        vues[cle] = lue.valeurs()
        en_base = conn.execute(
            "SELECT f.* FROM factures f JOIN clients c ON c.id = f.client_id WHERE c.code = ? AND f.numero = ?", cle
        ).fetchone()
        if en_base:
            identique = (date.fromisoformat(en_base["date_emission"]), date.fromisoformat(en_base["date_echeance"]),
                         en_base["montant_ttc"], en_base["devise"], bool(en_base["en_litige"])) == lue.valeurs()
            if identique:
                anomalies.append(_rejet(numero, brut, "DOUBLON_IMPORT",
                                        f"Facture {lue.numero} ({lue.code_client}) déjà importée, identique"))
            else:
                anomalies.append(_rejet(numero, brut, "CONFLIT_NUMERO",
                                        f"Facture {lue.numero} ({lue.code_client}) déjà en base avec des valeurs "
                                        "différentes : à arbitrer"))
            continue
        candidates.append(lue)

    # Passe 2 : avertissements (la ligne entre, marquée « à vérifier »).
    clients = {r["code"]: r for r in conn.execute("SELECT id, code, statut_validation FROM clients")}
    for i, f in enumerate(candidates):
        client = clients.get(f.code_client)
        if client is None or client["statut_validation"] == "en_attente":
            f.avertissements.append(Anomalie(f.ligne, "avertissement", "CLIENT_INCONNU",
                                             f"Client {f.code_client} inconnu : créé en attente de validation", f.brut))
        if f.echeance < f.emission:
            f.avertissements.append(Anomalie(f.ligne, "avertissement", "ECHEANCE_AVANT_EMISSION",
                                             f"Échéance {f.echeance} antérieure à l'émission {f.emission}", f.brut))
        similaire = next((g for g in candidates[:i]
                          if g.code_client == f.code_client and g.devise == f.devise and g.montant == f.montant
                          and abs((g.emission - f.emission).days) <= fenetre), None)
        if similaire is None and client is not None:
            for r in conn.execute(
                "SELECT numero, date_emission FROM factures WHERE client_id = ? AND devise = ? AND montant_ttc = ?"
                " AND statut <> 'cloturee'", (client["id"], f.devise, f.montant)
            ):
                if abs((date.fromisoformat(r["date_emission"]) - f.emission).days) <= fenetre:
                    similaire = r
                    break
        if similaire is not None:
            autre = similaire.numero if isinstance(similaire, _FactureLue) else similaire["numero"]
            f.avertissements.append(Anomalie(f.ligne, "avertissement", "QUASI_DOUBLON",
                                             f"Même client, même montant et date proche que la facture {autre}", f.brut))
        autres = [g.montant for g in candidates if g is not f and g.code_client == f.code_client and g.devise == f.devise]
        if client is not None:
            autres += [r[0] for r in conn.execute(
                "SELECT montant_ttc FROM factures WHERE client_id = ? AND devise = ? AND statut <> 'cloturee'",
                (client["id"], f.devise))]
        if len(autres) >= minimum and f.montant > facteur * _mediane(autres):
            f.avertissements.append(Anomalie(f.ligne, "avertissement", "MONTANT_ABERRANT",
                                             f"Montant plus de {facteur} fois supérieur à l'habitude de ce client", f.brut))

    # Passe 3 : écriture.
    avertissements = 0
    for f in candidates:
        client = clients.get(f.code_client)
        if client is None:
            curseur = conn.execute(
                "INSERT INTO clients (code, nom, canal_prefere, statut_validation, import_id)"
                " VALUES (?, ?, 'sms', 'en_attente', ?)", (f.code_client, f"Client {f.code_client} (à compléter)", import_id))
            client = {"id": curseur.lastrowid, "code": f.code_client, "statut_validation": "en_attente"}
            clients[f.code_client] = client
            journal.ajouter(conn, acteur="systeme", type_acteur="systeme", action="creation_client_en_attente",
                            objet_type="client", objet_id=f.code_client, apres={"statut_validation": "en_attente"},
                            regle="CLIENT_INCONNU")
        codes = [a.code for a in f.avertissements]
        statut = calculs.statut(montant_ttc=f.montant, total_paye=0, echeance=f.echeance, reference=reference,
                                en_litige=f.litige)
        reference_paiement = generer_reference(f.code_client, f.numero)
        conn.execute(
            "INSERT INTO factures (numero, client_id, date_emission, date_echeance, montant_ttc, devise,"
            " reference_paiement, statut, en_litige, a_verifier, motif_verification, import_id)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (f.numero, client["id"], f.emission.isoformat(), f.echeance.isoformat(), f.montant, f.devise,
             reference_paiement, statut, int(f.litige), int(bool(codes)), ",".join(codes) or None, import_id),
        )
        journal.ajouter(conn, acteur=auteur, type_acteur="humain", action="creation_facture", objet_type="facture",
                        objet_id=f"{f.code_client}/{f.numero}",
                        apres={"montant_ttc": f.montant, "devise": f.devise, "echeance": f.echeance.isoformat(),
                               "statut": statut, "a_verifier": codes},
                        regle="IMPORT" + ("+" + "+".join(codes) if codes else ""))
        anomalies.extend(f.avertissements)
        avertissements += bool(codes)
    return anomalies, len(candidates) - avertissements, avertissements


# ------------------------------------------------------------------------- paiements
def _traiter_paiements(conn, import_id, lignes, auteur) -> tuple[list[Anomalie], int, int]:
    devises = {r["code"]: r["decimales"] for r in conn.execute("SELECT code, decimales FROM devises")}
    anomalies: list[Anomalie] = []
    acceptees = 0
    vus: set[str] = set()
    for numero, brut in lignes:
        v = {k: nettoyer(x) for k, x in brut.items()}
        if a := _champ_manquant(numero, brut, v, ("id_transaction", "date", "montant")):
            anomalies.append(a)
            continue
        devise = (v.get("devise") or "XOF").upper()
        if devise not in devises:
            anomalies.append(_rejet(numero, brut, "DEVISE_INCONNUE", f"Devise « {devise} » non autorisée"))
            continue
        try:
            date_paiement = lire_date(v["date"])
            montant = lire_montant(v["montant"], devises[devise])
        except ErreurValeur as e:
            anomalies.append(_rejet(numero, brut, e.code, e.message))
            continue
        tx = v["id_transaction"]
        deja = tx in vus or conn.execute("SELECT 1 FROM paiements WHERE id_transaction = ?", (tx,)).fetchone()
        if deja:
            anomalies.append(_rejet(numero, brut, "DOUBLON_PAIEMENT", f"Transaction {tx} déjà enregistrée"))
            continue
        vus.add(tx)
        conn.execute(
            "INSERT INTO paiements (id_transaction, date_paiement, montant, devise, reference_citee, telephone_payeur,"
            " operateur, source, import_id) VALUES (?,?,?,?,?,?,?, 'mobile_money', ?)",
            (tx, date_paiement.isoformat(), montant, devise, v.get("reference") or None,
             v.get("telephone_payeur") or None, v.get("operateur") or None, import_id),
        )
        journal.ajouter(conn, acteur=auteur, type_acteur="humain", action="import_paiement", objet_type="paiement",
                        objet_id=tx, apres={"montant": montant, "devise": devise, "date": date_paiement.isoformat()},
                        regle="IMPORT")
        acceptees += 1
    return anomalies, acceptees, 0


_TRAITEMENTS = {"clients": _traiter_clients, "factures": _traiter_factures, "paiements": _traiter_paiements}


# --------------------------------------------------------------------------- public
def apercu(type_import: str, contenu: bytes, nom_fichier: str, nb_lignes: int = 5) -> dict:
    """Lecture sans écriture : en-têtes, correspondance proposée, premières lignes."""
    if type_import not in TYPES:
        raise ImportRefuse("TYPE_INCONNU", f"Type d'import inconnu : {type_import}")
    try:
        tableau = lire_tableau(contenu, nom_fichier)
    except FichierIllisible as e:
        raise ImportRefuse("FICHIER_ILLISIBLE", str(e)) from None
    correspondance = proposer_correspondance(type_import, tableau.entetes)
    return {
        "format": tableau.format, "encodage": tableau.encodage, "separateur": tableau.separateur,
        "entetes": tableau.entetes, "correspondance": correspondance,
        "champs_manquants": champs_obligatoires_manquants(type_import, correspondance),
        "lignes": [c for _, c in tableau.lignes[:nb_lignes]], "nombre_lignes": len(tableau.lignes),
    }


def importer(
    conn: sqlite3.Connection,
    type_import: str,
    contenu: bytes,
    nom_fichier: str,
    auteur: str,
    correspondance: dict[str, str | None] | None = None,
) -> RapportImport:
    if type_import not in TYPES:
        raise ImportRefuse("TYPE_INCONNU", f"Type d'import inconnu : {type_import}")
    empreinte = hashlib.sha256(contenu).hexdigest()
    try:
        tableau = lire_tableau(contenu, nom_fichier)
    except FichierIllisible as e:
        raise ImportRefuse("FICHIER_ILLISIBLE", str(e)) from None

    correspondance = correspondance or proposer_correspondance(type_import, tableau.entetes)
    inconnues = [e for e in correspondance.values() if e and e not in tableau.entetes]
    if inconnues:
        raise ImportRefuse("COLONNES_INCONNUES", f"Colonnes absentes du fichier : {', '.join(inconnues)}")
    manquants = champs_obligatoires_manquants(type_import, correspondance)
    if manquants:
        raise ImportRefuse("COLONNES_MANQUANTES",
                           "Colonnes obligatoires non trouvées : " + ", ".join(LIBELLES_CHAMPS.get(c, c) for c in manquants),
                           {"entetes": tableau.entetes, "correspondance": correspondance})
    lignes = appliquer_correspondance(tableau, correspondance)
    if not lignes:
        raise ImportRefuse("FICHIER_VIDE", "Le fichier ne contient aucune ligne de données")

    deja = None
    with transaction(conn):
        deja = conn.execute("SELECT fichier, importe_le FROM imports WHERE empreinte = ?", (empreinte,)).fetchone()
        if deja is None:
            import_id = conn.execute(
                "INSERT INTO imports (type, fichier, empreinte, importe_le, importe_par, lignes_lues, lignes_acceptees,"
                " lignes_rejetees, lignes_avertissement) VALUES (?,?,?,?,?,?,0,0,0)",
                (type_import, nom_fichier, empreinte, _maintenant(), auteur, len(lignes)),
            ).lastrowid
            anomalies, acceptees, avertissements = _TRAITEMENTS[type_import](conn, import_id, lignes, auteur)
            rejetees = len({a.ligne for a in anomalies if a.gravite == "rejet"})
            conn.execute("UPDATE imports SET lignes_acceptees=?, lignes_rejetees=?, lignes_avertissement=? WHERE id=?",
                         (acceptees, rejetees, avertissements, import_id))
            conn.executemany(
                "INSERT INTO import_anomalies (import_id, ligne, gravite, code, message, donnees) VALUES (?,?,?,?,?,?)",
                [(import_id, a.ligne, a.gravite, a.code, a.message, json.dumps(a.donnees, ensure_ascii=False))
                 for a in anomalies],
            )
            journal.ajouter(conn, acteur=auteur, type_acteur="humain", action="import_fichier", objet_type="import",
                            objet_id=import_id,
                            apres={"type": type_import, "fichier": nom_fichier, "empreinte": empreinte,
                                   "lues": len(lignes), "acceptees": acceptees, "avertissements": avertissements,
                                   "rejetees": rejetees},
                            regle="IMPORT")
    if deja is not None:
        with transaction(conn):
            journal.ajouter(conn, acteur=auteur, type_acteur="humain", action="import_refuse", objet_type="import",
                            apres={"fichier": nom_fichier, "empreinte": empreinte, "deja_importe_sous": deja["fichier"]},
                            regle="FICHIER_DEJA_IMPORTE")
        raise ImportRefuse("FICHIER_DEJA_IMPORTE",
                           f"Ce fichier a déjà été importé le {deja['importe_le'][:10]} (sous le nom « {deja['fichier']} »)")

    return RapportImport(import_id, type_import, nom_fichier, empreinte, tableau.format, tableau.encodage,
                         tableau.separateur, correspondance, len(lignes), acceptees, avertissements, rejetees,
                         sorted(anomalies, key=lambda a: (a.ligne, a.gravite)))


def rapport(conn: sqlite3.Connection, import_id: int) -> dict | None:
    ligne = conn.execute("SELECT * FROM imports WHERE id = ?", (import_id,)).fetchone()
    if ligne is None:
        return None
    anomalies = [dict(a) | {"donnees": json.loads(a["donnees"])} for a in
                 conn.execute("SELECT * FROM import_anomalies WHERE import_id = ? ORDER BY ligne, id", (import_id,))]
    return dict(ligne) | {"anomalies": anomalies}


def exporter_rejets_csv(conn: sqlite3.Connection, import_id: int) -> bytes:
    """Fichier des lignes rejetées avec leur motif, à corriger puis réimporter (UTF-8 avec BOM pour Excel)."""
    anomalies = conn.execute(
        "SELECT ligne, code, message, donnees FROM import_anomalies WHERE import_id = ? AND gravite = 'rejet'"
        " ORDER BY ligne", (import_id,)).fetchall()
    tampon = io.StringIO()
    ecrivain = csv.writer(tampon, delimiter=";", lineterminator="\r\n")
    colonnes: list[str] = []
    for a in anomalies:
        for c in json.loads(a["donnees"]):
            if c not in colonnes:
                colonnes.append(c)
    ecrivain.writerow(["ligne", "code_rejet", "motif", *colonnes])
    for a in anomalies:
        donnees = json.loads(a["donnees"])
        ecrivain.writerow([a["ligne"], a["code"], a["message"], *(donnees.get(c, "") for c in colonnes)])
    return tampon.getvalue().encode("utf-8-sig")
