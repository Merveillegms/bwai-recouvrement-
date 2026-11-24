"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { Chargement, Drapeaux, EnTetePage, Erreur, EtatVide, Statut } from "@/components/ui";
import { useDonnees } from "@/lib/donnees";
import { date, DRAPEAUX, STATUTS, TRANCHES } from "@/lib/libelles";
import type { Facture } from "@/lib/types";

export default function Factures() {
  const [statut, setStatut] = useState("");
  const [drapeau, setDrapeau] = useState("");
  const [texte, setTexte] = useState("");
  const chemin = useMemo(() => {
    const p = new URLSearchParams();
    if (statut) p.set("statut", statut);
    if (drapeau) p.set("drapeau", drapeau);
    return `/api/factures${p.size ? `?${p}` : ""}`;
  }, [statut, drapeau]);
  const { donnees, erreur, chargement } = useDonnees<Facture[]>(chemin);
  const recherche = texte.trim().toLowerCase();
  const lignes = (donnees ?? []).filter((f) => !recherche || `${f.numero} ${f.nom_client} ${f.code_client}`.toLowerCase().includes(recherche));

  return (
    <div className="grid gap-5">
      <EnTetePage titre="Factures" sousTitre="Toutes les factures du registre, avec leur état calculé." />
      <form className="flex flex-wrap items-end gap-3 text-sm" onSubmit={(e) => e.preventDefault()}>
        <label className="grid gap-1" htmlFor="r-texte"><span className="etiquette">Rechercher</span>
          <input id="r-texte" className="champ w-60" placeholder="Numéro, client ou code" value={texte} onChange={(e) => setTexte(e.target.value)} />
        </label>
        <label className="grid gap-1" htmlFor="r-statut"><span className="etiquette">Statut</span>
          <select id="r-statut" className="champ" value={statut} onChange={(e) => setStatut(e.target.value)}>
            <option value="">Tous</option>{Object.entries(STATUTS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </label>
        <label className="grid gap-1" htmlFor="r-drapeau"><span className="etiquette">Signalement</span>
          <select id="r-drapeau" className="champ" value={drapeau} onChange={(e) => setDrapeau(e.target.value)}>
            <option value="">Aucun filtre</option>{Object.entries(DRAPEAUX).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </label>
        <span className="chiffres pb-1.5 text-encre-pale">{lignes.length} facture(s)</span>
      </form>
      {erreur && <Erreur message={erreur} />}
      {chargement && !donnees ? <Chargement /> : lignes.length === 0 ? <EtatVide titre="Aucune facture ne correspond" /> : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[820px] border-collapse text-sm">
            <thead><tr className="border-b-2 border-encre text-left">
              <th className="py-2 pr-4 font-medium">Facture</th><th className="pr-4 font-medium">Client</th>
              <th className="pr-4 font-medium">Échéance</th><th className="pr-4 font-medium">Retard</th>
              <th className="pr-4 text-right font-medium">Solde</th><th className="pr-4 font-medium">Statut</th><th className="font-medium">Signalements</th>
            </tr></thead>
            <tbody>
              {lignes.map((f) => (
                <tr key={f.id} className="border-b border-filet hover:bg-papier-fonce/50">
                  <td className="py-2 pr-4"><Link href={`/factures/${f.id}`} className="chiffres underline-offset-2 hover:underline">{f.numero}</Link></td>
                  <td className="pr-4">{f.nom_client}</td>
                  <td className="chiffres pr-4">{date(f.date_echeance)}</td>
                  <td className="pr-4 text-encre-pale">{f.tranche ? TRANCHES[f.tranche] : "-"}</td>
                  <td className="chiffres pr-4 text-right">{f.solde_affiche}</td>
                  <td className="pr-4"><Statut statut={f.statut} /></td>
                  <td><Drapeaux drapeaux={f.drapeaux} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
