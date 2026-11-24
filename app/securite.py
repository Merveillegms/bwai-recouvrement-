"""Hachage des mots de passe (PBKDF2-SHA256, bibliothèque standard)."""
from __future__ import annotations

import hashlib
import hmac
import secrets

_ITERATIONS = 200_000


def hacher_mot_de_passe(mot_de_passe: str) -> str:
    sel = secrets.token_bytes(16)
    derive = hashlib.pbkdf2_hmac("sha256", mot_de_passe.encode("utf-8"), sel, _ITERATIONS)
    return f"pbkdf2_sha256${_ITERATIONS}${sel.hex()}${derive.hex()}"


def verifier_mot_de_passe(mot_de_passe: str, stocke: str) -> bool:
    try:
        algo, iterations, sel, attendu = stocke.split("$")
    except ValueError:
        return False
    if algo != "pbkdf2_sha256":
        return False
    derive = hashlib.pbkdf2_hmac("sha256", mot_de_passe.encode("utf-8"), bytes.fromhex(sel), int(iterations))
    return hmac.compare_digest(derive.hex(), attendu)
