"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { BoutonAction, Chargement, EnTetePage, Erreur } from "@/components/ui";
import { ouvrirFichier } from "@/lib/api";
import { useApp, useDonnees } from "@/lib/donnees";
import { date, TRANCHES } from "@/lib/libelles";
import type { Indicateurs } from "@/lib/types";

const GARDE_FOUS: Record<string, string> = {
  lignes_rejetees_a_l_import: "Lignes rejetées à l'import", doublons_detectes: "Doublons et conflits détectés",
  factures_a_verifier: "Factures mises en vérification", paiements_a_valider: "Paiements gardés pour décision humaine",
  relances_annulees_avant_envoi: "Relances annulées juste avant l'envoi", factures_payees_jamais_relancees: "Factures payées jamais relancées",
};

export default function Tableau() {
  const { notifier } = useApp();
  const [filtres, setFiltres] = useState({ debut: "", fin: "", client: "" });
  const params = useMemo(() => new URLSearchParams(Object.entries(filtres).filter(([, v]) => v) as [string, string][]), [filtres]);
  const { donnees: d, erreur, chargement } = useDonnees<Indicateurs>(`/api/tableau-de-bord?${params}`);
  const maj = (cle: keyof typeof filtres) => (e: React.ChangeEvent<HTMLInputElement>) => setFiltres({ ...filtres, [cle]: e.target.value });

  return (
    <div className="grid gap-6">
      <EnTetePage titre="Tableau de bord" sousTitre={d && <>Situation au {date(d.date_reference)}</>}>
        <BoutonAction variante="second" onClick={() => ouvrirFichier(`/api/tableau-de-bord/export.csv?${params}`, "tableau_de_bord.csv", true).catch(() => notifier("Export impossible", "erreur"))}>CSV</BoutonAction>
        <BoutonAction variante="second" onClick={() => ouvrirFichier(`/api/tableau-de-bord/export.pdf?${params}`, "tableau_de_bord.pdf").catch(() => notifier("Export impossible", "erreur"))}>PDF</BoutonAction>
      </EnTetePage>

      <form className="flex flex-wrap items-end gap-3 text-sm" onSubmit={(e) => e.preventDefault()} aria-label="Filtres">
        <label className="grid gap-1" htmlFor="t-debut"><span className="etiquette">Paiements depuis</span>
          <input id="t-debut" type="date" className="champ" value={filtres.debut} onChange={maj("debut")} /></label>
        <label className="grid gap-1" htmlFor="t-fin"><span className="etiquette">Jusqu'au</span>
          <input id="t-fin" type="date" className="champ" value={filtres.fin} onChange={maj("fin")} /></label>
        <label className="grid gap-1" htmlFor="t-client"><span className="etiquette">Code client</span>
          <input id="t-client" className="champ w-24" placeholder="C005" value={filtres.client} onChange={maj("client")} /></label>
      </form>

      {erreur && <Erreur message={erreur} />}
      {chargement && !d ? <Chargement /> : d && (
        <>
          <section className="grid gap-x-10 gap-y-4 carte px-5 py-5 sm:grid-cols-3" aria-label="Encours">
            <div><p className="etiquette">Échu à recouvrer</p>
              {Object.values(d.encours.total_echu).map((m) => <p key={m.affiche} className="chiffres text-3xl">{m.affiche}</p>)}
              <p className="text-sm text-doux"><span className="chiffres">{d.encours.factures_echues}</span> factures échues</p></div>
            <div><p className="etiquette">Total dû (y compris à échoir)</p>
              {Object.values(d.encours.total_du).map((m) => <p key={m.affiche} className="chiffres text-xl">{m.affiche}</p>)}</div>
            <div><p className="etiquette">Recouvré après relance</p>
              {Object.keys(d.efficacite.recouvre_apres_relance).length
                ? Object.values(d.efficacite.recouvre_apres_relance).map((m) => <p key={m.affiche} className="chiffres text-xl">{m.affiche}</p>)
                : <p className="chiffres text-xl">0 FCFA</p>}
              <p className="text-sm text-doux"><span className="chiffres">{d.efficacite.paiements_apres_relance}</span> paiement(s)
                {d.efficacite.delai_moyen_jours !== null && <>, en <span className="chiffres">{d.efficacite.delai_moyen_jours}</span> j en moyenne après la relance</>}</p></div>
          </section>

          <div className="grid items-start gap-8 lg:grid-cols-2">
            <Tranches d={d} />
            <section className="grid gap-2">
              <h2 className="text-[16px] font-semibold">Où agir en premier</h2>
              <ol className="grid">
                {d.top10.map((f, i) => (
                  <li key={f.facture_id} className="grid grid-cols-[1.8rem_minmax(0,1fr)_auto] items-baseline gap-x-3 border-b border-filet py-1.5 text-sm">
                    <span className="chiffres text-doux">{i + 1}</span>
                    <span className="min-w-0 truncate"><Link className="hover:underline" href={`/app/factures/${f.facture_id}`}>{f.client}</Link>
                      <span className="text-doux"> · {f.jours_retard} j</span></span>
                    <span className="chiffres text-right">{f.affiche}</span>
                  </li>
                ))}
              </ol>
            </section>
          </div>

          <div className="grid items-start gap-8 lg:grid-cols-3">
            <section className="grid gap-2">
              <h2 className="text-[16px] font-semibold">Charge de travail</h2>
              <dl className="grid gap-1 text-sm">
                <Ligne libelle="Messages à valider" valeur={d.relances.lots_a_valider} />
                <Ligne libelle="Relances envoyées" valeur={d.relances.par_statut.envoyee ?? 0} />
                <Ligne libelle="Relances validées, à envoyer" valeur={d.relances.par_statut.validee ?? 0} />
                <Ligne libelle="Relances en échec" valeur={d.relances.par_statut.echec ?? 0} />
              </dl>
            </section>
            <section className="grid gap-2">
              <h2 className="text-[16px] font-semibold">Efficacité</h2>
              <dl className="grid gap-1 text-sm">
                {Object.entries(d.efficacite.delai_moyen_par_etape).map(([e, j]) => <Ligne key={e} libelle={`Délai de paiement après ${e}`} valeur={`${j} j`} />)}
                <Ligne libelle="Promesses tenues" valeur={d.efficacite.promesses.tenues} />
                <Ligne libelle="Promesses non tenues" valeur={d.efficacite.promesses.non_tenues} />
                <Ligne libelle="Promesses en cours" valeur={d.efficacite.promesses.en_cours} />
              </dl>
            </section>
            <section className="grid gap-2">
              <h2 className="text-[16px] font-semibold">Ce qu'ont évité les garde-fous</h2>
              <dl className="grid gap-1 text-sm">
                {Object.entries(GARDE_FOUS).map(([k, v]) => <Ligne key={k} libelle={v} valeur={d.garde_fous[k] as number} />)}
              </dl>
            </section>
          </div>
        </>
      )}
    </div>
  );
}

function Ligne({ libelle, valeur }: { libelle: string; valeur: number | string }) {
  return <div className="flex justify-between gap-4 border-b border-filet py-1"><dt>{libelle}</dt><dd className="chiffres">{valeur}</dd></div>;
}

/** Barres horizontales, une seule teinte (l'encre) : la longueur porte le montant FCFA de chaque tranche. */
function Tranches({ d }: { d: Indicateurs }) {
  const lignes = d.tranches.filter((t) => t.tranche !== "non_echue");
  const montant = (t: Indicateurs["tranches"][number]) => t.montants.XOF?.montant ?? 0;
  const max = Math.max(1, ...lignes.map(montant));
  return (
    <section className="grid gap-2">
      <h2 className="text-[16px] font-semibold">Où se trouve le risque</h2>
      <p className="text-sm text-doux">Solde échu par ancienneté du retard (FCFA).</p>
      <table className="donnees">
        <thead className="sr-only"><tr><th>Ancienneté</th><th>Factures</th><th>Montant</th></tr></thead>
        <tbody>
          {lignes.map((t) => (
            <tr key={t.tranche} className="group" title={`${TRANCHES[t.tranche]} : ${t.nombre} facture(s), ${t.montants.XOF?.affiche ?? "0 FCFA"}`}>
              <td className="w-28 align-middle">{TRANCHES[t.tranche]}</td>
              <td className="align-middle">
                <div className="h-2.5 w-full bg-filet-2">
                  <div className="h-2.5 rounded-r bg-encre transition-opacity group-hover:opacity-80"
                       style={{ width: `${(montant(t) / max) * 100}%` }} />
                </div>
              </td>
              <td className="chiffres w-36 text-right align-middle">{t.montants.XOF?.affiche ?? "0 FCFA"}</td>
              <td className="chiffres w-10 text-right align-middle text-doux">{t.nombre}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
