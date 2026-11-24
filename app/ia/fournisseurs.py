"""Fournisseurs de modèles de langage, derrière une interface unique et remplaçable.

- Gemini (Google AI Studio) : recommandé, bon en français, sortie JSON structurée ;
- Hugging Face (routeur compatible OpenAI) : modèles ouverts, par exemple Meta Llama ;
- Faux : réponses programmées, pour les tests et une démonstration sans réseau.
Choix et clés dans .env (voir .env.exemple). Les clés ne sont jamais journalisées.
"""
from __future__ import annotations

import os
import time
from typing import Protocol

import httpx


class ErreurIA(Exception):
    pass


class Fournisseur(Protocol):
    nom: str
    modele: str

    def generer(self, systeme: str, demande: str) -> str:
        """Retourne le texte produit par le modèle. Lève ErreurIA en cas d'échec."""


_SCHEMA_MESSAGE = {"type": "OBJECT", "properties": {"message": {"type": "STRING"}}, "required": ["message"]}


class Gemini:
    nom = "gemini"

    def __init__(self, cle: str, modele: str = "gemini-3.5-flash", client: httpx.Client | None = None,
                 pause_s: float = 2.0) -> None:
        self.cle, self.modele, self.pause_s = cle, modele, pause_s
        self.client = client or httpx.Client(timeout=30)

    def generer(self, systeme: str, demande: str) -> str:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.modele}:generateContent"
        corps = {
            "systemInstruction": {"parts": [{"text": systeme}]},
            "contents": [{"role": "user", "parts": [{"text": demande}]}],
            "generationConfig": {"temperature": 0.4, "responseMimeType": "application/json",
                                 "responseSchema": _SCHEMA_MESSAGE,
                                 "thinkingConfig": {"thinkingLevel": "low"}},  # 20 s → 8 s, qualité suffisante
        }
        try:
            r = self.client.post(url, json=corps, headers={"x-goog-api-key": self.cle})
            if r.status_code in (429, 503):  # surcharge passagère du service : une seconde tentative
                time.sleep(self.pause_s)
                r = self.client.post(url, json=corps, headers={"x-goog-api-key": self.cle})
            r.raise_for_status()
            return r.json()["candidates"][0]["content"]["parts"][0]["text"]
        except httpx.HTTPStatusError as e:
            raise ErreurIA(f"Gemini a répondu {e.response.status_code}") from None
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as e:
            raise ErreurIA(f"Gemini indisponible ({type(e).__name__})") from None


class HuggingFace:
    nom = "huggingface"

    def __init__(self, jeton: str, modele: str = "meta-llama/Llama-3.1-8B-Instruct",
                 client: httpx.Client | None = None) -> None:
        self.jeton, self.modele = jeton, modele
        self.client = client or httpx.Client(timeout=60)

    def generer(self, systeme: str, demande: str) -> str:
        corps = {"model": self.modele, "temperature": 0.4, "max_tokens": 800,
                 "messages": [{"role": "system", "content": systeme}, {"role": "user", "content": demande}]}
        try:
            r = self.client.post("https://router.huggingface.co/v1/chat/completions", json=corps,
                                 headers={"Authorization": f"Bearer {self.jeton}"})
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]
        except httpx.HTTPStatusError as e:
            raise ErreurIA(f"Hugging Face a répondu {e.response.status_code}") from None
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as e:
            raise ErreurIA(f"Hugging Face indisponible ({type(e).__name__})") from None


class Faux:
    """Fournisseur programmé : renvoie les réponses données, dans l'ordre (tests, démo hors ligne)."""
    nom = "faux"
    modele = "reponses-programmees"

    def __init__(self, reponses: list[str | Exception]) -> None:
        self.reponses = list(reponses)
        self.demandes: list[tuple[str, str]] = []

    def generer(self, systeme: str, demande: str) -> str:
        self.demandes.append((systeme, demande))
        if not self.reponses:
            raise ErreurIA("Aucune réponse programmée")
        r = self.reponses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def fournisseur_configure() -> Fournisseur | None:
    """Fournisseur choisi dans l'environnement (.env), ou None si aucune clé n'est disponible."""
    choix = os.environ.get("RECOUVREMENT_IA_FOURNISSEUR", "").strip().lower()
    gemini, hf = os.environ.get("GEMINI_API_KEY", "").strip(), os.environ.get("HF_TOKEN", "").strip()
    if choix == "aucun":
        return None
    if choix in ("", "gemini") and gemini:
        return Gemini(gemini, os.environ.get("GEMINI_MODELE", "gemini-3.5-flash"))
    if choix in ("", "huggingface") and hf:
        return HuggingFace(hf, os.environ.get("HF_MODELE", "meta-llama/Llama-3.1-8B-Instruct"))
    return None
