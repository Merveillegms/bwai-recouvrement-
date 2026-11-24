"""Test de charge : 10 000 factures, 500 clients, 4 000 paiements (base temporaire).

    python -m app.charge [nombre]      écrit docs/performance.json

Mesure le temps de chaque étape du parcours réel : import, rapprochement, file du jour, préparation des relances.
"""
from __future__ import annotations

import io
import json
import random
import sys
import tempfile
import time
from datetime import date, timedelta
from pathlib import Path

from app import config, importer, parametres, priorisation, rapprochement, relances, seed
from app.db import connecter, migrer
from app.references import generer_reference

REFERENCE = date(2026, 12, 15)


def _csv(entete: list[str], lignes: list[list]) -> bytes:
    tampon = io.StringIO()
    tampon.write(";".join(entete) + "\n")
    for l in lignes:
        tampon.write(";".join(map(str, l)) + "\n")
    return tampon.getvalue().encode("utf-8")


def generer(nombre: int, graine: int = 7) -> tuple[bytes, bytes, bytes]:
    rng = random.Random(graine)
    nb_clients = max(10, nombre // 20)
    clients = [[f"K{i:04d}", f"Client {i}", f"+229 0196{i:06d}", "", rng.choice(["sms", "whatsapp"]), "fr", "non", ""]
               for i in range(nb_clients)]
    factures, paiements = [], []
    for i in range(nombre):
        client = f"K{rng.randrange(nb_clients):04d}"
        echeance = REFERENCE - timedelta(days=rng.randint(-30, 200))
        montant = rng.randrange(20, 2000) * 1000 + i % 1000  # montants distincts : pas de quasi-doublon fortuit
        numero = f"F-{i:06d}"
        factures.append([numero, client, (echeance - timedelta(days=30)).isoformat(), echeance.isoformat(), montant, "XOF"])
        if rng.random() < 0.4 and echeance < REFERENCE:
            paye = montant if rng.random() < 0.7 else montant // 2
            paiements.append([f"T{i:07d}", min(REFERENCE, echeance + timedelta(days=rng.randint(0, 60))).isoformat(), paye,
                              "XOF", generer_reference(client, numero), "", "MTN MoMo"])
    return (_csv(["code_client", "nom", "telephone", "email", "canal_prefere", "langue", "sensible", "notes"], clients),
            _csv(["numero_facture", "code_client", "date_emission", "date_echeance", "montant_ttc", "devise"], factures),
            _csv(["id_transaction", "date", "montant", "devise", "reference", "telephone_payeur", "operateur"], paiements))


def mesurer(nombre: int = 10_000) -> dict:
    clients, factures, paiements = generer(nombre)
    with tempfile.TemporaryDirectory() as dossier:
        conn = connecter(Path(dossier) / "charge.db")
        migrer(conn)
        seed.initialiser(conn)
        parametres.ecrire(conn, "date_du_jour_simulee", REFERENCE.isoformat(), "charge")
        temps = {}

        def chrono(nom, fn):
            debut = time.perf_counter()
            resultat = fn()
            temps[nom] = round(time.perf_counter() - debut, 2)
            return resultat

        chrono("import_clients_s", lambda: importer.importer(conn, "clients", clients, "clients.csv", "charge"))
        rapport = chrono("import_factures_s", lambda: importer.importer(conn, "factures", factures, "factures.csv", "charge"))
        chrono("import_paiements_s", lambda: importer.importer(conn, "paiements", paiements, "paiements.csv", "charge"))
        resume = chrono("rapprochement_s", lambda: rapprochement.rapprocher_tout(conn))
        file, exclues = chrono("file_du_jour_s", lambda: priorisation.file_du_jour(conn))
        prep = chrono("preparation_relances_s", lambda: relances.preparer(conn))
        taille = (Path(dossier) / "charge.db").stat().st_size
        conn.close()
    return {"factures": nombre, "paiements": paiements.count(b"\n") - 1, "acceptees": rapport.lignes_acceptees,
            "rapprochements": resume.get("RAPPROCHE", 0), "file_du_jour": len(file), "exclues": len(exclues),
            "relances_preparees": prep["relances"], "temps_s": temps, "total_s": round(sum(temps.values()), 2),
            "taille_base_mo": round(taille / 1e6, 1)}


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 10_000
    r = mesurer(n)
    (config.RACINE / "docs" / "performance.json").write_text(json.dumps(r, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(r, ensure_ascii=False, indent=1))
