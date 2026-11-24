"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { api, ErreurApi, ouvrirSession } from "@/lib/api";
import type { Utilisateur } from "@/lib/types";

const COMPTES = [
  { identifiant: "gestionnaire", role: "Prépare et envoie les relances, saisit les réponses" },
  { identifiant: "validateur", role: "Valide les cas sensibles, peut tout arrêter en urgence" },
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
      const r = await api<{ jeton: string; utilisateur: Utilisateur }>("/api/auth/connexion", { corps: { identifiant: id, mot_de_passe: mdp } });
      ouvrirSession(r.jeton, r.utilisateur);
      router.replace("/app");
    } catch (e) {
      setErreur(e instanceof ErreurApi ? e.message : "Connexion impossible");
    } finally {
      setOccupe(false);
    }
  }

  return (
    <main className="grid min-h-screen lg:grid-cols-[1fr_1fr]">
      <section className="hidden flex-col justify-between bg-encre p-12 text-white lg:flex">
        <Link href="/" className="flex items-center gap-2.5 font-titre text-[18px] font-bold">
          <span className="grid h-8 w-8 place-items-center rounded-lg bg-vert text-[14px]">R</span>Recouvra
        </Link>
        <div className="grid max-w-md gap-5">
          <h1 className="text-[34px] font-bold leading-tight">La bonne relance, <span className="text-vert">au bon moment.</span></h1>
          <p className="text-[15px] text-[#a9b4c8]">Aucune facture payée n'est relancée, aucune action n'est faite deux fois, et chaque décision est inscrite au journal.</p>
        </div>
        <p className="text-[12.5px] text-[#8b97ad]">Distribution Atlantique SARL · Cotonou · données fictives</p>
      </section>

      <section className="grid content-center justify-items-center px-5 py-12">
        <div className="grid w-full max-w-md gap-6">
          <Link href="/" className="flex items-center gap-2.5 font-titre text-[17px] font-bold lg:hidden">
            <span className="grid h-8 w-8 place-items-center rounded-lg bg-vert text-[14px] text-white">R</span>Recouvra
          </Link>
          <div>
            <h2 className="text-[24px] font-bold">Connexion</h2>
            <p className="mt-1 text-[13.5px] text-doux">Choisissez un compte de démonstration ou saisissez vos identifiants.</p>
          </div>
          <ul className="grid gap-2">
            {COMPTES.map((c) => (
              <li key={c.identifiant}>
                <button type="button" disabled={occupe} onClick={() => connecter(c.identifiant, `demo-${c.identifiant}`)}
                        className="carte flex w-full items-center justify-between gap-4 px-4 py-3 text-left transition-colors hover:border-vert disabled:opacity-50">
                  <span className="grid gap-0.5"><span className="font-semibold capitalize">{c.identifiant}</span><span className="text-[12.5px] text-doux">{c.role}</span></span>
                  <span className="text-vert" aria-hidden="true">→</span>
                </button>
              </li>
            ))}
          </ul>
          <div className="flex items-center gap-3 text-[12px] text-doux"><span className="h-px flex-1 bg-filet" />ou<span className="h-px flex-1 bg-filet" /></div>
          <form className="grid gap-3" onSubmit={(e) => { e.preventDefault(); connecter(); }}>
            <label className="grid gap-1 text-[13px] font-medium" htmlFor="identifiant">Identifiant
              <input id="identifiant" className="champ" autoComplete="username" value={identifiant} onChange={(e) => setIdentifiant(e.target.value)} />
            </label>
            <label className="grid gap-1 text-[13px] font-medium" htmlFor="mot-de-passe">Mot de passe
              <input id="mot-de-passe" type="password" className="champ" autoComplete="current-password" value={motDePasse} onChange={(e) => setMotDePasse(e.target.value)} />
            </label>
            {erreur && <p role="alert" className="alerte"><span className="font-bold">!</span>{erreur}</p>}
            <button type="submit" className="btn py-2.5" disabled={occupe || !motDePasse}>Se connecter</button>
          </form>
        </div>
      </section>
    </main>
  );
}
