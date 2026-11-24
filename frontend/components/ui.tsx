"use client";

import { useState, type ReactNode } from "react";
import { DRAPEAUX, STATUTS } from "@/lib/libelles";

/** Bouton d'action : désactivé pendant l'appel (jamais de double envoi), libellé explicite. */
export function BoutonAction({ onClick, children, variante = "principal", disabled, titre }: {
  onClick: () => Promise<unknown> | void; children: ReactNode; variante?: "principal" | "second" | "encre";
  disabled?: boolean; titre?: string;
}) {
  const [occupe, setOccupe] = useState(false);
  const classe = { principal: "btn", second: "btn-sec", encre: "btn-encre" }[variante];
  return (
    <button type="button" className={classe} disabled={disabled || occupe} title={titre} aria-busy={occupe}
            onClick={async () => { setOccupe(true); try { await onClick(); } finally { setOccupe(false); } }}>
      {occupe && <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-t-transparent" aria-hidden="true" />}
      {children}
    </button>
  );
}

const BADGES_STATUT: Record<string, string> = {
  payee: "badge-vert", cloturee: "badge", en_litige: "badge-contour", suspendue: "badge-contour",
  echue: "badge-encre", partiellement_payee: "badge-encre", a_echoir: "badge",
};

export function Statut({ statut }: { statut: string }) {
  return <span className={BADGES_STATUT[statut] ?? "badge"}>{STATUTS[statut] ?? statut}</span>;
}

export function Etape({ etape }: { etape: string }) {
  return <span className="chiffres rounded-md bg-filet-2 px-1.5 py-0.5 text-[11.5px]">{etape}</span>;
}

export function Drapeaux({ drapeaux }: { drapeaux: string[] }) {
  if (!drapeaux.length) return null;
  return <span className="flex flex-wrap gap-1.5">{drapeaux.map((d) => <span key={d} className="badge">{DRAPEAUX[d] ?? d}</span>)}</span>;
}

export function EnTetePage({ titre, sousTitre, children }: { titre: string; sousTitre?: ReactNode; children?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
      <div className="min-w-0">
        <h1 className="text-[22px] font-semibold leading-tight">{titre}</h1>
        {sousTitre && <p className="mt-1 text-[13.5px] text-doux">{sousTitre}</p>}
      </div>
      {children && <div className="flex flex-wrap items-center gap-2">{children}</div>}
    </div>
  );
}

export function Tuile({ libelle, valeur, note, accent }: { libelle: string; valeur: ReactNode; note?: ReactNode; accent?: boolean }) {
  return (
    <div className="tuile">
      <span className="text-[12px] text-doux">{libelle}</span>
      <span className={`font-titre text-[22px] font-bold tabulaire ${accent ? "text-vert" : ""}`}>{valeur}</span>
      {note && <span className="text-[11.5px] text-doux">{note}</span>}
    </div>
  );
}

export function EtatVide({ titre, children }: { titre: string; children?: ReactNode }) {
  return (
    <div className="carte grid justify-items-center gap-2 px-6 py-12 text-center">
      <span className="grid h-10 w-10 place-items-center rounded-full bg-vert-pale text-vert" aria-hidden="true">✓</span>
      <p className="font-titre text-[16px] font-semibold">{titre}</p>
      {children && <div className="max-w-prose text-[13.5px] text-doux">{children}</div>}
    </div>
  );
}

export function Erreur({ message }: { message: string }) {
  return <p role="alert" className="alerte"><span className="font-bold">!</span>{message}</p>;
}

export function Chargement() {
  return (
    <div className="grid gap-2" aria-label="Chargement">
      {[0, 1, 2].map((i) => <div key={i} className="h-12 animate-pulse rounded-xl bg-filet-2" />)}
    </div>
  );
}

/** Décision sensible : motif obligatoire saisi dans la page (pas de boîte de dialogue du navigateur). */
export function DecisionMotivee({ libelle, action, variante = "second", placeholder, onValider }: {
  libelle: string; action: string; variante?: "principal" | "second" | "encre"; placeholder?: string;
  onValider: (motif: string) => Promise<unknown>;
}) {
  const [ouvert, setOuvert] = useState(false);
  const [motif, setMotif] = useState("");
  const id = `motif-${libelle.replace(/\W/g, "")}`;
  if (!ouvert) return <button type="button" className={variante === "encre" ? "btn-encre" : "btn-sec"} onClick={() => setOuvert(true)}>{libelle}</button>;
  return (
    <form className="flex w-full flex-wrap items-center gap-2" onSubmit={(e) => e.preventDefault()}>
      <label className="sr-only" htmlFor={id}>Motif</label>
      <input id={id} className="champ flex-1" autoFocus placeholder={placeholder ?? "Motif (obligatoire)"}
             value={motif} onChange={(e) => setMotif(e.target.value)} />
      <BoutonAction variante={variante === "principal" ? "principal" : "encre"} disabled={!motif.trim()}
                    onClick={async () => { await onValider(motif.trim()); setOuvert(false); setMotif(""); }}>
        {action}
      </BoutonAction>
      <button type="button" className="btn-sec" onClick={() => setOuvert(false)}>Annuler</button>
    </form>
  );
}

/** Jauge horizontale : la longueur porte la valeur (une seule teinte). */
export function Jauge({ valeur, max }: { valeur: number; max: number }) {
  const largeur = max > 0 ? Math.max(0, Math.min(100, (valeur / max) * 100)) : 0;
  return (
    <span className="block h-1.5 overflow-hidden rounded-full bg-filet-2">
      <span className="block h-full rounded-full bg-vert transition-[width] duration-700" style={{ width: `${largeur}%` }} />
    </span>
  );
}
