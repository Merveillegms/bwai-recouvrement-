"""Générateur du jeu de données piégé (graine fixe, résultat identique à chaque exécution).

Produit des fichiers « sales » comme ceux d'un vrai gestionnaire (formats variés, encodages,
doublons, erreurs de saisie) et un fichier `attendus.json` qui décrit, ligne par ligne, ce que
le système doit obtenir.

Les valeurs attendues sont fixées PAR CONSTRUCTION (on choisit le retard, puis on en déduit
l'échéance ; on choisit les paiements, puis on en déduit le solde). Elles ne sont jamais
calculées par le moteur : c'est un oracle indépendant contre lequel le moteur est testé.
Les règles appliquées sont décrites dans docs/regles_metier.md.
"""
from __future__ import annotations

import csv
import io
import json
import random
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from app.references import generer_reference

GRAINE = 20261124
DATE_REFERENCE = date(2026, 12, 15)
SEUILS_GROS_MONTANT = {"XOF": Decimal(1_000_000), "XAF": Decimal(1_000_000), "EUR": Decimal(1_500)}

LOT1 = "factures_lot1.csv"
LOT2 = "factures_lot2.csv"
FICHIER_CLIENTS = "clients.csv"
FICHIER_PAIEMENTS = "paiements_mobile_money.csv"

ENTETE_CLIENTS = ["code_client", "nom", "telephone", "email", "canal_prefere", "langue", "sensible", "notes"]
ENTETE_FACTURES = ["numero_facture", "code_client", "date_emission", "date_echeance", "montant_ttc", "devise", "litige"]
# Le lot 2 vient d'un autre logiciel : autres noms de colonnes, virgule, encodage Windows-1252.
ENTETE_FACTURES_LOT2 = ["N° facture", "Client", "Date facture", "Échéance", "Montant TTC", "Devise", "Litige"]
ENTETE_PAIEMENTS = ["id_transaction", "date", "montant", "devise", "reference", "telephone_payeur", "operateur"]

OPERATEURS = ("MTN MoMo", "Moov Money", "Celtiis Cash")  # opérateurs mobile money au Bénin


@dataclass(frozen=True)
class Client:
    code: str
    nom: str
    telephone: str
    email: str
    canal: str
    sensible: bool
    profil: str
    montant_base: int  # ordre de grandeur des factures du client


# Données entièrement fictives (numéros dans une plage factice, domaines .example).
CLIENTS = (
    Client("C001", "Boulangerie Les Délices", "+229 0190000001", "contact@delices.example", "whatsapp", False, "bon_payeur", 120_000),
    Client("C002", "Pharmacie du Plateau", "+229 0190000002", "compta@pharmaplateau.example", "email", False, "bon_payeur", 350_000),
    Client("C003", "Quincaillerie Moderne", "+229 0190000003", "", "sms", False, "retardataire", 200_000),
    Client("C004", "Maquis Chez Awa", "+229 0190000004", "", "whatsapp", False, "retardataire", 90_000),
    Client("C005", "Transports Adjovi", "+229 0190000005", "gestion@transadjovi.example", "sms", False, "normal", 450_000),
    Client("C006", "École Les Petits Génies", "+229 0190000006", "direction@petitsgenies.example", "email", True, "sensible", 300_000),
    Client("C007", "Clinique Saint-Luc", "+229 0190000007", "admin@clinique-stluc.example", "email", True, "sensible", 600_000),
    Client("C008", "Garage Auto Plus", "+229 0190000008", "", "whatsapp", False, "normal", 150_000),
    Client("C009", "Imprimerie Rapide", "", "", "sms", False, "sans_contact", 80_000),
    Client("C010", "Supermarché Bon Prix", "+229 0190000010", "achats@bonprix.example", "email", False, "gros_client", 4_000_000),
    Client("C011", "Cabinet Houngbo Conseil", "+229 0190000011", "cabinet@houngbo.example", "email", False, "normal", 250_000),
    Client("C012", "Salon Beauté Divine", "+229 0190000012", "", "whatsapp", False, "normal", 45_000),
    Client("C013", "Ferme Avicole du Nord", "+229 0190000013", "", "sms", False, "retardataire", 180_000),
    Client("C014", "Librairie Savoir", "+229 0190000014", "librairie@savoir.example", "email", False, "bon_payeur", 60_000),
    Client("C015", "Hôtel Lagune de Cotonou", "+229 0190000015", "reception@hotel-lagune.example", "email", False, "normal", 500_000),
)
PAR_CODE = {c.code: c for c in CLIENTS}


def tranche(jours_retard: int) -> str:
    if jours_retard <= 0:
        return "non_echue"
    for borne, nom in ((15, "1-15"), (30, "16-30"), (60, "31-60"), (90, "61-90")):
        if jours_retard <= borne:
            return nom
    return "plus_90"


def _fr(d: date) -> str:
    return d.strftime("%d/%m/%Y")


def _milliers(montant: int) -> str:
    return f"{montant:,}".replace(",", " ")


@dataclass
class Facture:
    fichier: str
    numero: str
    client: str
    emission: date
    echeance: date
    montant: Decimal
    devise: str
    litige: bool
    cas: str
    issue: str  # acceptee | avertissement | rejetee
    codes: list[str]
    a_verifier: bool
    ligne_brute: dict[str, str]
    ligne: int = 0


@dataclass
class Paiement:
    id_transaction: str
    date_paiement: date
    montant: Decimal
    reference: str
    telephone: str
    operateur: str
    cas: str
    issue: str  # rapproche_auto | a_valider | rejete
    codes: list[str]
    facture: Facture | None  # facture concernée (rapprochement auto ou proposition)
    ligne: int = 0


@dataclass
class Generateur:
    graine: int = GRAINE
    factures: list[Facture] = field(default_factory=list)
    paiements: list[Paiement] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.rng = random.Random(self.graine)
        self._compteurs: dict[int, int] = defaultdict(int)
        self._montants_pris: set[tuple[str, Decimal]] = set()
        self._paye: dict[tuple[str, str], Decimal] = defaultdict(Decimal)
        self._tx = 40_000_000

    # ------------------------------------------------------------------ outils
    def _numero(self, annee: int) -> str:
        self._compteurs[annee] += 1
        return f"FAC-{annee}-{self._compteurs[annee]:04d}"

    def _montant(self, client: str) -> Decimal:
        """Montant au millier, entre 0,5 et 1,5 fois la base du client, unique pour ce client
        (deux factures d'un même client n'ont jamais le même montant par hasard : seuls les
        quasi-doublons et le cas ambigu le font volontairement)."""
        base = PAR_CODE[client].montant_base
        while True:
            m = Decimal(self.rng.randrange(base // 2000, base * 3 // 2000 + 1) * 1000)
            if (client, m) not in self._montants_pris:
                self._montants_pris.add((client, m))
                return m

    def facture(
        self,
        client: str,
        *,
        cas: str,
        retard: int | None = None,
        echeance: date | None = None,
        emission: date | None = None,
        montant: int | Decimal | None = None,
        devise: str = "XOF",
        litige: bool = False,
        fichier: str = LOT1,
        issue: str = "acceptee",
        codes: tuple[str, ...] = (),
        a_verifier: bool = False,
    ) -> Facture:
        if echeance is None:
            echeance = DATE_REFERENCE - timedelta(days=retard)
        if emission is None:
            emission = echeance - timedelta(days=30)
        if montant is None:
            montant = self._montant(client)
        else:
            montant = Decimal(montant)
            self._montants_pris.add((client, montant))
        numero = self._numero(emission.year)
        brute = {
            "numero_facture": numero,
            "code_client": client,
            "date_emission": emission.isoformat(),
            "date_echeance": echeance.isoformat(),
            "montant_ttc": str(montant),
            "devise": devise,
            "litige": "oui" if litige else "non",
        }
        f = Facture(fichier, numero, client, emission, echeance, montant, devise, litige, cas, issue,
                    list(codes), a_verifier, brute)
        self.factures.append(f)
        return f

    def copie(self, source: Facture, *, cas: str, issue: str, codes: tuple[str, ...],
              fichier: str = LOT1, **modifs: str) -> Facture:
        """Ligne copiée d'une facture existante (doublons), éventuellement modifiée."""
        brute = dict(source.ligne_brute) | modifs
        f = Facture(fichier, source.numero, source.client, source.emission, source.echeance,
                    Decimal(brute["montant_ttc"]), source.devise, source.litige, cas, issue,
                    list(codes), False, brute)
        self.factures.append(f)
        return f

    def _id_transaction(self) -> str:
        self._tx += self.rng.randrange(1, 997)
        return f"MP{self._tx:010d}"

    def paiement(
        self,
        facture: Facture | None,
        montant: int | Decimal,
        date_paiement: date,
        *,
        cas: str,
        reference: str | None = "auto",
        telephone: str | None = None,
        issue: str = "rapproche_auto",
        codes: tuple[str, ...] = (),
    ) -> Paiement:
        assert date_paiement <= DATE_REFERENCE, cas
        montant = Decimal(montant)
        if reference == "auto":
            reference = generer_reference(facture.client, facture.numero)
        if telephone is None:
            telephone = PAR_CODE[facture.client].telephone if facture else "+229 0199999999"
        p = Paiement(self._id_transaction(), date_paiement, montant, reference or "", telephone,
                     self.rng.choice(OPERATEURS), cas, issue, list(codes), facture)
        if issue == "rapproche_auto":
            self._paye[(facture.client, facture.numero)] += montant
        self.paiements.append(p)
        return p

    def doublon_paiement(self, source: Paiement) -> Paiement:
        p = Paiement(source.id_transaction, source.date_paiement, source.montant, source.reference,
                     source.telephone, source.operateur, "paiement_en_double", "rejete",
                     ["DOUBLON_PAIEMENT"], source.facture)
        self.paiements.append(p)
        return p

    # ------------------------------------------------------------ construction
    def construire(self) -> None:
        rng = self.rng
        f = self.facture

        # 1. Factures à échoir, dont l'échéance tombant le jour même (retard 0 = pas encore échue).
        for client, jours in (("C001", -3), ("C002", -10), ("C005", -30), ("C011", -45)):
            f(client, retard=jours, cas="a_echoir")
        f("C008", retard=0, cas="echeance_aujourd_hui")

        # 2. Factures échues aux bornes exactes des tranches d'ancienneté.
        echues = {}
        for retard, client in ((1, "C001"), (7, "C002"), (15, "C005"), (16, "C008"), (30, "C011"),
                               (31, "C012"), (60, "C015"), (61, "C003"), (90, "C004"), (91, "C013"),
                               (120, "C005")):
            echues[retard] = f(client, retard=retard, cas=f"echue_{retard}j")

        # 3. Historique : bons payeurs réglant à l'échéance, retardataires réglant tard.
        for client in ("C001", "C002", "C014", "C014", "C014"):
            x = f(client, retard=rng.randint(40, 200), cas="payee_a_temps")
            self.paiement(x, x.montant, x.echeance - timedelta(days=rng.randint(0, 5)), cas="paiement_total")
        for client in ("C003", "C003", "C003", "C004", "C004", "C013", "C013"):
            x = f(client, retard=rng.randint(100, 250), cas="payee_en_retard")
            self.paiement(x, x.montant, x.echeance + timedelta(days=rng.randint(20, 60)), cas="paiement_total_tardif")

        # 4. Paiements partiels, payée en deux fois, trop-perçu.
        partielles = []
        for client in ("C005", "C008", "C012", "C015"):
            x = f(client, retard=rng.randint(10, 70), cas="partiellement_payee")
            part = int(x.montant) * rng.choice((30, 50, 70)) // 100 // 1000 * 1000
            partielles.append(self.paiement(x, part, x.echeance + timedelta(days=2), cas="paiement_partiel"))
        x = f("C011", retard=-10, cas="partiellement_payee_non_echue")
        self.paiement(x, int(x.montant) * 40 // 100 // 1000 * 1000, DATE_REFERENCE - timedelta(days=3),
                      cas="paiement_partiel_anticipe")
        x = f("C001", retard=20, cas="payee_en_deux_fois")
        moitie = int(x.montant) // 2000 * 1000
        self.paiement(x, moitie, x.echeance + timedelta(days=1), cas="paiement_1_sur_2")
        self.paiement(x, x.montant - moitie, x.echeance + timedelta(days=8), cas="paiement_2_sur_2")
        x = f("C002", retard=25, cas="trop_percu")
        self.paiement(x, x.montant + 5000, x.echeance + timedelta(days=3), cas="paiement_trop_percu")

        # 5. Litiges (jamais relancés automatiquement), dont un partiellement payé.
        f("C005", retard=45, litige=True, cas="litige")
        f("C015", retard=20, litige=True, cas="litige")
        x = f("C008", retard=35, litige=True, cas="litige_partiellement_payee")
        self.paiement(x, int(x.montant) * 30 // 100 // 1000 * 1000, x.echeance + timedelta(days=5),
                      cas="paiement_partiel")

        # 6. Montants extrêmes.
        f("C012", retard=12, montant=500, cas="montant_tres_petit")
        for _ in range(3):
            f("C010", retard=rng.randint(5, 80), cas="gros_montant")
        f("C010", retard=40, montant=15_000_000, cas="gros_montant_extreme")
        f("C014", retard=18, montant=4_800_000, cas="montant_aberrant", issue="avertissement",
          codes=("MONTANT_ABERRANT",), a_verifier=True)

        # 7. Clients particuliers.
        f("C009", retard=20, cas="client_sans_contact")
        f("C009", retard=50, cas="client_sans_contact")
        f("C006", retard=8, cas="client_sensible")
        f("C007", retard=33, cas="client_sensible")
        f("C999", retard=14, montant=175_000, cas="client_inconnu", issue="avertissement",
          codes=("CLIENT_INCONNU",), a_verifier=True)

        # 8. Dates piégées (retard en jours calendaires).
        f("C011", echeance=date(2026, 11, 30), emission=date(2026, 10, 31), cas="fin_de_mois")
        f("C012", echeance=date(2026, 2, 28), emission=date(2026, 1, 31), cas="fin_fevrier")
        f("C015", echeance=date(2026, 1, 14), emission=date(2025, 12, 15), cas="changement_annee")
        f("C003", echeance=date(2025, 12, 31), emission=date(2025, 12, 1), cas="echeance_31_decembre")
        f("C001", echeance=date(2026, 12, 25), emission=date(2026, 11, 25), cas="echeance_jour_ferie_future")
        f("C002", echeance=date(2026, 11, 1), emission=date(2026, 10, 2), cas="echeance_jour_ferie_passee")
        f("C013", echeance=date(2026, 10, 1), emission=date(2026, 10, 5), cas="echeance_avant_emission",
          issue="avertissement", codes=("ECHEANCE_AVANT_EMISSION",), a_verifier=True)

        # 9. Formats variés, acceptés après normalisation.
        for client in ("C004", "C013"):
            x = f(client, retard=rng.randint(5, 40), cas="dates_format_fr")
            x.ligne_brute |= {"date_emission": _fr(x.emission), "date_echeance": _fr(x.echeance)}
        x = f("C005", retard=11, cas="montant_avec_espaces")
        x.ligne_brute["montant_ttc"] = _milliers(int(x.montant))
        x = f("C008", retard=26, cas="espaces_parasites")
        x.ligne_brute |= {"code_client": "  C008 ", "numero_facture": f" {x.numero}  "}
        x = f("C015", retard=38, cas="montant_decimales_nulles")
        x.ligne_brute["montant_ttc"] = f"{int(x.montant)}.00"
        x = f("C011", retard=20, montant=Decimal("1250.50"), devise="EUR", cas="devise_eur_virgule")
        x.ligne_brute["montant_ttc"] = "1250,50"

        # 10. Lignes à rejeter, avec le motif attendu.
        rejets = (
            ("date_emission", "", "CHAMP_MANQUANT"),
            ("date_echeance", "", "CHAMP_MANQUANT"),
            ("montant_ttc", "", "CHAMP_MANQUANT"),
            ("devise", "", "CHAMP_MANQUANT"),
            ("code_client", "", "CHAMP_MANQUANT"),
            ("numero_facture", "", "CHAMP_MANQUANT"),
            ("montant_ttc", "-45000", "MONTANT_NEGATIF"),
            ("montant_ttc", "0", "MONTANT_NUL"),
            ("montant_ttc", "12a00", "MONTANT_INVALIDE"),
            ("montant_ttc", "150000,50", "DECIMALES_INVALIDES"),
            ("devise", "XYZ", "DEVISE_INCONNUE"),
            ("date_echeance", "2026-13-45", "DATE_INVALIDE"),
            ("date_emission", "31/02/2026", "DATE_INVALIDE"),
        )
        for colonne, valeur, code in rejets:
            client = rng.choice(("C001", "C005", "C008", "C011", "C015"))
            x = f(client, retard=rng.randint(5, 60), cas=f"rejet_{code.lower()}", issue="rejetee", codes=(code,))
            x.ligne_brute[colonne] = valeur

        # 11. Volume : factures ordinaires, dont certaines réglées.
        ordinaires = ("C001", "C002", "C003", "C004", "C005", "C006", "C007", "C008",
                      "C011", "C012", "C013", "C014", "C015")
        volume = []
        for _ in range(45):
            x = f(rng.choice(ordinaires), retard=rng.randint(-20, 150), cas="volume")
            volume.append(x)
        regles = [x for x in volume if (DATE_REFERENCE - x.echeance).days > 5]
        for x in rng.sample(regles, 8):
            retard = (DATE_REFERENCE - x.echeance).days
            x.cas = "volume_payee"
            self.paiement(x, x.montant, x.echeance + timedelta(days=rng.randint(-5, retard - 1)), cas="paiement_total")
        ouvertes = [x for x in volume if x.cas == "volume" and (DATE_REFERENCE - x.echeance).days > 0]

        # 12. Doublons dans le même fichier (placés plus loin, comme dans la vraie vie).
        original = f("C011", retard=22, cas="original_doublon_exact")
        conflit = f("C012", retard=27, cas="original_conflit_numero")
        q1 = f("C015", retard=19, cas="original_quasi_doublon")
        f("C015", emission=q1.emission + timedelta(days=2), echeance=q1.echeance + timedelta(days=2),
          montant=q1.montant, cas="quasi_doublon", issue="avertissement", codes=("QUASI_DOUBLON",), a_verifier=True)
        # Deux factures ouvertes de même montant, émises à 30 jours d'écart (pas un quasi-doublon) :
        # un paiement sans référence de ce montant est ambigu.
        amb1 = f("C013", retard=40, montant=72_000, cas="montant_identique_ambigu")
        f("C013", retard=70, montant=72_000, cas="montant_identique_ambigu")
        self.copie(original, cas="doublon_exact", issue="rejetee", codes=("DOUBLON_EXACT",))
        self.copie(conflit, cas="conflit_numero", issue="rejetee", codes=("CONFLIT_NUMERO",),
                   montant_ttc=str(conflit.montant + 10_000))

        # 13. Lot 2 : export d'un autre logiciel, importé après le lot 1.
        for x in rng.sample(ouvertes, 3):
            self.copie(x, cas="deja_importee", issue="rejetee", codes=("DOUBLON_IMPORT",), fichier=LOT2)
        cible = rng.choice([x for x in ouvertes])
        self.copie(cible, cas="conflit_numero_inter_fichiers", issue="rejetee", codes=("CONFLIT_NUMERO",),
                   fichier=LOT2, montant_ttc=str(cible.montant + 25_000))
        for _ in range(6):
            f(rng.choice(ordinaires), retard=rng.randint(1, 60), cas="lot2_nouvelle", fichier=LOT2)

        # 14. Paiements piégés.
        self.doublon_paiement(partielles[0])
        self.paiement(None, 95_000, DATE_REFERENCE - timedelta(days=4), cas="reference_inconnue",
                      reference=generer_reference("C000", "FAC-0000-0000"), issue="a_valider",
                      codes=("REFERENCE_INCONNUE",))
        vraie = generer_reference(echues[30].client, echues[30].numero)
        fausse = vraie[:5] + str((int(vraie[5]) + 1) % 10) + vraie[6:]  # un chiffre tapé de travers
        self.paiement(echues[30], echues[30].montant, DATE_REFERENCE - timedelta(days=2),
                      cas="reference_mal_saisie", reference=fausse, issue="a_valider",
                      codes=("REFERENCE_INVALIDE",))
        self.paiement(echues[7], echues[7].montant, DATE_REFERENCE - timedelta(days=1),
                      cas="sans_reference_proposition", reference="", issue="a_valider",
                      codes=("PROPOSITION_MONTANT_CLIENT",))
        self.paiement(None, 72_000, DATE_REFERENCE - timedelta(days=1), cas="sans_reference_ambigu",
                      reference="", telephone=PAR_CODE["C013"].telephone, issue="a_valider",
                      codes=("RAPPROCHEMENT_AMBIGU",))
        x = rng.choice([v for v in ouvertes if v not in (amb1,)])
        x.cas = "volume_payee_reference_saisie_libre"
        ref = generer_reference(x.client, x.numero)
        libre = f"{ref[:2].lower()} {ref[2:6]}-{ref[6:]}"  # « rc 1234-56789 »
        self.paiement(x, x.montant, DATE_REFERENCE - timedelta(days=1), cas="reference_saisie_libre", reference=libre)

    # -------------------------------------------------------------- attendus
    def _attendu_facture(self, x: Facture) -> dict:
        # Numéro et client tels qu'ils apparaissent dans le fichier (une ligne rejetée peut les avoir vides).
        attendu = {
            "fichier": x.fichier, "ligne": x.ligne, "cas": x.cas,
            "numero": x.ligne_brute["numero_facture"].strip(),
            "code_client": x.ligne_brute["code_client"].strip(), "issue": x.issue, "codes": x.codes,
        }
        if x.issue == "rejetee":
            return attendu
        paye = self._paye[(x.client, x.numero)]
        solde = max(x.montant - paye, Decimal(0))
        trop_percu = max(paye - x.montant, Decimal(0))
        retard = (DATE_REFERENCE - x.echeance).days
        if x.litige:
            statut = "en_litige"
        elif paye >= x.montant:
            statut = "payee"
        elif paye > 0:
            statut = "partiellement_payee"
        elif retard >= 1:
            statut = "echue"
        else:
            statut = "a_echoir"
        jours = 0 if statut == "payee" else max(retard, 0)
        client = PAR_CODE.get(x.client)
        drapeaux = []
        if x.a_verifier:
            drapeaux.append("a_verifier")
        if solde > 0 and solde >= SEUILS_GROS_MONTANT[x.devise]:
            drapeaux.append("gros_montant")
        if client is None or (not client.telephone and not client.email):
            drapeaux.append("sans_contact")
        if client is not None and client.sensible:
            drapeaux.append("client_sensible")
        attendu |= {
            "devise": x.devise,
            "montant_ttc": str(x.montant),
            "reference_paiement": generer_reference(x.client, x.numero),
            "statut": statut,
            "jours_retard": jours,
            "tranche": None if statut == "payee" else tranche(jours),
            "total_paye": str(paye),
            "solde": str(solde),
            "trop_percu": str(trop_percu),
            "drapeaux": drapeaux,
        }
        return attendu

    def _attendu_paiement(self, p: Paiement) -> dict:
        return {
            "fichier": FICHIER_PAIEMENTS, "ligne": p.ligne, "cas": p.cas, "id_transaction": p.id_transaction,
            "issue": p.issue, "codes": p.codes, "montant": str(p.montant),
            "facture": None if p.facture is None else {"numero": p.facture.numero, "code_client": p.facture.client},
        }

    # --------------------------------------------------------------- écriture
    def ecrire(self, dossier: Path) -> dict:
        dossier.mkdir(parents=True, exist_ok=True)

        # Clients (UTF-8 avec BOM, point-virgule), avec trois lignes piégées.
        lignes_clients = [
            [c.code, c.nom, c.telephone, c.email, c.canal, "fr", "oui" if c.sensible else "non", c.profil]
            for c in CLIENTS
        ]
        c5 = lignes_clients[4]
        lignes_clients += [
            list(c5),
            ["", "Boutique Sans Code", "+229 0190000020", "", "sms", "fr", "non", ""],
            ["C016", "Boutique Étoile", "+229 0190000016", "", "fax", "fr", "non", ""],
        ]
        attendus_clients = [
            {"ligne": i + 2, "code_client": c.code, "issue": "acceptee", "codes": []} for i, c in enumerate(CLIENTS)
        ] + [
            {"ligne": len(CLIENTS) + 2, "code_client": "C005", "issue": "rejetee", "codes": ["DOUBLON_EXACT"]},
            {"ligne": len(CLIENTS) + 3, "code_client": "", "issue": "rejetee", "codes": ["CHAMP_MANQUANT"]},
            {"ligne": len(CLIENTS) + 4, "code_client": "C016", "issue": "rejetee", "codes": ["CANAL_INVALIDE"]},
        ]
        _ecrire_csv(dossier / FICHIER_CLIENTS, ENTETE_CLIENTS, lignes_clients, ";", "utf-8-sig")

        for nom, entete, sep, encodage in ((LOT1, ENTETE_FACTURES, ";", "utf-8-sig"),
                                           (LOT2, ENTETE_FACTURES_LOT2, ",", "cp1252")):
            lot = [x for x in self.factures if x.fichier == nom]
            for i, x in enumerate(lot):
                x.ligne = i + 2
            lignes = [[x.ligne_brute[c] for c in ENTETE_FACTURES] for x in lot]
            _ecrire_csv(dossier / nom, entete, lignes, sep, encodage)

        for i, p in enumerate(self.paiements):
            p.ligne = i + 2
        lignes_p = [[p.id_transaction, p.date_paiement.isoformat(), str(p.montant), "XOF", p.reference,
                     p.telephone, p.operateur] for p in self.paiements]
        _ecrire_csv(dossier / FICHIER_PAIEMENTS, ENTETE_PAIEMENTS, lignes_p, ";", "utf-8")

        attendus = {
            "graine": self.graine,
            "date_reference": DATE_REFERENCE.isoformat(),
            "seuils_gros_montant": {k: str(v) for k, v in SEUILS_GROS_MONTANT.items()},
            "ordre_import": [FICHIER_CLIENTS, LOT1, LOT2, FICHIER_PAIEMENTS],
            "fichiers": {
                FICHIER_CLIENTS: {"encodage": "utf-8-sig", "separateur": ";"},
                LOT1: {"encodage": "utf-8-sig", "separateur": ";"},
                LOT2: {"encodage": "cp1252", "separateur": ",",
                       "correspondance_colonnes": dict(zip(ENTETE_FACTURES_LOT2, ENTETE_FACTURES))},
                FICHIER_PAIEMENTS: {"encodage": "utf-8", "separateur": ";"},
            },
            "clients": attendus_clients,
            "factures": [self._attendu_facture(x) for x in self.factures],
            "paiements": [self._attendu_paiement(p) for p in self.paiements],
        }
        (dossier / "attendus.json").write_text(
            json.dumps(attendus, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
        )
        return attendus


def _ecrire_csv(chemin: Path, entete: list[str], lignes: list[list[str]], sep: str, encodage: str) -> None:
    tampon = io.StringIO()
    ecrivain = csv.writer(tampon, delimiter=sep, lineterminator="\r\n")
    ecrivain.writerow(entete)
    ecrivain.writerows(lignes)
    chemin.write_bytes(tampon.getvalue().encode(encodage))


def generer(dossier: Path, graine: int = GRAINE) -> dict:
    g = Generateur(graine)
    g.construire()
    return g.ecrire(dossier)


if __name__ == "__main__":
    from app.config import DOSSIER_DEMO

    resultat = generer(DOSSIER_DEMO)
    print(f"Jeu de données écrit dans {DOSSIER_DEMO}")
    print(f"  {len(resultat['factures'])} lignes de factures, {len(resultat['paiements'])} paiements, "
          f"{len(resultat['clients'])} lignes clients")
