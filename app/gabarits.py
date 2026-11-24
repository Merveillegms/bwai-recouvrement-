"""Gabarits de messages de relance : un par étape et par canal, en français, au vouvoiement,
avec une légère touche béninoise (formules de politesse chaleureuses, sans familiarité).

Toutes les valeurs (montants, dates, références, numéros) sont insérées par le code à partir des
données calculées : le texte des gabarits ne contient aucun chiffre métier.
Règles de ton : politesse, aucune menace, aucune mention de tiers (docs/regles_metier.md § 9).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.montants import formater
from app.references import formater_reference

ETAPES_MESSAGE = ("R0", "R1", "R2", "R3", "R4")
# Au-delà, le message part en validation humaine (SMS : 4 segments de 160 caractères au plus).
LONGUEUR_MAX = {"sms": 640, "whatsapp": 1500, "email": 5000}

# Vocabulaire interdit dans tout message client (menace, intimidation, mention de tiers).
MOTS_INTERDITS = (
    "huissier", "police", "prison", "tribunal", "plainte", "poursuite", "menace", "saisie", "gendarmerie",
    "voisin", "votre famille", "employeur", "réseaux sociaux", "honte", "liste noire",
)

_OUVERTURE = {
    "R0": "Bonjour {client}, nous espérons que vous allez bien et que les affaires se portent bien.",
    "R1": "Bonjour {client}, nous espérons que vous allez bien et que les affaires se portent bien.",
    "R2": "Bonjour {client}, nous espérons que vous vous portez bien.",
    "R3": "Bonjour {client},",
    "R4": "À l'attention de {client}.\nMadame, Monsieur,",
}
_OUVERTURE_SMS = {
    "R0": "Bonjour {client}, nous espérons que vous allez bien.",
    "R1": "Bonjour {client}, nous espérons que vous allez bien.",
    "R2": "Bonjour {client},",
    "R3": "Bonjour {client},",
    "R4": "{client}, Madame, Monsieur,",
}

# (une facture, plusieurs factures)
_CORPS = {
    "R0": ("Pour vous faciliter l'organisation, nous vous rappelons l'échéance prochaine de la facture suivante :",
           "Pour vous faciliter l'organisation, nous vous rappelons l'échéance prochaine des factures suivantes :"),
    "R1": ("Sauf erreur de notre part, la facture suivante est arrivée à échéance et reste à régler :",
           "Sauf erreur de notre part, les factures suivantes sont arrivées à échéance et restent à régler :"),
    "R2": ("Nous revenons vers vous au sujet de la facture suivante, toujours en attente de règlement malgré "
           "notre premier rappel :",
           "Nous revenons vers vous au sujet des factures suivantes, toujours en attente de règlement malgré "
           "notre premier rappel :"),
    "R3": ("Malgré nos précédents rappels, la facture suivante n'a pas encore été réglée. Nous vous remercions de "
           "bien vouloir procéder au paiement dans les meilleurs délais. Sans règlement de votre part, nous serions "
           "amenés à suspendre les prochaines livraisons à crédit :",
           "Malgré nos précédents rappels, les factures suivantes n'ont pas encore été réglées. Nous vous remercions "
           "de bien vouloir procéder au paiement dans les meilleurs délais. Sans règlement de votre part, nous "
           "serions amenés à suspendre les prochaines livraisons à crédit :"),
    "R4": ("Ceci est notre dernier avis amiable concernant la facture ci-dessous. Si vous rencontrez une difficulté "
           "passagère, nous vous proposons de convenir ensemble d'un échéancier : il vous suffit de nous appeler. "
           "À défaut, votre dossier sera transmis à notre responsable du recouvrement pour un examen personnalisé :",
           "Ceci est notre dernier avis amiable concernant les factures ci-dessous. Si vous rencontrez une "
           "difficulté passagère, nous vous proposons de convenir ensemble d'un échéancier : il vous suffit de nous "
           "appeler. À défaut, votre dossier sera transmis à notre responsable du recouvrement pour un examen "
           "personnalisé :"),
}
_CORPS_SMS = {
    "R0": ("Petit rappel, échéance prochaine :", "Petit rappel, échéances prochaines :"),
    "R1": ("Sauf erreur, cette facture est échue :", "Sauf erreur, ces factures sont échues :"),
    "R2": ("2e rappel, facture toujours en attente :", "2e rappel, factures toujours en attente :"),
    "R3": ("Malgré nos rappels, cette facture reste impayée. Merci de régler rapidement pour éviter la "
           "suspension des livraisons à crédit :",
           "Malgré nos rappels, ces factures restent impayées. Merci de régler rapidement pour éviter la "
           "suspension des livraisons à crédit :"),
    "R4": ("Dernier avis amiable. En cas de difficulté, appelez-nous pour convenir d'un échéancier :",
           "Dernier avis amiable. En cas de difficulté, appelez-nous pour convenir d'un échéancier :"),
}

# Lot dont les factures sont à des étapes différentes : on n'affirme pas « malgré nos rappels » pour une
# facture jamais relancée. Formulation neutre, complétée selon l'étape la plus avancée du lot.
_CORPS_MIXTE = "Sauf erreur de notre part, les factures suivantes restent à régler{suite} :"
_SUITE_MIXTE = {
    "R0": "", "R1": "", "R2": "",
    "R3": ". Nous vous remercions de bien vouloir procéder au paiement dans les meilleurs délais",
    "R4": (". Nous vous remercions de bien vouloir procéder au paiement dans les meilleurs délais. En cas de "
           "difficulté passagère, nous vous proposons de convenir ensemble d'un échéancier"),
}
_CORPS_MIXTE_SMS = "Sauf erreur, ces factures restent à régler{suite} :"
_SUITE_MIXTE_SMS = {"R0": "", "R1": "", "R2": "", "R3": ". Merci de régler rapidement",
                    "R4": ". En cas de difficulté, appelez-nous pour un échéancier"}

_CLOTURE = {
    "R0": "Merci pour votre confiance et bonne journée à vous.",
    "R1": "Si le paiement a déjà été effectué, merci de ne pas tenir compte de ce message. "
          "Merci pour votre confiance et bonne journée à vous.",
    "R2": "Si le paiement a déjà été effectué, merci de ne pas tenir compte de ce message. "
          "Nous restons à votre écoute pour toute question. Bonne journée à vous.",
    "R3": "Si le paiement a déjà été effectué, merci de ne pas tenir compte de ce message. "
          "Nous restons disponibles pour en parler. Merci pour votre compréhension.",
    "R4": "Nous comptons sur votre diligence et restons disponibles pour trouver ensemble une solution. "
          "Veuillez agréer, Madame, Monsieur, nos salutations distinguées.",
}
_CLOTURE_SMS = {
    "R0": "Merci et bonne journée à vous.",
    "R1": "Si vous avez déjà réglé, merci d'ignorer ce message. Bonne journée à vous.",
    "R2": "Si vous avez déjà réglé, merci d'ignorer ce message. Bonne journée à vous.",
    "R3": "Si vous avez déjà réglé, merci d'ignorer ce message.",
    "R4": "Nous vous remercions de votre compréhension.",
}

_OBJETS_EMAIL = {
    "R0": "Rappel amical : échéance prochaine ({objet})",
    "R1": "Rappel de règlement ({objet})",
    "R2": "Deuxième rappel de règlement ({objet})",
    "R3": "Relance : règlement en attente ({objet})",
    "R4": "Dernier avis amiable ({objet})",
}


@dataclass(frozen=True)
class LigneFacture:
    numero: str
    date_emission: str
    date_echeance: str
    jours_retard: int
    solde: int
    devise: str
    decimales: int
    reference: str


@dataclass(frozen=True)
class Message:
    canal: str
    objet: str | None  # e-mail uniquement
    texte: str


def _date(iso: str) -> str:
    return date.fromisoformat(iso).strftime("%d/%m/%Y")


def _total(lignes: list[LigneFacture]) -> str:
    """Total par devise (« 1 250 000 FCFA et 1 250,50 EUR ») : on n'additionne jamais deux devises."""
    totaux: dict[str, list] = {}
    for l in lignes:
        totaux.setdefault(l.devise, [0, l.decimales])[0] += l.solde
    return " et ".join(formater(montant, devise, decimales) for devise, (montant, decimales) in sorted(totaux.items()))


def _ligne(l: LigneFacture, canal: str) -> str:
    solde = formater(l.solde, l.devise, l.decimales)
    ref = formater_reference(l.reference)
    if canal == "sms":
        return f"- {l.numero} : {solde}, réf. {ref}"
    retard = f", {l.jours_retard} j de retard" if l.jours_retard > 0 else ""
    return (f"- Facture {l.numero} du {_date(l.date_emission)}, échéance {_date(l.date_echeance)}{retard} : "
            f"reste à payer {solde} (référence {ref})")


def _bloc_paiement(entreprise: dict, plusieurs: bool, canal: str) -> str:
    operateurs = entreprise["mobile_money"]
    if canal == "sms":
        momo = " ou ".join(f"{o['operateur']} {o['numero']}" for o in operateurs)
        return f"Paiement : {momo}, en indiquant la référence."
    momo = "\n".join(f"  {o['operateur']} : {o['numero']}" for o in operateurs)
    consigne = "la référence de chaque facture" if plusieurs else "la référence ci-dessus"
    return (f"Pour régler par mobile money, envoyez le montant à l'un de nos numéros marchands :\n{momo}\n"
            f"en indiquant {consigne} dans le motif du paiement. Une fiche de paiement peut vous être remise "
            "sur demande.")


def rendre(etape: str, canal: str, client: str, lignes: list[LigneFacture], entreprise: dict,
           etapes_mixtes: bool = False) -> Message:
    """`etape` : étape la plus avancée du lot (elle fixe le ton). `etapes_mixtes` : les factures du lot ne sont
    pas toutes à la même étape ; le corps du message reste alors exact pour chacune."""
    if etape not in ETAPES_MESSAGE:
        raise ValueError(f"Pas de message client pour l'étape {etape}")
    if not lignes:
        raise ValueError("Aucune facture à relancer")
    plusieurs = len(lignes) > 1
    mixte = etapes_mixtes and plusieurs
    total = f"Total à régler : {_total(lignes)}." if plusieurs else ""
    liste = "\n".join(_ligne(l, canal) for l in lignes)
    if canal == "sms":
        corps = (_CORPS_MIXTE_SMS.format(suite=_SUITE_MIXTE_SMS[etape]) if mixte
                 else _CORPS_SMS[etape][plusieurs])
        morceaux = [_OUVERTURE_SMS[etape].format(client=client), corps, liste, total,
                    _bloc_paiement(entreprise, plusieurs, canal), _CLOTURE_SMS[etape],
                    f"{entreprise['nom']} {entreprise['telephone']}"]
        return Message(canal, None, "\n".join(m for m in morceaux if m))
    corps = _CORPS_MIXTE.format(suite=_SUITE_MIXTE[etape]) if mixte else _CORPS[etape][plusieurs]
    morceaux = [_OUVERTURE[etape].format(client=client), corps, liste, total,
                _bloc_paiement(entreprise, plusieurs, canal), _CLOTURE[etape],
                f"Le service recouvrement\n{entreprise['nom']}, {entreprise['ville']}\n"
                f"{entreprise['telephone']} - {entreprise['email']}"]
    objet = None
    if canal == "email":
        objet = _OBJETS_EMAIL[etape].format(objet=f"{len(lignes)} factures" if plusieurs
                                            else f"facture {lignes[0].numero}")
    return Message(canal, objet, "\n\n".join(m for m in morceaux if m))


def elements(canal: str, client: str, lignes: list[LigneFacture], entreprise: dict) -> dict[str, str]:
    """Parties du message qui portent des valeurs : toujours produites par le code, jamais par l'IA.
    Elles remplacent les marqueurs [[CLIENT]], [[FACTURES]], [[TOTAL]], [[PAIEMENT]], [[SIGNATURE]]."""
    plusieurs = len(lignes) > 1
    signature = (f"{entreprise['nom']} {entreprise['telephone']}" if canal == "sms" else
                 f"Le service recouvrement\n{entreprise['nom']}, {entreprise['ville']}\n"
                 f"{entreprise['telephone']} - {entreprise['email']}")
    parties = {"CLIENT": client, "FACTURES": "\n".join(_ligne(l, canal) for l in lignes),
               "PAIEMENT": _bloc_paiement(entreprise, plusieurs, canal), "SIGNATURE": signature}
    if plusieurs:
        parties["TOTAL"] = f"Total à régler : {_total(lignes)}."
    return parties


def controler_ton(texte: str) -> list[str]:
    """Écarts aux règles de ton (liste vide = conforme)."""
    bas = texte.lower()
    ecarts = [f"mot interdit : « {m} »" for m in MOTS_INTERDITS if m in bas]
    mots = set(bas.replace(",", " ").replace(".", " ").replace("'", " ").split())
    if mots & {"tu", "toi", "ton", "ta", "tes"}:
        ecarts.append("tutoiement")
    return ecarts
