"""Mesure des gains : l'outil face à une référence « relance naïve », sur le même jeu de test piégé.

Référence (le gestionnaire décrit par le hackathon : relance à la main, sans priorité, parfois une facture
déjà réglée) : chaque ligne du fichier de factures dont l'échéance est passée est relancée, au montant TTC du
fichier, dans l'ordre du fichier, un message par facture, sans rapprochement des paiements mobile money.

Les ERREURS sont mesurées : elles se comptent sur les données, ligne par ligne, grâce à attendus.json.
Les TEMPS humains reposent sur des hypothèses écrites ci-dessous, à remplacer par un chronométrage réel
(protocole : docs/protocole_mesure.md). Les temps machine sont mesurés.

    python -m app.mesure_gains      écrit docs/mesure_gains.json et docs/mesure_gains.md
"""
from __future__ import annotations

import json
import tempfile
import time
from collections import Counter
from datetime import date
from decimal import Decimal
from pathlib import Path

from app import config, garde_fous, importer, lecture, parametres, priorisation, rapprochement, relances, seed
from app import etat as moteur
from app.db import connecter, migrer
from app.normalisation import ErreurValeur, lire_date

# Hypothèses de temps humain (minutes), à remplacer par une mesure réelle.
HYPOTHESES = {
    "manuel_par_relance": 3.0,     # retrouver la facture, consulter le relevé MoMo, rédiger, envoyer
    "outil_lancement": 2.0,        # importer les fichiers, préparer, envoyer (quelques clics)
    "outil_par_lot_a_valider": 0.5,  # lire un message préparé et l'approuver
}
# Le gestionnaire met à jour son suivi des paiements une fois par semaine : il ne connaît pas les
# paiements des 7 derniers jours (c'est là que naît la « facture déjà réglée » relancée).
DELAI_SUIVI_JOURS = 7
CAPACITE_UNE_HEURE = int(60 / HYPOTHESES["manuel_par_relance"])
REFERENCE = date(2026, 12, 15)
DOUBLONS = {"DOUBLON_EXACT", "CONFLIT_NUMERO", "DOUBLON_IMPORT"}


def _attendus() -> dict:
    return json.loads((config.DOSSIER_DEMO / "attendus.json").read_text(encoding="utf-8"))


def _paiements_par_facture(attendus: dict) -> dict[tuple[str, str], list[tuple[date, Decimal]]]:
    """Paiements réellement reçus (ceux que l'outil rapproche par référence), avec leur date."""
    import csv
    import io
    texte = (config.DOSSIER_DEMO / "paiements_mobile_money.csv").read_text(encoding="utf-8")
    dates = {l["id_transaction"]: date.fromisoformat(l["date"]) for l in csv.DictReader(io.StringIO(texte), delimiter=";")}
    resultat: dict[tuple[str, str], list] = {}
    for p in attendus["paiements"]:
        if p["issue"] == "rapproche_auto":
            cle = (p["facture"]["code_client"], p["facture"]["numero"])
            resultat.setdefault(cle, []).append((dates[p["id_transaction"]], Decimal(p["montant"])))
    return resultat


def reference_naive(attendus: dict) -> dict:
    paiements = _paiements_par_facture(attendus)
    limite_suivi = REFERENCE.toordinal() - DELAI_SUIVI_JOURS
    contenu = (config.DOSSIER_DEMO / "factures_lot1.csv").read_bytes()
    tableau = lecture.lire_tableau(contenu, "factures_lot1.csv")
    lignes = lecture.appliquer_correspondance(tableau, lecture.proposer_correspondance("factures", tableau.entetes))
    par_ligne = {x["ligne"]: x for x in attendus["factures"] if x["fichier"] == "factures_lot1.csv"}
    relancees, ignorees = [], 0
    for numero, v in lignes:
        try:
            echeance = lire_date(v["date_echeance"])
        except ErreurValeur:
            ignorees += 1  # ligne illisible écartée sans que personne ne soit prévenu
            continue
        if echeance >= REFERENCE:
            continue
        x = par_ligne[numero]
        if x["issue"] != "rejetee":
            connus = sum(m for d, m in paiements.get((x["code_client"], x["numero"]), []) if d.toordinal() <= limite_suivi)
            if connus >= Decimal(x["montant_ttc"]):
                continue  # paiement ancien, déjà reporté dans le suivi : le gestionnaire ne relance pas
            x = dict(x, connu_paye=str(connus))
        relancees.append((numero, v["code_client"].strip().upper(), x))
    erreurs = Counter()
    for _, _, x in relancees:
        if x["issue"] == "rejetee" and set(x["codes"]) & DOUBLONS:
            erreurs["doublons_relances"] += 1
        elif x["issue"] == "rejetee":
            erreurs["lignes_invalides_relancees"] += 1
        elif x["statut"] == "payee":
            erreurs["factures_payees_relancees"] += 1
        elif x["statut"] == "en_litige":
            erreurs["litiges_relances"] += 1
        else:
            if Decimal(x["total_paye"]) != Decimal(x.get("connu_paye", "0")):
                erreurs["montants_faux"] += 1  # un paiement récent ignoré : le montant réclamé est trop élevé
            if "a_verifier" in x["drapeaux"]:
                erreurs["donnees_douteuses_relancees"] += 1
            if "sans_contact" in x["drapeaux"]:
                erreurs["relances_impossibles"] += 1
    en_attente = {(q["facture"]["code_client"], q["facture"]["numero"]) for q in attendus["paiements"]
                  if q["issue"] == "a_valider" and q["facture"]}
    erreurs["paiement_recu_non_rapproche_relance"] = sum(
        1 for _, _, x in relancees if x["issue"] != "rejetee" and (x["code_client"], x["numero"]) in en_attente)
    par_client = Counter(client for _, client, _ in relancees)
    erreurs["messages_en_trop_le_meme_jour"] = sum(n - 1 for n in par_client.values() if n > 1)
    erreurs["anomalies_non_signalees"] = sum(1 for x in par_ligne.values() if x["issue"] != "acceptee")
    # Première heure de travail : les N premières lignes du fichier.
    premiere_heure = [x for _, _, x in relancees][:CAPACITE_UNE_HEURE]
    du_premiere_heure = sum(Decimal(x["solde"]) for x in premiere_heure
                            if x["issue"] != "rejetee" and x.get("devise") == "XOF" and x["statut"] in ("echue", "partiellement_payee"))
    return {"relances": len(relancees), "messages": len(relancees), "lignes_ignorees_sans_alerte": ignorees,
            "erreurs": dict(erreurs), "du_traite_premiere_heure_fcfa": int(du_premiere_heure)}


def outil(attendus: dict) -> dict:
    with tempfile.TemporaryDirectory() as dossier:
        conn = connecter(Path(dossier) / "mesure.db")
        migrer(conn)
        seed.initialiser(conn)
        parametres.ecrire(conn, "date_du_jour_simulee", REFERENCE.isoformat(), "mesure")
        chronos = {}
        debut = time.perf_counter()
        for nom, t in (("clients.csv", "clients"), ("factures_lot1.csv", "factures"), ("paiements_mobile_money.csv", "paiements")):
            importer.importer(conn, t, (config.DOSSIER_DEMO / nom).read_bytes(), nom, "mesure")
        chronos["import_s"] = time.perf_counter() - debut
        debut = time.perf_counter()
        rapprochement.rapprocher_tout(conn)
        chronos["rapprochement_s"] = time.perf_counter() - debut
        debut = time.perf_counter()
        file, _ = priorisation.file_du_jour(conn)
        chronos["priorisation_s"] = time.perf_counter() - debut
        debut = time.perf_counter()
        relances.preparer(conn)
        chronos["preparation_s"] = time.perf_counter() - debut

        en_attente = {(q["facture"]["code_client"], q["facture"]["numero"]) for q in attendus["paiements"]
                      if q["issue"] == "a_valider" and q["facture"]}
        attendu_par_cle = {(x["code_client"], x["numero"]): x for x in attendus["factures"]
                           if x["fichier"] == "factures_lot1.csv" and x["issue"] != "rejetee"}
        ctx = moteur.contexte(conn)
        erreurs = Counter()
        rel = conn.execute("SELECT r.*, c.code, f.numero FROM relances r JOIN clients c ON c.id = r.client_id"
                           " JOIN factures f ON f.id = r.facture_id").fetchall()
        for r in rel:
            x = attendu_par_cle.get((r["code"], r["numero"]))
            if x is None:
                continue
            if x["statut"] == "payee":
                erreurs["factures_payees_relancees"] += 1
            if x["statut"] == "en_litige":
                erreurs["litiges_relances"] += 1
            if "a_verifier" in x["drapeaux"]:
                erreurs["donnees_douteuses_relancees"] += 1
            if (r["code"], r["numero"]) in en_attente:
                erreurs["paiement_recu_non_rapproche_relance"] += 1
        erreurs["doublons_relances"] = sum(n - 1 for n in Counter(r["facture_id"] for r in rel).values() if n > 1)
        lots: dict[str, list] = {}
        for r in rel:
            lots.setdefault(r["lot_envoi"], []).append(r)
        for lot in lots.values():
            if lot[0]["etape"] == "R5":
                continue
            etats = [moteur.etat(conn, r["facture_id"], ctx) for r in lot]
            ecarts = garde_fous.verifier_message(garde_fous.corps_du_message(lot[0]["message"]), etats)
            erreurs["montants_faux"] += any("solde" in e or "montant" in e for e in ecarts)
        par_client_jour = Counter((r["client_id"], r["date_preparation"], r["etape"] == "R5") for r in rel)
        erreurs["messages_en_trop_le_meme_jour"] = sum(n - 1 for n in Counter(k for k in par_client_jour).values() if n > 1)
        anomalies = conn.execute("SELECT count(*) FROM import_anomalies a JOIN imports i ON i.id = a.import_id"
                                 " WHERE i.fichier = 'factures_lot1.csv'").fetchone()[0]
        a_valider = conn.execute("SELECT count(DISTINCT lot_envoi) FROM relances WHERE statut = 'a_valider'").fetchone()[0]
        premiere_heure = [p for p in file if p.facture.devise == "XOF"][:CAPACITE_UNE_HEURE]
        du = sum(p.facture.solde for p in premiere_heure)
        conn.close()
    return {"relances": len(rel), "messages": len(lots), "lots_a_valider": a_valider, "anomalies_signalees": anomalies,
            "erreurs": dict(erreurs), "chronos": {k: round(v, 3) for k, v in chronos.items()},
            "du_traite_premiere_heure_fcfa": du}


def mesurer() -> dict:
    attendus = _attendus()
    naif, auto = reference_naive(attendus), outil(attendus)
    machine_min = sum(auto["chronos"].values()) / 60
    temps = {
        "manuel_min": round(naif["relances"] * HYPOTHESES["manuel_par_relance"], 1),
        "outil_min": round(HYPOTHESES["outil_lancement"] + auto["lots_a_valider"] * HYPOTHESES["outil_par_lot_a_valider"]
                           + machine_min, 1),
    }
    temps["gain_pct"] = round(100 * (1 - temps["outil_min"] / temps["manuel_min"]), 1) if temps["manuel_min"] else None
    return {"date_reference": REFERENCE.isoformat(), "jeu": "factures_lot1.csv (128 lignes piégées) + paiements mobile money",
            "hypotheses_minutes": HYPOTHESES, "delai_suivi_paiements_jours": DELAI_SUIVI_JOURS,
            "capacite_premiere_heure": CAPACITE_UNE_HEURE,
            "reference_naive": naif, "outil": auto, "temps": temps}


LIBELLES = [
    ("factures_payees_relancees", "Factures déjà payées relancées"),
    ("paiement_recu_non_rapproche_relance", "Clients relancés alors qu'un paiement est arrivé (sans bonne référence)"),
    ("doublons_relances", "Doublons relancés deux fois"),
    ("montants_faux", "Montants réclamés faux (paiement récent ignoré)"),
    ("litiges_relances", "Factures en litige relancées"),
    ("lignes_invalides_relancees", "Lignes invalides relancées"),
    ("donnees_douteuses_relancees", "Données douteuses relancées sans vérification"),
    ("relances_impossibles", "Relances tentées sans aucun contact"),
    ("messages_en_trop_le_meme_jour", "Messages en trop au même client le même jour"),
]


def ecrire(resultat: dict) -> None:
    (config.RACINE / "docs" / "mesure_gains.json").write_text(json.dumps(resultat, ensure_ascii=False, indent=2) + "\n",
                                                              encoding="utf-8")
    n, o, t = resultat["reference_naive"], resultat["outil"], resultat["temps"]
    fcfa = lambda v: f"{v:,}".replace(",", " ") + " FCFA"  # noqa: E731
    lignes = ["# Mesure des gains", "",
              f"Jeu : {resultat['jeu']}, au {resultat['date_reference']}. Généré par `python -m app.mesure_gains`.", "",
              "Référence : relance naïve (chaque ligne échue du fichier, dans l'ordre du fichier, un message par facture). "
              f"Le gestionnaire connaît les paiements de plus de {DELAI_SUIVI_JOURS} jours (suivi mis à jour chaque semaine), "
              "pas les plus récents.", "",
              "## Erreurs (mesurées sur les données)", "", "| Erreur | Référence naïve | Recouvra |", "|---|---|---|"]
    for cle, lib in LIBELLES:
        lignes.append(f"| {lib} | {n['erreurs'].get(cle, 0)} | {o['erreurs'].get(cle, 0)} |")
    lignes += [f"| Anomalies du fichier signalées | 0 sur {n['erreurs']['anomalies_non_signalees']} | {o['anomalies_signalees']} |", "",
               "## Volume et priorité", "", "| Indicateur | Référence naïve | Recouvra |", "|---|---|---|",
               f"| Relances | {n['relances']} | {o['relances']} |",
               f"| Messages envoyés | {n['messages']} | {o['messages']} |",
               f"| Solde dû traité dans la première heure ({resultat['capacite_premiere_heure']} factures) | "
               f"{fcfa(n['du_traite_premiere_heure_fcfa'])} | {fcfa(o['du_traite_premiere_heure_fcfa'])} |", "",
               "## Temps (hypothèses à remplacer par un chronométrage)", "",
               "| Poste | Minutes |", "|---|---|",
               f"| Traitement manuel ({n['relances']} relances × {resultat['hypotheses_minutes']['manuel_par_relance']} min) | {t['manuel_min']} |",
               f"| Avec Recouvra (lancement + {o['lots_a_valider']} messages à valider × {resultat['hypotheses_minutes']['outil_par_lot_a_valider']} min + calcul) | {t['outil_min']} |",
               f"| Gain | {t['gain_pct']} % |", "",
               "Temps machine mesurés : " + ", ".join(f"{k.replace('_s', '')} {v} s" for k, v in o["chronos"].items()) + "."]
    (config.RACINE / "docs" / "mesure_gains.md").write_text("\n".join(lignes) + "\n", encoding="utf-8")


if __name__ == "__main__":
    r = mesurer()
    ecrire(r)
    print(json.dumps({"erreurs_naif": r["reference_naive"]["erreurs"], "erreurs_outil": r["outil"]["erreurs"],
                      "temps": r["temps"]}, ensure_ascii=False, indent=1))
