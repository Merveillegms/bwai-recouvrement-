"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { api, fermerSession, session } from "@/lib/api";
import { FournisseurApp, useApp } from "@/lib/donnees";
import { dateLongue, ROLES } from "@/lib/libelles";
import type { Utilisateur } from "@/lib/types";
import { Tampon } from "./ui";

export function Coquille({ children }: { children: ReactNode }) {
  const router = useRouter();
  const [utilisateur, setUtilisateur] = useState<Utilisateur | null>(null);

  useEffect(() => {
    const s = session();
    if (!s) router.replace("/connexion");
    else setUtilisateur(s.utilisateur);
  }, [router]);

  if (!utilisateur) return null;
  return (
    <FournisseurApp utilisateur={utilisateur}>
      <EnTete />
      <main className="mx-auto w-full max-w-[1240px] px-4 pb-16 pt-6 sm:px-6">{children}</main>
    </FournisseurApp>
  );
}

function EnTete() {
  const { utilisateur, systeme } = useApp();
  const chemin = usePathname();
  const router = useRouter();
  const a = systeme?.a_traiter;
  const liens: { href: string; libelle: string; compte?: number }[] = [
    { href: "/", libelle: "Aujourd'hui" },
    { href: "/validation", libelle: "Validation", compte: a ? a.lots_a_valider + a.lots_a_envoyer + a.relances_en_echec : 0 },
    { href: "/paiements", libelle: "Paiements", compte: a?.paiements_a_valider },
    { href: "/factures", libelle: "Factures" },
    { href: "/import", libelle: "Import", compte: a ? a.anomalies_ouvertes + a.factures_a_verifier : 0 },
    { href: "/journal", libelle: "Journal" },
    { href: "/tableau", libelle: "Tableau de bord" },
    { href: "/reglages", libelle: "Réglages" },
  ];
  const actif = (href: string) => (href === "/" ? chemin === "/" : chemin.startsWith(href));

  return (
    <header className="sticky z-30 bg-papier" style={{ top: "env(safe-area-inset-top, 0px)" }}>
      <div className="filet-double mx-auto flex max-w-[1240px] flex-wrap items-baseline justify-between gap-x-6 gap-y-1 px-4 pb-2 pt-4 sm:px-6">
        <Link href="/" className="font-titre text-2xl font-semibold">
          Recouvrement
          <span className="ml-2 font-texte text-sm font-normal text-encre-pale">{systeme?.entreprise}</span>
        </Link>
        <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1 text-sm">
          {systeme && (
            <span className="chiffres" title={systeme.date_simulee ? "Date simulée (mode démonstration)" : "Date du jour"}>
              {dateLongue(systeme.date_du_jour)}{systeme.date_simulee && <span className="text-encre-pale"> · simulée</span>}
            </span>
          )}
          <span className="text-encre-pale">{utilisateur.nom} · {ROLES[utilisateur.role]}</span>
          <button type="button" className="underline underline-offset-2"
                  onClick={async () => {
                    try { await api("/api/auth/deconnexion", { methode: "POST" }); } catch { /* déjà expirée */ }
                    fermerSession();
                    router.replace("/connexion");
                  }}>
            Se déconnecter
          </button>
        </div>
      </div>
      <nav className="border-b border-filet" aria-label="Sections">
        <ul className="mx-auto flex max-w-[1240px] flex-wrap gap-x-5 px-4 text-sm sm:px-6">
          {liens.map((l) => (
            <li key={l.href}>
              <Link href={l.href} aria-current={actif(l.href) ? "page" : undefined}
                    className={`inline-block border-b-2 py-2 ${actif(l.href) ? "border-encre font-semibold" : "border-transparent text-encre-pale hover:text-encre"}`}>
                {l.libelle}
                {!!l.compte && <span className="chiffres ml-1.5 text-tampon">{l.compte}</span>}
              </Link>
            </li>
          ))}
        </ul>
      </nav>
      {systeme?.arret_urgence && (
        <div className="border-b-2 border-tampon bg-papier-fonce">
          <p className="mx-auto flex max-w-[1240px] flex-wrap items-center gap-3 px-4 py-2 text-sm text-tampon sm:px-6">
            <Tampon>Arrêt d'urgence</Tampon>
            Aucune relance n'est préparée ni envoyée. Le validateur peut le lever dans Réglages.
          </p>
        </div>
      )}
    </header>
  );
}
