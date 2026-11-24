"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { BoutonAction, Chargement, Drapeaux, EnTetePage, Erreur, Etape, EtatVide, Statut, Tampon } from "@/components/ui";
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
      <div className="grid gap-6">
        <EnTetePage titre="Aujourd'hui" />
        <EtatVide titre="Le registre est vide">
          <p>Importez vos factures dans « Import », ou chargez le jeu de démonstration : 138 lignes de factures piégées
            (doublons, erreurs, paiements ambigus) au 15 décembre 2026.</p>
          {!lecture && (
            <div className="mt-4 flex justify-center">
              <BoutonAction onClick={() => agir(() => api("/api/demo/charger", { methode: "POST" }),
                                                "Jeu de démonstration chargé").then(recharger)}>
                Charger le jeu de démonstration
              </BoutonAction>
            </div>
          )}
        </EtatVide>
      </div>
    );
  }

  const file = donnees?.file ?? [];
  const selection = file.find((p) => p.facture.id === choisie) ?? file[0];

  return (
    <div className="grid gap-5">
      <EnTetePage titre="Aujourd'hui"
                  sousTitre={donnees && <>
                    <span className="chiffres">{donnees.resume.a_relancer}</span> factures à relancer, dont{" "}
                    <span className="chiffres text-tampon">{donnees.resume.validation_humaine}</span> soumises à validation ·{" "}
                    <span className="chiffres">{donnees.resume.exclues}</span> écartées avec motif
                  </>}>
        {!lecture && (
          <BoutonAction onClick={() => agir(
            () => api<{ relances: number; lots: number; a_valider: number; ignorees: unknown[] }>("/api/relances/preparer", { methode: "POST" }),
            (r) => r.relances ? `${r.relances} relances préparées en ${r.lots} messages, dont ${r.a_valider} à valider`
                              : "Rien de nouveau à préparer aujourd'hui").then(recharger)}>
            Préparer les relances du jour
          </BoutonAction>
        )}
      </EnTetePage>

      <BarreFiltres filtres={filtres} onChange={setFiltres} />

      {erreur && <Erreur message={erreur} />}
      {chargement && !donnees ? <Chargement /> : file.length === 0 ? (
        <EtatVide titre="Aucune facture à relancer avec ces critères">
          {donnees?.resume.a_relancer ? "Modifiez les filtres pour en voir davantage." :
            "Les factures dues ont déjà une relance préparée, envoyée récemment, ou sont écartées (voir ci-dessous)."}
        </EtatVide>
      ) : (
        <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
          <ol className="registre border-y border-filet" aria-label="Factures à relancer, par priorité">
            {file.map((p) => <LigneFile key={p.facture.id} p={p} active={p.facture.id === selection?.facture.id}
                                        onChoisir={() => setChoisie(p.facture.id)} />)}
          </ol>
          {selection && <Detail p={selection} />}
        </div>
      )}

      {donnees && donnees.exclues.length > 0 && (
        <section className="grid gap-3">
          <button type="button" className="justify-self-start text-sm underline underline-offset-2"
                  aria-expanded={voirExclues} onClick={() => setVoirExclues((v) => !v)}>
            {voirExclues ? "Masquer" : "Voir"} les {donnees.exclues.length} factures écartées et pourquoi
          </button>
          {voirExclues && (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[640px] border-collapse text-sm">
                <thead><tr className="border-b border-encre text-left">
                  <th className="py-1.5 pr-4 font-medium">Facture</th><th className="pr-4 font-medium">Client</th>
                  <th className="pr-4 font-medium">Statut</th><th className="font-medium">Motif</th>
                </tr></thead>
                <tbody>
                  {donnees.exclues.map((x) => (
                    <tr key={x.facture.id} className="border-b border-filet align-top">
                      <td className="py-1.5 pr-4"><Link className="chiffres underline-offset-2 hover:underline" href={`/factures/${x.facture.id}`}>{x.facture.numero}</Link></td>
                      <td className="pr-4">{x.facture.nom_client}</td>
                      <td className="pr-4"><Statut statut={x.facture.statut} /></td>
                      <td className="text-encre-pale">{x.motif}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}
    </div>
  );
}

function LigneFile({ p, active, onChoisir }: { p: Priorite; active: boolean; onChoisir: () => void }) {
  const f = p.facture;
  return (
    <li>
      <button type="button" onClick={onChoisir} aria-pressed={active}
              className={`grid min-h-[3.75rem] w-full grid-cols-[2.4rem_minmax(0,1fr)_auto] items-center gap-x-3 px-3 py-2 text-left sm:grid-cols-[2.4rem_minmax(0,1fr)_auto_auto] ${active ? "bg-lavis" : "hover:bg-papier-fonce/60"}`}>
        <span className="chiffres text-sm text-encre-pale">{String(p.rang).padStart(2, "0")}</span>
        <span className="min-w-0">
          <span className="block truncate font-titre text-[1.05rem] font-medium">{f.nom_client}</span>
          <span className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-encre-pale">
            <span className="chiffres">{f.numero}</span>
            <span>{f.jours_retard} j de retard</span>
            {p.validation_humaine ? <Tampon>À valider</Tampon> : <span>envoi automatique</span>}
            <Drapeaux drapeaux={f.drapeaux} />
          </span>
        </span>
        <span className="chiffres text-right">{f.solde_affiche}</span>
        <span className="hidden sm:block"><Etape etape={p.etape.etape} /></span>
      </button>
    </li>
  );
}

function Detail({ p }: { p: Priorite }) {
  const f = p.facture;
  const h = p.historique;
  return (
    <aside className="grid gap-4 border border-filet bg-[#f8f5ec] p-5 lg:sticky lg:top-32" aria-label="Pourquoi cette facture est ici">
      <div>
        <p className="chiffres text-xs text-encre-pale">{f.numero} · échéance {date(f.date_echeance)} · réf. {f.reference_paiement}</p>
        <h2 className="text-2xl font-semibold">{f.nom_client}</h2>
      </div>
      <p className="font-titre text-lg leading-snug">{p.explication}</p>
      <ul className="chiffres grid gap-1 border-y border-filet py-3 text-xs">
        {p.detail.map((ligne) => <li key={ligne}>{ligne}</li>)}
      </ul>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
        <div><dt className="etiquette">Solde</dt><dd className="chiffres">{f.solde_affiche}</dd></div>
        <div><dt className="etiquette">Tranche</dt><dd>{f.tranche ? TRANCHES[f.tranche] : "-"}</dd></div>
        <div><dt className="etiquette">Factures réglées</dt><dd>{h.nb_reglees ? `${h.nb_reglees_en_retard} en retard sur ${h.nb_reglees}` : "aucune"}</dd></div>
        <div><dt className="etiquette">Retard moyen de règlement</dt><dd>{h.nb_reglees_en_retard ? `${h.retard_moyen_reglement} j` : "-"}</dd></div>
      </dl>
      {p.validation_humaine && (
        <p className="text-sm"><span className="font-semibold text-tampon">Validation humaine requise : </span>{p.raisons_validation.join(", ")}.</p>
      )}
      <div className="flex flex-wrap gap-2">
        <Link href={`/factures/${f.id}`} className="bouton bouton-second">Ouvrir la facture</Link>
        <BoutonAction variante="second" onClick={() => ouvrirFichier(`/api/factures/${f.id}/fiche-paiement.pdf`, `fiche_${f.numero}.pdf`)}>
          Fiche de paiement
        </BoutonAction>
      </div>
    </aside>
  );
}

function BarreFiltres({ filtres, onChange }: { filtres: Filtres; onChange: (f: Filtres) => void }) {
  const maj = (cle: keyof Filtres) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    onChange({ ...filtres, [cle]: e.target.value });
  const actif = Object.values(filtres).some(Boolean);
  return (
    <form className="flex flex-wrap items-end gap-3 text-sm" onSubmit={(e) => e.preventDefault()} aria-label="Filtres">
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
        <input id="f-client" className="champ w-24" placeholder="C001" value={filtres.client} onChange={maj("client")} />
      </label>
      <label className="grid gap-1" htmlFor="f-min"><span className="etiquette">Solde min.</span>
        <input id="f-min" className="champ chiffres w-28" inputMode="numeric" placeholder="100 000" value={filtres.montant_min} onChange={maj("montant_min")} />
      </label>
      <label className="grid gap-1" htmlFor="f-max"><span className="etiquette">Solde max.</span>
        <input id="f-max" className="champ chiffres w-28" inputMode="numeric" value={filtres.montant_max} onChange={maj("montant_max")} />
      </label>
      {actif && <button type="button" className="pb-1.5 underline underline-offset-2" onClick={() => onChange(VIDE)}>Effacer les filtres</button>}
    </form>
  );
}
