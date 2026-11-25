/* Client de l'API locale. Le frontend ne calcule rien : il affiche et déclenche.
   - jeton de session en sessionStorage (fermé avec l'onglet) ;
   - chaque POST/PUT porte une clé d'idempotence : un double clic ne produit jamais deux actions. */

import type { Utilisateur } from "./types";

const CLE_JETON = "recouvrement.jeton";
const CLE_UTILISATEUR = "recouvrement.utilisateur";

export class ErreurApi extends Error {
  constructor(public code: string, message: string, public statut: number) {
    super(message);
  }
}

export function session(): { jeton: string; utilisateur: Utilisateur } | null {
  if (typeof window === "undefined") return null;
  try {
    const jeton = sessionStorage.getItem(CLE_JETON);
    const utilisateur = sessionStorage.getItem(CLE_UTILISATEUR);
    return jeton && utilisateur ? { jeton, utilisateur: JSON.parse(utilisateur) } : null;
  } catch {
    return null;
  }
}

export function ouvrirSession(jeton: string, utilisateur: Utilisateur) {
  sessionStorage.setItem(CLE_JETON, jeton);
  sessionStorage.setItem(CLE_UTILISATEUR, JSON.stringify(utilisateur));
}

export function fermerSession() {
  try {
    sessionStorage.removeItem(CLE_JETON);
    sessionStorage.removeItem(CLE_UTILISATEUR);
  } catch {
    /* stockage indisponible : rien à effacer */
  }
}

type Options = { methode?: "GET" | "POST" | "PUT"; corps?: unknown; formulaire?: FormData; cleIdempotence?: string };

async function appel(chemin: string, options: Options = {}): Promise<Response> {
  const methode = options.methode ?? (options.corps !== undefined || options.formulaire ? "POST" : "GET");
  const entetes: Record<string, string> = {};
  const s = session();
  if (s) entetes.Authorization = `Bearer ${s.jeton}`;
  if (methode !== "GET") entetes["Idempotency-Key"] = options.cleIdempotence ?? crypto.randomUUID();
  let corps: BodyInit | undefined;
  if (options.formulaire) corps = options.formulaire;
  else if (options.corps !== undefined) {
    entetes["Content-Type"] = "application/json";
    corps = JSON.stringify(options.corps);
  }
  let reponse: Response;
  try {
    reponse = await fetch(chemin, { method: methode, headers: entetes, body: corps });
  } catch {
    throw new ErreurApi("RESEAU", "Le serveur local ne répond pas. Vérifiez que « python tasks.py demo » tourne.", 0);
  }
  if (reponse.status === 401 && !chemin.startsWith("/api/auth/connexion")) {
    fermerSession();
    if (typeof window !== "undefined") window.location.assign("/connexion");
  }
  if (!reponse.ok) {
    let code = "ERREUR", message = `Erreur ${reponse.status}`;
    try {
      const d = await reponse.json();
      code = d.code ?? code;
      message = d.message ?? (Array.isArray(d.detail) ? "Données envoyées invalides" : message);
    } catch {
      /* corps non JSON */
    }
    throw new ErreurApi(code, message, reponse.status);
  }
  return reponse;
}

export async function api<T>(chemin: string, options: Options = {}): Promise<T> {
  return (await appel(chemin, options)).json() as Promise<T>;
}

/** Fichiers protégés (PDF, CSV) : récupérés avec le jeton puis ouverts ou téléchargés. */
export async function ouvrirFichier(chemin: string, nom: string, telecharger = false) {
  const blob = await (await appel(chemin)).blob();
  const url = URL.createObjectURL(blob);
  if (telecharger) {
    const a = document.createElement("a");
    a.href = url;
    a.download = nom;
    a.click();
  } else {
    window.open(url, "_blank", "noopener");
  }
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}
