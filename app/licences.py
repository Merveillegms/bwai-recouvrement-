"""Inventaire des licences des dépendances (Python et interface), écrit dans docs/licences.md.

    python -m app.licences
"""
from __future__ import annotations

import json
from importlib import metadata

from app import config


def _licence_python(dist: metadata.Distribution) -> str:
    m = dist.metadata
    if m.get("License-Expression"):
        return m["License-Expression"]
    classifieurs = [c.split("::")[-1].strip() for c in m.get_all("Classifier") or [] if c.startswith("License ::")]
    if classifieurs:
        return ", ".join(classifieurs)
    texte = (m.get("License") or "").strip()
    return texte.splitlines()[0][:60] if texte else "non déclarée"


def python() -> list[tuple[str, str, str]]:
    figees = {l.split("==")[0].lower().replace("_", "-") for l in
              (config.RACINE / "requirements.txt").read_text(encoding="utf-8").splitlines() if "==" in l}
    resultat = []
    for d in metadata.distributions():
        nom = d.metadata["Name"]
        if nom and nom.lower().replace("_", "-") in figees:
            resultat.append((nom, d.version, _licence_python(d)))
    return sorted(set(resultat), key=lambda x: x[0].lower())


def interface() -> list[tuple[str, str, str, str]]:
    front = config.RACINE / "frontend"
    paquet = json.loads((front / "package.json").read_text(encoding="utf-8"))
    resultat = []
    for portee, deps in (("exécution", paquet.get("dependencies", {})), ("développement", paquet.get("devDependencies", {}))):
        for nom, version in deps.items():
            fichier = front / "node_modules" / nom / "package.json"
            licence = json.loads(fichier.read_text(encoding="utf-8")).get("license", "non déclarée") if fichier.exists() else "?"
            resultat.append((nom, version, licence if isinstance(licence, str) else str(licence), portee))
    return resultat


def ecrire() -> str:
    lignes = ["# Licences", "", "Projet : **MIT** (voir LICENSE).", "",
              "Généré par `python -m app.licences` à partir des dépendances installées (versions figées).", "",
              "## Python (requirements.txt)", "", "| Paquet | Version | Licence |", "|---|---|---|"]
    lignes += [f"| {n} | {v} | {l} |" for n, v, l in python()]
    lignes += ["", "## Interface (frontend/package.json, dépendances directes)", "",
               "| Paquet | Version | Licence | Usage |", "|---|---|---|---|"]
    lignes += [f"| {n} | {v} | {l} | {p} |" for n, v, l, p in interface()]
    lignes += ["", "Points d'attention : fpdf2 est sous LGPL-3.0, utilisée comme bibliothèque non modifiée (compatible avec "
               "un projet MIT). Les polices (Sora, Inter, JetBrains Mono) sont sous licence SIL Open Font License."]
    texte = "\n".join(lignes) + "\n"
    (config.RACINE / "docs" / "licences.md").write_text(texte, encoding="utf-8")
    return texte


if __name__ == "__main__":
    print(ecrire())
