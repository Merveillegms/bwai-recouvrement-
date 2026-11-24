"""Références de paiement : courtes, lisibles, avec chiffre de contrôle (algorithme de Damm).

Format : RC + 8 chiffres + 1 chiffre de contrôle, par ex. RC123456784.
Affichage : RC-1234-5678-4. La saisie tolère minuscules, espaces, tirets et points.
Le chiffre de Damm détecte toute erreur sur un chiffre et toute inversion de deux chiffres voisins.
La référence dérive de (code client, numéro de facture) : elle est stable et reproductible.
"""
from __future__ import annotations

import hashlib
import re

PREFIXE = "RC"

_TABLE_DAMM = (
    (0, 3, 1, 7, 5, 9, 8, 6, 4, 2),
    (7, 0, 9, 2, 1, 5, 4, 8, 6, 3),
    (4, 2, 0, 6, 8, 7, 1, 3, 5, 9),
    (1, 7, 5, 0, 9, 8, 3, 4, 2, 6),
    (6, 1, 2, 3, 0, 4, 5, 9, 7, 8),
    (3, 6, 7, 4, 2, 0, 9, 5, 8, 1),
    (5, 8, 6, 9, 7, 2, 0, 1, 3, 4),
    (8, 9, 4, 5, 3, 6, 2, 0, 1, 7),
    (9, 4, 3, 8, 6, 1, 7, 2, 0, 5),
    (2, 5, 8, 1, 4, 3, 6, 7, 9, 0),
)
_FORMAT = re.compile(rf"^{PREFIXE}\d{{9}}$")


def _damm(chiffres: str) -> int:
    interim = 0
    for c in chiffres:
        interim = _TABLE_DAMM[interim][int(c)]
    return interim


def chiffre_controle(chiffres: str) -> str:
    return str(_damm(chiffres))


def generer_reference(code_client: str, numero_facture: str) -> str:
    graine = f"{code_client.strip().upper()}|{numero_facture.strip().upper()}".encode("utf-8")
    corps = f"{int.from_bytes(hashlib.sha256(graine).digest()[:8], 'big') % 10**8:08d}"
    return f"{PREFIXE}{corps}{chiffre_controle(corps)}"


def normaliser_reference(texte: str) -> str:
    return re.sub(r"[\s\-.]", "", texte or "").upper()


def reference_valide(texte: str) -> bool:
    ref = normaliser_reference(texte)
    return bool(_FORMAT.match(ref)) and _damm(ref[len(PREFIXE):]) == 0


def formater_reference(reference: str) -> str:
    ref = normaliser_reference(reference)
    c = ref[len(PREFIXE):]
    return f"{PREFIXE}-{c[:4]}-{c[4:8]}-{c[8:]}"
