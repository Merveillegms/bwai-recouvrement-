"""Indicateurs du tableau de bord : des réponses à des questions de gestionnaire, calculées par le code.

- Combien reste-t-il à recouvrer, et où est le risque (tranches, top 10) ?
- Quelle est ma charge (relances à valider, bloquées, en échec) ?
- Les relances sont-elles efficaces (sommes recouvrées après relance, délai de paiement, promesses tenues) ?
- Que m'ont évité les garde-fous (rejets, doublons, annulations avant envoi) ?
Montants en unités mineures, avec leur affichage ; jamais d'addition entre devises.
"""
from __future__ import annotations

import csv
import io
import sqlite3
from collections import defaultdict
from datetime import date

from app import calculs
from app import etat as moteur
from app.montants import formater

OUVERTS = ("echue", "partiellement_payee", "en_litige", "suspendue", "a_echoir")


def _montants(par_devise: dict[str, int], decimales: dict[str, int]) -> dict:
    return {d: {"montant": m, "affiche": formater(m, d, decimales[d])} for d, m in sorted(par_devise.items())}


def indicateurs(conn: sqlite3.Connection, debut: str | None = None, fin: str | None = None,
                client: str | None = None, tranche: str | None = None) -> dict:
    ctx = moteur.contexte(conn)
    decimales = {r["code"]: r["decimales"] for r in conn.execute("SELECT code, decimales FROM devises")}
    condition, params = ("c.code = ?", (client.upper(),)) if client else ("", ())
    etats = [e for e in moteur.etats(conn, condition, params, ctx) if not tranche or e.tranche == tranche]
    ids = {e.id for e in etats}
    debut = debut or "0000-01-01"
    fin = fin or ctx.reference.isoformat()

    # ------------------------------------------------------------------ encours
    du, echu = defaultdict(int), defaultdict(int)
    par_tranche: dict[str, dict] = {t: {"nombre": 0, "montants": defaultdict(int)} for t in calculs.TRANCHES}
    echues = []
    for e in etats:
        if e.statut in OUVERTS and e.solde > 0:
            du[e.devise] += e.solde
            if e.jours_retard > 0:
                echu[e.devise] += e.solde
                echues.append(e)
            par_tranche[e.tranche]["nombre"] += 1
            par_tranche[e.tranche]["montants"][e.devise] += e.solde
    top = sorted(echues, key=lambda e: (e.devise != "XOF", -e.solde, e.numero))[:10]

    # ---------------------------------------------------------------- relances
    statuts_relances = {r["statut"]: r["n"] for r in conn.execute(
        "SELECT statut, count(*) AS n FROM relances GROUP BY statut")}
    lots_a_valider = conn.execute("SELECT count(DISTINCT lot_envoi) FROM relances WHERE statut = 'a_valider'").fetchone()[0]
    annulees = conn.execute("SELECT motif_annulation FROM relances WHERE statut = 'annulee'").fetchall()
    bloquees_avant_envoi = sum(1 for a in annulees if a[0] and not a[0].startswith(("Rejet", "Suspension")))

    # -------------------------------------------------- efficacité après relance
    premiere_relance = {r["facture_id"]: r["d"] for r in conn.execute(
        "SELECT facture_id, min(date_envoi) AS d FROM relances WHERE statut = 'envoyee' GROUP BY facture_id")}
    derniere_etape = {}
    for r in conn.execute("SELECT facture_id, etape, date_envoi FROM relances WHERE statut = 'envoyee' ORDER BY date_envoi"):
        derniere_etape.setdefault(r["facture_id"], []).append((r["date_envoi"], r["etape"]))
    recouvre, nb_paiements = defaultdict(int), 0
    delais: dict[str, list[int]] = defaultdict(list)
    for p in conn.execute("SELECT p.*, f.devise AS devise_facture FROM paiements p JOIN factures f ON f.id = p.facture_id"
                          " WHERE p.statut_rapprochement = 'rapproche' AND p.date_paiement BETWEEN ? AND ?", (debut, fin)):
        if p["facture_id"] not in ids or p["facture_id"] not in premiere_relance:
            continue
        if p["date_paiement"] < premiere_relance[p["facture_id"]]:
            continue
        recouvre[p["devise"]] += p["montant"]
        nb_paiements += 1
        avant = [(d, etape) for d, etape in derniere_etape[p["facture_id"]] if d <= p["date_paiement"]]
        d_relance, etape = avant[-1]
        delais[etape].append((date.fromisoformat(p["date_paiement"]) - date.fromisoformat(d_relance)).days)
    delai_moyen = {etape: round(sum(v) / len(v), 1) for etape, v in sorted(delais.items())}
    tous = [x for v in delais.values() for x in v]

    # ---------------------------------------------------------------- promesses
    promesses = {"tenues": 0, "non_tenues": 0, "en_cours": 0}
    for r in conn.execute("SELECT * FROM reponses_client WHERE type IN ('promesse', 'demande_delai')"
                          " AND date_promise IS NOT NULL"):
        if r["date_promise"] >= ctx.reference.isoformat():
            promesses["en_cours"] += 1
            continue
        paye = conn.execute(
            "SELECT 1 FROM paiements p JOIN factures f ON f.id = p.facture_id WHERE p.statut_rapprochement = 'rapproche'"
            " AND f.client_id = ? AND (? IS NULL OR f.id = ?) AND p.date_paiement <= ? AND p.date_paiement >= ?",
            (r["client_id"], r["facture_id"], r["facture_id"], r["date_promise"], r["cree_le"][:10])).fetchone()
        promesses["tenues" if paye else "non_tenues"] += 1

    # ------------------------------------------------------- valeur des garde-fous
    anomalies = {r["code"]: r["n"] for r in conn.execute(
        "SELECT code, count(*) AS n FROM import_anomalies GROUP BY code ORDER BY n DESC")}
    garde_fous = {
        "lignes_rejetees_a_l_import": conn.execute(
            "SELECT count(*) FROM import_anomalies WHERE gravite = 'rejet'").fetchone()[0],
        "doublons_detectes": sum(n for c, n in anomalies.items()
                                 if c.startswith(("DOUBLON", "CONFLIT")) or c == "QUASI_DOUBLON"),
        "factures_a_verifier": sum(1 for e in etats if e.a_verifier),
        "paiements_a_valider": conn.execute(
            "SELECT count(*) FROM paiements WHERE statut_rapprochement = 'a_valider'").fetchone()[0],
        "relances_annulees_avant_envoi": bloquees_avant_envoi,
        "factures_payees_jamais_relancees": sum(1 for e in etats if e.statut == "payee"
                                                and e.id not in premiere_relance),
        "par_code": anomalies,
    }
    return {
        "date_reference": ctx.reference.isoformat(), "periode": {"debut": debut, "fin": fin},
        "filtres": {"client": client, "tranche": tranche},
        "encours": {"total_du": _montants(du, decimales), "total_echu": _montants(echu, decimales),
                    "factures_echues": len(echues)},
        "tranches": [{"tranche": t, "nombre": v["nombre"], "montants": _montants(v["montants"], decimales)}
                     for t, v in par_tranche.items()],
        "top10": [{"facture_id": e.id, "numero": e.numero, "client": e.nom_client, "jours_retard": e.jours_retard,
                   "solde": e.solde, "affiche": formater(e.solde, e.devise, e.decimales)} for e in top],
        "relances": {"par_statut": statuts_relances, "lots_a_valider": lots_a_valider,
                     "annulees_avant_envoi": bloquees_avant_envoi},
        "efficacite": {"recouvre_apres_relance": _montants(recouvre, decimales), "paiements_apres_relance": nb_paiements,
                       "delai_moyen_jours": round(sum(tous) / len(tous), 1) if tous else None,
                       "delai_moyen_par_etape": delai_moyen, "promesses": promesses},
        "garde_fous": garde_fous,
    }


def _lignes(ind: dict) -> list[tuple[str, str, str]]:
    lignes = [("Contexte", "Date de référence", ind["date_reference"]),
              ("Contexte", "Période", f"{ind['periode']['debut']} → {ind['periode']['fin']}")]
    for d, v in ind["encours"]["total_du"].items():
        lignes.append(("Encours", f"Total dû ({d})", v["affiche"]))
    for d, v in ind["encours"]["total_echu"].items():
        lignes.append(("Encours", f"Total échu ({d})", v["affiche"]))
    lignes.append(("Encours", "Factures échues", str(ind["encours"]["factures_echues"])))
    for t in ind["tranches"]:
        lignes.append(("Tranches", t["tranche"], f"{t['nombre']} facture(s) — "
                       + ", ".join(v["affiche"] for v in t["montants"].values())))
    for i, f in enumerate(ind["top10"], 1):
        lignes.append(("Top 10", f"{i}. {f['numero']} ({f['client']})", f"{f['affiche']}, {f['jours_retard']} j"))
    for s, n in sorted(ind["relances"]["par_statut"].items()):
        lignes.append(("Relances", s, str(n)))
    lignes.append(("Relances", "Lots à valider", str(ind["relances"]["lots_a_valider"])))
    for d, v in ind["efficacite"]["recouvre_apres_relance"].items():
        lignes.append(("Efficacité", f"Recouvré après relance ({d})", v["affiche"]))
    lignes.append(("Efficacité", "Délai moyen de paiement après relance (j)", str(ind["efficacite"]["delai_moyen_jours"])))
    for k, v in ind["efficacite"]["promesses"].items():
        lignes.append(("Efficacité", f"Promesses {k.replace('_', ' ')}", str(v)))
    for k, v in ind["garde_fous"].items():
        if k != "par_code":
            lignes.append(("Garde-fous", k.replace("_", " ").capitalize(), str(v)))
    return lignes


def exporter_csv(ind: dict) -> bytes:
    tampon = io.StringIO()
    ecrivain = csv.writer(tampon, delimiter=";", lineterminator="\r\n")
    ecrivain.writerow(["section", "indicateur", "valeur"])
    ecrivain.writerows(_lignes(ind))
    return tampon.getvalue().encode("utf-8-sig")


def exporter_pdf(ind: dict, entreprise: str) -> bytes:
    from fpdf import FPDF

    from app.fiche import _latin1

    pdf = FPDF(format="A4")
    pdf.set_compression(False)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 15)
    pdf.cell(0, 9, _latin1(f"{entreprise} - Tableau de bord du recouvrement"), new_x="LMARGIN", new_y="NEXT")
    section = None
    for sec, indicateur, valeur in _lignes(ind):
        if sec != section:
            pdf.ln(3)
            pdf.set_font("Helvetica", "B", 11)
            pdf.cell(0, 7, _latin1(sec), new_x="LMARGIN", new_y="NEXT")
            section = sec
        pdf.set_font("Helvetica", "", 9)
        pdf.multi_cell(0, 5, _latin1(f"{indicateur} : {valeur}"), new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())
