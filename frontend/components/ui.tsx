"use client";

import { useState, type ReactNode } from "react";
import { DRAPEAUX, STATUTS } from "@/lib/libelles";

/** Bouton d'action : désactivé pendant l'appel (pas de double envoi), libellé explicite de ce qui se passe. */
export function BoutonAction({ onClick, children, variante = "principal", disabled, titre }: {
  onClick: () => Promise<unknown> | void; children: ReactNode; variante?: "principal" | "second" | "danger";
  disabled?: boolean; titre?: string;
}) {
  const [occupe, setOccupe] = useState(false);
  const classe = variante === "second" ? "bouton bouton-second" : variante === "danger" ? "bouton bouton-danger" : "bouton";
  return (
    <button type="button" className={classe} disabled={disabled || occupe} title={titre} aria-busy={occupe}
            onClick={async () => {
              setOccupe(true);
              try { await onClick(); } finally { setOccupe(false); }
            }}>
      {children}
    </button>
  );
}

const TONS_STATUT: Record<string, string> = {
  payee: "text-ok", cloturee: "text-encre-pale", en_litige: "text-tampon", suspendue: "text-alerte",
  echue: "text-encre", partiellement_payee: "text-encre", a_echoir: "text-encre-pale",
};

export function Statut({ statut }: { statut: string }) {
  return <span className={`text-sm italic ${TONS_STATUT[statut] ?? ""}`}>{STATUTS[statut] ?? statut}</span>;
}

/** Tampon encré : réservé à ce qui exige une décision ou bloque. */
export function Tampon({ children, ton = "tampon" }: { children: ReactNode; ton?: "tampon" | "ok" | "alerte" | "encre" }) {
  const couleur = { tampon: "text-tampon", ok: "text-ok", alerte: "text-alerte", encre: "text-encre" }[ton];
  return <span className={`tampon ${couleur}`}>{children}</span>;
}

export function Etape({ etape }: { etape: string }) {
  return <span className="chiffres border border-encre px-1.5 text-xs">{etape}</span>;
}

export function Drapeaux({ drapeaux }: { drapeaux: string[] }) {
  if (!drapeaux.length) return null;
  return (
    <span className="flex flex-wrap gap-x-2 text-xs text-encre-pale">
      {drapeaux.map((d) => <span key={d}>· {DRAPEAUX[d] ?? d}</span>)}
    </span>
  );
}

export function EnTetePage({ titre, sousTitre, children }: { titre: string; sousTitre?: ReactNode; children?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-3 border-b border-filet pb-4">
      <div className="min-w-0">
        <h1 className="text-3xl font-semibold">{titre}</h1>
        {sousTitre && <p className="mt-1 text-encre-pale">{sousTitre}</p>}
      </div>
      {children && <div className="flex flex-wrap items-center gap-2">{children}</div>}
    </div>
  );
}

export function EtatVide({ titre, children }: { titre: string; children?: ReactNode }) {
  return (
    <div className="border border-dashed border-filet px-6 py-10 text-center">
      <p className="font-titre text-xl">{titre}</p>
      {children && <div className="mx-auto mt-2 max-w-prose text-encre-pale">{children}</div>}
    </div>
  );
}

export function Erreur({ message }: { message: string }) {
  return <p role="alert" className="border-2 border-tampon px-4 py-3 text-tampon">{message}</p>;
}

export function Chargement() {
  return <p className="etiquette py-6">Chargement du registre…</p>;
}

/** Saisie d'un motif obligatoire avant une décision sensible (pas de boîte de dialogue du navigateur). */
export function DecisionMotivee({ libelle, action, variante = "second", placeholder, onValider }: {
  libelle: string; action: string; variante?: "principal" | "second" | "danger"; placeholder?: string;
  onValider: (motif: string) => Promise<unknown>;
}) {
  const [ouvert, setOuvert] = useState(false);
  const [motif, setMotif] = useState("");
  if (!ouvert) return <button type="button" className={`bouton ${variante === "danger" ? "bouton-danger" : "bouton-second"}`} onClick={() => setOuvert(true)}>{libelle}</button>;
  return (
    <form className="flex w-full flex-wrap items-center gap-2" onSubmit={(e) => e.preventDefault()}>
      <label className="sr-only" htmlFor={`motif-${libelle}`}>Motif</label>
      <input id={`motif-${libelle}`} className="champ flex-1" autoFocus placeholder={placeholder ?? "Motif (obligatoire)"}
             value={motif} onChange={(e) => setMotif(e.target.value)} />
      <BoutonAction variante={variante} disabled={!motif.trim()} onClick={async () => { await onValider(motif.trim()); setOuvert(false); setMotif(""); }}>
        {action}
      </BoutonAction>
      <button type="button" className="bouton bouton-second" onClick={() => setOuvert(false)}>Annuler</button>
    </form>
  );
}
