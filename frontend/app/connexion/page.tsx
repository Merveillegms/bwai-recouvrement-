"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { api, ErreurApi, ouvrirSession } from "@/lib/api";
import type { Utilisateur } from "@/lib/types";

const COMPTES = [
  { identifiant: "gestionnaire", role: "Prépare et envoie les relances, saisit les réponses" },
  { identifiant: "validateur", role: "Valide les cas sensibles, arrête tout en urgence" },
  { identifiant: "auditeur", role: "Consulte tout, sans rien modifier" },
];

export default function Connexion() {
  const router = useRouter();
  const [identifiant, setIdentifiant] = useState("gestionnaire");
  const [motDePasse, setMotDePasse] = useState("");
  const [erreur, setErreur] = useState<string | null>(null);
  const [occupe, setOccupe] = useState(false);

  async function connecter(id = identifiant, mdp = motDePasse) {
    setOccupe(true);
    setErreur(null);
    try {
      const r = await api<{ jeton: string; utilisateur: Utilisateur }>("/api/auth/connexion",
                                                                       { corps: { identifiant: id, mot_de_passe: mdp } });
      ouvrirSession(r.jeton, r.utilisateur);
      router.replace("/");
    } catch (e) {
      setErreur(e instanceof ErreurApi ? e.message : "Connexion impossible");
    } finally {
      setOccupe(false);
    }
  }

  return (
    <main className="mx-auto grid min-h-full max-w-4xl content-center gap-10 px-4 py-12 md:grid-cols-[1.1fr_1fr]">
      <section className="grid content-start gap-4">
        <p className="etiquette">Distribution Atlantique SARL · Cotonou</p>
        <h1 className="text-4xl font-semibold leading-tight">Registre de recouvrement</h1>
        <p className="max-w-prose text-encre-pale">
          La bonne relance au bon moment. Aucune facture payée n'est relancée, aucune action n'est faite deux fois,
          et chaque décision est inscrite au journal.
        </p>
        <div className="filet-double" />
        <p className="etiquette">Comptes de démonstration</p>
        <ul className="grid gap-2">
          {COMPTES.map((c) => (
            <li key={c.identifiant}>
              <button type="button" disabled={occupe} onClick={() => connecter(c.identifiant, `demo-${c.identifiant}`)}
                      className="grid w-full gap-0.5 border border-filet px-4 py-2.5 text-left hover:bg-lavis disabled:opacity-50">
                <span className="font-semibold">Entrer comme {c.identifiant}</span>
                <span className="text-sm text-encre-pale">{c.role}</span>
              </button>
            </li>
          ))}
        </ul>
      </section>

      <form className="grid content-start gap-4 border border-filet bg-[#fbf9f3] p-6"
            onSubmit={(e) => { e.preventDefault(); connecter(); }}>
        <h2 className="text-2xl font-semibold">Connexion</h2>
        <label className="grid gap-1 text-sm" htmlFor="identifiant">Identifiant
          <input id="identifiant" className="champ" autoComplete="username" value={identifiant}
                 onChange={(e) => setIdentifiant(e.target.value)} />
        </label>
        <label className="grid gap-1 text-sm" htmlFor="mot-de-passe">Mot de passe
          <input id="mot-de-passe" type="password" className="champ" autoComplete="current-password" value={motDePasse}
                 onChange={(e) => setMotDePasse(e.target.value)} />
        </label>
        {erreur && <p role="alert" className="text-sm text-tampon">{erreur}</p>}
        <button type="submit" className="bouton justify-center" disabled={occupe || !motDePasse}>Se connecter</button>
        <p className="text-xs text-encre-pale">Mots de passe de démonstration : demo-gestionnaire, demo-validateur, demo-auditeur.</p>
      </form>
    </main>
  );
}
