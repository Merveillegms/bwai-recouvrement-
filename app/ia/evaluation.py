"""Évaluation de l'IA, pour la fiche IA (docs/fiche_ia.md).

    python -m app.ia.evaluation                 classification (jeu d'évaluation étiqueté, jamais vu à l'entraînement)
    python -m app.ia.evaluation --redaction 10  + rédaction sur 10 lots du jeu de démo (nécessite une clé dans .env)

Écrit docs/ia_evaluation.json. Les seuils de revue humaine se justifient par ces mesures.
"""
from __future__ import annotations

import json
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

from app import config
from app.ia import classification

SEUILS = (0.4, 0.5, 0.6, 0.7, 0.8)


def evaluer_classification(seuil_litige: float = 0.25) -> dict:
    exemples = classification.lire_exemples(classification.FICHIER_EVALUATION)
    confusion: dict[str, Counter] = defaultdict(Counter)
    resultats = []
    for texte, attendu in exemples:
        p = classification.classer(texte)
        confusion[attendu][p.categorie] += 1
        resultats.append((texte, attendu, p))
    n = len(resultats)
    justes = sum(a == p.categorie for _, a, p in resultats)
    par_classe = {}
    for c in classification.CATEGORIES:
        vrais = confusion[c][c]
        predits = sum(confusion[a][c] for a in confusion)
        reels = sum(confusion[c].values())
        par_classe[c] = {"precision": round(vrais / predits, 3) if predits else None,
                         "rappel": round(vrais / reels, 3) if reels else None, "exemples": reels}
    litiges = [p for _, a, p in resultats if a == "litige"]
    signales = sum(p.probabilites.get("litige", 0) >= seuil_litige for p in litiges)
    faux_signal = sum(p.probabilites.get("litige", 0) >= seuil_litige for _, a, p in resultats if a != "litige")
    seuils = []
    for s in SEUILS:
        au_dessus = [(a, p) for _, a, p in resultats if p.confiance >= s]
        seuils.append({"seuil": s, "couverture": round(len(au_dessus) / n, 3),
                       "exactitude_au_dessus": round(sum(a == p.categorie for a, p in au_dessus) / len(au_dessus), 3)
                       if au_dessus else None,
                       "erreurs_sous_le_seuil": sum(a != p.categorie for _, a, p in resultats if p.confiance < s)})
    return {
        "modele": classification.VERSION_MODELE,
        "exemples_entrainement": len(classification.lire_exemples(classification.FICHIER_ENTRAINEMENT)),
        "exemples_evaluation": n, "exactitude": round(justes / n, 3), "par_classe": par_classe,
        "litige": {"seuil": seuil_litige, "rappel_signalement": round(signales / len(litiges), 3) if litiges else None,
                   "faux_signalements": faux_signal},
        "seuils_de_confiance": seuils,
        "matrice_confusion": {a: dict(c) for a, c in confusion.items()},
        "erreurs": [{"texte": t, "attendu": a, "propose": p.categorie, "confiance": p.confiance}
                    for t, a, p in resultats if a != p.categorie],
    }


def evaluer_redaction(nombre: int) -> dict:
    """Rédaction réelle sur des lots du jeu de démo, dans une base temporaire (rien n'est envoyé aux clients)."""
    from app import importer, parametres, rapprochement, relances, seed
    from app.db import connecter, migrer
    from app.ia.fournisseurs import fournisseur_configure
    from app.ia.redaction import rediger_lots_du_jour

    fournisseur = fournisseur_configure()
    if fournisseur is None:
        return {"disponible": False, "raison": "aucune clé GEMINI_API_KEY ou HF_TOKEN dans .env"}
    with tempfile.TemporaryDirectory() as dossier:
        conn = connecter(Path(dossier) / "eval.db")
        migrer(conn)
        seed.initialiser(conn)
        parametres.ecrire(conn, "date_du_jour_simulee", "2026-12-15", "evaluation")
        parametres.ecrire(conn, "ia_active", True, "evaluation")
        for nom, t in (("clients.csv", "clients"), ("factures_lot1.csv", "factures"),
                       ("paiements_mobile_money.csv", "paiements")):
            importer.importer(conn, t, (config.DOSSIER_DEMO / nom).read_bytes(), nom, "evaluation")
        rapprochement.rapprocher_tout(conn)
        relances.preparer(conn)
        resultat = rediger_lots_du_jour(conn, fournisseur, "evaluation", limite=nombre)
        raisons = Counter(r for l in resultat["lots"] for r in l["raisons"])
        durees = [d[0] for d in conn.execute("SELECT duree_ms FROM ia_appels WHERE fonction = 'redaction'")]
        conn.close()
    total = len(resultat["lots"])
    return {"disponible": True, "fournisseur": fournisseur.nom, "modele": fournisseur.modele, "lots": total,
            "acceptes": resultat["acceptes"], "rejetes": resultat["rejetes"], "erreurs": resultat["erreurs"],
            "taux_acceptation": round(resultat["acceptes"] / total, 3) if total else None,
            "raisons_de_rejet": dict(raisons.most_common()),
            "duree_moyenne_ms": round(sum(durees) / len(durees)) if durees else None}


def main() -> None:
    resultat = {"classification": evaluer_classification()}
    if "--redaction" in sys.argv:
        i = sys.argv.index("--redaction")
        resultat["redaction"] = evaluer_redaction(int(sys.argv[i + 1]) if len(sys.argv) > i + 1 else 10)
    sortie = config.RACINE / "docs" / "ia_evaluation.json"
    sortie.write_text(json.dumps(resultat, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    c = resultat["classification"]
    print(f"Classification : exactitude {c['exactitude']:.0%} sur {c['exemples_evaluation']} exemples, "
          f"rappel litige {c['litige']['rappel_signalement']:.0%}")
    for s in c["seuils_de_confiance"]:
        print(f"  seuil {s['seuil']}: couverture {s['couverture']:.0%}, exactitude au-dessus {s['exactitude_au_dessus']}")
    if "redaction" in resultat:
        print("Rédaction :", json.dumps(resultat["redaction"], ensure_ascii=False))
    print(f"Résultats écrits dans {sortie}")


if __name__ == "__main__":
    main()
