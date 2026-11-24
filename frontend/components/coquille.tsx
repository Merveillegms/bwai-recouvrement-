"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { api, fermerSession, session } from "@/lib/api";
import { FournisseurApp, useApp } from "@/lib/donnees";
import { dateLongue, ROLES } from "@/lib/libelles";
import type { Utilisateur } from "@/lib/types";
import { Icones } from "./icones";

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
      <div className="min-h-screen lg:grid lg:grid-cols-[232px_minmax(0,1fr)]">
        <Lateral />
        <div className="min-w-0">
          <BandeauArret />
          <main className="mx-auto grid w-full max-w-[1280px] gap-6 py-6 sm:py-8"
                style={{ paddingLeft: "max(16px, env(safe-area-inset-left, 0px))", paddingRight: "max(16px, env(safe-area-inset-right, 0px))" }}>
            {children}
          </main>
        </div>
      </div>
    </FournisseurApp>
  );
}

function Lateral() {
  const { utilisateur, systeme } = useApp();
  const chemin = usePathname();
  const router = useRouter();
  const a = systeme?.a_traiter;
  const liens = [
    { href: "/app", libelle: "Aujourd'hui", icone: Icones.jour },
    { href: "/app/validation", libelle: "Validation", icone: Icones.validation, compte: a ? a.lots_a_valider + a.lots_a_envoyer + a.relances_en_echec : 0 },
    { href: "/app/paiements", libelle: "Paiements", icone: Icones.paiements, compte: a?.paiements_a_valider },
    { href: "/app/reponses", libelle: "Réponses clients", icone: Icones.reponses, compte: systeme?.reponses_a_traiter },
    { href: "/app/factures", libelle: "Factures", icone: Icones.factures },
    { href: "/app/import", libelle: "Import", icone: Icones.import, compte: a ? a.anomalies_ouvertes + a.factures_a_verifier : 0 },
    { href: "/app/journal", libelle: "Journal", icone: Icones.journal },
    { href: "/app/tableau", libelle: "Tableau de bord", icone: Icones.tableau },
    { href: "/app/reglages", libelle: "Réglages", icone: Icones.reglages },
  ];
  const actif = (href: string) => (href === "/app" ? chemin === "/app" : chemin.startsWith(href));
  const deconnecter = async () => {
    try { await api("/api/auth/deconnexion", { methode: "POST" }); } catch { /* session déjà expirée */ }
    fermerSession();
    router.replace("/connexion");
  };

  return (
    <aside className="sticky z-30 bg-encre text-[#b8c2d4] lg:flex lg:h-screen lg:flex-col"
           style={{ top: "env(safe-area-inset-top, 0px)" }}>
      <div className="flex items-center justify-between gap-3 px-4 py-3 lg:px-5 lg:pb-5 lg:pt-6">
        <Link href="/" className="flex items-center gap-2.5 font-titre text-[16px] font-bold text-white">
          <span className="grid h-7 w-7 place-items-center rounded-lg bg-vert text-[13px]">R</span>Recouvra
        </Link>
        <button type="button" onClick={deconnecter} className="text-[12.5px] text-[#8b97ad] hover:text-white lg:hidden">Se déconnecter</button>
      </div>
      <nav aria-label="Sections" className="overflow-x-auto px-3 pb-3 lg:flex-1 lg:overflow-y-auto lg:pb-0">
        <ul className="flex gap-1 lg:grid">
          {liens.map((l) => (
            <li key={l.href}>
              <Link href={l.href} aria-current={actif(l.href) ? "page" : undefined}
                    className={`flex items-center gap-2.5 whitespace-nowrap rounded-lg px-3 py-2 text-[13.5px] transition-colors ${actif(l.href) ? "bg-encre-2 font-semibold text-white" : "hover:bg-encre-2/60 hover:text-white"}`}>
                {l.icone}
                <span>{l.libelle}</span>
                {!!l.compte && <span className="ml-auto rounded-full bg-vert px-1.5 text-[11px] font-bold text-white tabulaire">{l.compte}</span>}
              </Link>
            </li>
          ))}
        </ul>
      </nav>
      <div className="hidden border-t border-encre-3 px-5 py-4 text-[12.5px] lg:grid lg:gap-1">
        {systeme && (
          <span className="text-white">{dateLongue(systeme.date_du_jour)}{systeme.date_simulee && <span className="text-[#8b97ad]"> (simulée)</span>}</span>
        )}
        <span>{utilisateur.nom}</span>
        <span className="text-[#8b97ad]">{ROLES[utilisateur.role]}</span>
        <button type="button" onClick={deconnecter} className="mt-2 flex items-center gap-2 text-left text-[#8b97ad] hover:text-white">
          {Icones.sortie}Se déconnecter
        </button>
      </div>
    </aside>
  );
}

function BandeauArret() {
  const { systeme } = useApp();
  if (!systeme?.arret_urgence) return null;
  return (
    <div className="bg-encre text-white">
      <p className="mx-auto flex max-w-[1280px] flex-wrap items-center gap-3 px-4 py-2.5 text-[13.5px] sm:px-6">
        <span className="badge bg-white text-encre">Arrêt d'urgence</span>
        Aucune relance n'est préparée ni envoyée. Le validateur peut le lever dans Réglages.
      </p>
    </div>
  );
}
