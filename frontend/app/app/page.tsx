"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { BoutonAction, Chargement, Drapeaux, EnTetePage, Erreur, Etape, EtatVide, Jauge, Statut, Tuile } from "@/components/ui";
import { api, ouvrirFichier } from "@/lib/api";
import { useApp, useDonnees } from "@/lib/donnees";
import { date, TRANCHES } from "@/lib/libelles";
import type { FileDuJour, Priorite } from "@/lib/types";

type Filtres = { tranche: string; etape: string; validation: string; client: string; montant_min: string; montant_max: string };
const VIDE: Filtres = { tranche: "", etape: "", validation: "", client: "", montant_min: "", montant_max: "" };

export default function Aujourdhui() {
  const { utilisateur, systeme, agir } = useApp();
  const [filtres, setFiltres] = useState<Filtres>(VIDE);
  const requete = useMemo(() => {
    const p = new URLSearchParams(Object.entries(filtres).filter(([, v]) => v) as [string, string][]);
    return `/api/aujourdhui${p.size ? `?${p}` : ""}`;
  }, [filtres]);
  const { donnees, erreur, chargement, recharger } = useDonnees<FileDuJour>(requete);
  const [choisie, setChoisie] = useState<number | null>(null);
  const [voirExclues, setVoirExclues] = useState(false);
  const lecture = utilisateur.role === "auditeur";

  if (systeme && systeme.factures === 0) {
    return (
      <>
        <EnTetePage titre="Aujourd'hui" />
        <EtatVide titre="Aucune facture pour l'instant">
          <p>Importez vos factures depuis la page Import, ou chargez le jeu de démonstration : 138 lignes de factures volontairement
            piégées (doublons, erreurs, paiements ambigus) au 15 décembre 2026.</p>
          {!lecture && (
            <div className="mt-5 flex justify-center gap-2">
              <BoutonAction onClick={() => agir(() => api("/api/demo/charger", { methode: "POST" }), "Jeu de démonstration chargé").then(recharger)}>
                Charger le jeu de démonstration
              </BoutonAction>
              <Link href="/app/import" className="btn-sec">Importer un fichier</Link>
            </div>
          )}
        </EtatVide>
      </>
    );
  }

  const file = donnees?.file ?? [];
  const selection = file.find((p) => p.facture.id === choisie) ?? file[0];
  const r = donnees?.resume;

  return (
    <>
      <EnTetePage titre="Aujourd'hui" sousTitre="File priorisée et expliquée : chaque rang se justifie en une phrase.">
        {!lecture && (
          <BoutonAction onClick={() => agir(
            () => api<{ relances: number; lots: number; a_valider: number }>("/api/relances/preparer", { methode: "POST" }),
            (x) => x.relances ? `${x.relances} relances préparées en ${x.lots} messages, dont ${x.a_valider} à valider` : "Rien de nouveau à préparer aujourd'hui",
          ).then(recharger)}>
            Préparer les relances du jour
          </BoutonAction>
        )}
      </EnTetePage>

      {r && (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <Tuile libelle="À relancer aujourd'hui" valeur={r.a_relancer} note={`dont ${r.validation_humaine} à valider`} />
          <Tuile libelle="Validation humaine" valeur={r.validation_humaine} note="litiges, gros montants, R3 et plus" />
          <Tuile libelle="Écartées avec motif" valeur={r.exclues} note="payées, litiges, promesses…" />
          <Tuile libelle="Affichées" valeur={r.affichees} note={Object.values(filtres).some(Boolean) ? "selon vos filtres" : "aucun filtre"} accent />
        </div>
      )}

      <BarreFiltres filtres={filtres} onChange={setFiltres} />

      {erreur && <Erreur message={erreur} />}
      {chargement && !donnees ? <Chargement /> : file.length === 0 ? (
        <EtatVide titre="Aucune facture à relancer avec ces critères">
          {donnees?.resume.a_relancer ? "Modifiez les filtres pour en voir davantage." :
            "Les factures dues ont déjà une relance préparée, envoyée récemment, ou sont écartées."}
        </EtatVide>
      ) : (
        <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
          <div className="carte overflow-x-auto">
            <table className="donnees min-w-[720px]">
              <thead><tr><th className="w-10">#</th><th>Client</th><th>Facture</th><th className="text-right">Retard</th><th className="text-right">Solde</th><th>Étape</th><th>Décision</th></tr></thead>
              <tbody>
                {file.map((p) => <LigneFile key={p.facture.id} p={p} active={p.facture.id === selection?.facture.id} onChoisir={() => setChoisie(p.facture.id)} />)}
              </tbody>
            </table>
          </div>
          {selection && <Detail p={selection} />}
        </div>
      )}

      {donnees && donnees.exclues.length > 0 && (
        <section className="grid gap-3">
          <button type="button" className="btn-lien justify-self-start" aria-expanded={voirExclues} onClick={() => setVoirExclues((v) => !v)}>
            {voirExclues ? "Masquer" : "Voir"} les {donnees.exclues.length} factures écartées et leur motif
          </button>
          {voirExclues && (
            <div className="carte overflow-x-auto">
              <table className="donnees min-w-[640px]">
                <thead><tr><th>Facture</th><th>Client</th><th>Statut</th><th>Motif</th></tr></thead>
                <tbody>
                  {donnees.exclues.map((x) => (
                    <tr key={x.facture.id}>
                      <td><Link className="chiffres text-[12.5px] hover:text-vert" href={`/app/factures/${x.facture.id}`}>{x.facture.numero}</Link></td>
                      <td className="font-medium">{x.facture.nom_client}</td>
                      <td><Statut statut={x.facture.statut} /></td>
                      <td className="text-doux">{x.motif}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}
    </>
  );
}

function LigneFile({ p, active, onChoisir }: { p: Priorite; active: boolean; onChoisir: () => void }) {
  const f = p.facture;
  return (
    <tr onClick={onChoisir} aria-selected={active} tabIndex={0}
        onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onChoisir(); } }}
        className={`cursor-pointer ${active ? "!bg-vert-pale shadow-[inset_3px_0_0_#0e9f6e]" : ""}`}>
      <td className="text-doux">{p.rang}</td>
      <td><span className="font-semibold">{f.nom_client}</span><div className="mt-0.5"><Drapeaux drapeaux={f.drapeaux} /></div></td>
      <td className="chiffres text-[12.5px] text-doux">{f.numero}</td>
      <td className="text-right">{f.jours_retard} j</td>
      <td className="chiffres text-right font-medium">{f.solde_affiche}</td>
      <td><Etape etape={p.etape.etape} /></td>
      <td>{p.validation_humaine ? <span className="badge-encre">À valider</span> : <span className="badge-vert">Automatique</span>}</td>
    </tr>
  );
}

function Detail({ p }: { p: Priorite }) {
  const f = p.facture;
  const h = p.historique;
  // Points calculés par l'API ; l'interface ne fait que les afficher et dessiner la jauge.
  const facteurs = (["anciennete", "solde", "historique"] as const).map((k) => ({
    nom: { anciennete: "Ancienneté", solde: "Solde", historique: "Historique" }[k], points: p.points[k], max: p.points_max[k] }));
  return (
    <aside className="carte grid gap-4 p-5 xl:sticky xl:top-6 xl:max-h-[calc(100dvh-3rem)] xl:overflow-y-auto xl:overscroll-contain"
           aria-label="Pourquoi cette facture est ici" tabIndex={0}>
      <div>
        <p className="chiffres text-[11.5px] text-doux">{f.numero} · étape {p.etape.etape} · score {p.score.replace(".", ",")}</p>
        <h2 className="mt-1 text-[17px] font-semibold">{f.nom_client}</h2>
      </div>
      <p className="rounded-lg bg-fond px-3.5 py-3 leading-relaxed">{p.explication}</p>
      <div className="grid gap-2.5" aria-label="Détail du score">
        {facteurs.map((x) => (
          <div key={x.nom} className="grid grid-cols-[84px_minmax(0,1fr)_44px] items-center gap-3 text-[12.5px]">
            <span className="text-doux">{x.nom}</span><Jauge valeur={Number(x.points)} max={Number(x.max)} />
            <span className="text-right font-semibold tabulaire">{x.points.replace(".", ",")}</span>
          </div>
        ))}
      </div>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-[12.5px]">
        <div><dt className="text-doux">Solde</dt><dd className="font-semibold tabulaire">{f.solde_affiche}</dd></div>
        <div><dt className="text-doux">Ancienneté</dt><dd className="font-semibold">{f.tranche ? TRANCHES[f.tranche] : "-"}</dd></div>
        <div><dt className="text-doux">Échéance</dt><dd className="font-semibold tabulaire">{date(f.date_echeance)}</dd></div>
        <div><dt className="text-doux">Factures réglées</dt><dd className="font-semibold">{h.nb_reglees ? `${h.nb_reglees_en_retard} en retard sur ${h.nb_reglees}` : "aucune"}</dd></div>
        <div className="col-span-2"><dt className="text-doux">Référence de paiement</dt><dd className="chiffres">{f.reference_paiement}</dd></div>
      </dl>
      {p.validation_humaine && (
        <p className="rounded-lg border border-filet px-3.5 py-2.5 text-[12.5px]"><span className="font-semibold">Validation requise : </span>{p.raisons_validation.join(", ")}.</p>
      )}
      <div className="flex flex-wrap gap-2">
        <Link href={`/app/factures/${f.id}`} className="btn">Ouvrir la facture</Link>
        <BoutonAction variante="second" onClick={() => ouvrirFichier(`/api/factures/${f.id}/fiche-paiement.pdf`, `fiche_${f.numero}.pdf`)}>Fiche de paiement</BoutonAction>
      </div>
    </aside>
  );
}

function BarreFiltres({ filtres, onChange }: { filtres: Filtres; onChange: (f: Filtres) => void }) {
  const maj = (cle: keyof Filtres) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => onChange({ ...filtres, [cle]: e.target.value });
  const actif = Object.values(filtres).some(Boolean);
  return (
    <form className="flex flex-wrap items-end gap-2.5" onSubmit={(e) => e.preventDefault()} aria-label="Filtres">
      <label className="grid gap-1" htmlFor="f-tranche"><span className="etiquette">Ancienneté</span>
        <select id="f-tranche" className="champ" value={filtres.tranche} onChange={maj("tranche")}>
          <option value="">Toutes</option>
          {Object.entries(TRANCHES).filter(([k]) => k !== "non_echue").map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
      </label>
      <label className="grid gap-1" htmlFor="f-etape"><span className="etiquette">Étape</span>
        <select id="f-etape" className="champ" value={filtres.etape} onChange={maj("etape")}>
          <option value="">Toutes</option>{["R1", "R2", "R3", "R4", "R5"].map((e) => <option key={e}>{e}</option>)}
        </select>
      </label>
      <label className="grid gap-1" htmlFor="f-validation"><span className="etiquette">Décision</span>
        <select id="f-validation" className="champ" value={filtres.validation} onChange={maj("validation")}>
          <option value="">Toutes</option><option value="true">À valider</option><option value="false">Automatique</option>
        </select>
      </label>
      <label className="grid gap-1" htmlFor="f-client"><span className="etiquette">Code client</span>
        <input id="f-client" className="champ w-28" placeholder="C001" value={filtres.client} onChange={maj("client")} />
      </label>
      <label className="grid gap-1" htmlFor="f-min"><span className="etiquette">Solde min.</span>
        <input id="f-min" className="champ w-32 tabulaire" inputMode="numeric" placeholder="100 000" value={filtres.montant_min} onChange={maj("montant_min")} />
      </label>
      <label className="grid gap-1" htmlFor="f-max"><span className="etiquette">Solde max.</span>
        <input id="f-max" className="champ w-32 tabulaire" inputMode="numeric" value={filtres.montant_max} onChange={maj("montant_max")} />
      </label>
      {actif && <button type="button" className="btn-lien pb-2" onClick={() => onChange(VIDE)}>Effacer les filtres</button>}
    </form>
  );
}
