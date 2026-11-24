"use client";

import { useParams } from "next/navigation";
import { useState } from "react";
import { BoutonAction, Chargement, DecisionMotivee, Drapeaux, Erreur, Statut } from "@/components/ui";
import { api, ouvrirFichier } from "@/lib/api";
import { useApp, useDonnees } from "@/lib/donnees";
import { date, heure, TRANCHES } from "@/lib/libelles";
import type { Evenement, Facture, Paiement } from "@/lib/types";

type Detail = Facture & { paiements: (Paiement & { montant_affiche?: string })[]; avoirs: { id: number; montant: number; motif: string; date_avoir: string }[] };
type Pourquoi = { dans_la_file: boolean; explication?: string; detail?: string[]; motif?: string; rang?: number };

export default function FicheFacture() {
  const { id } = useParams<{ id: string }>();
  const { utilisateur, systeme, agir } = useApp();
  const fiche = useDonnees<Detail>(`/api/factures/${id}`);
  const frise = useDonnees<{ evenements: Evenement[] }>(`/api/factures/${id}/frise`);
  const pourquoi = useDonnees<Pourquoi>(`/api/factures/${id}/priorite`);
  const tout = async () => { await Promise.all([fiche.recharger(), frise.recharger(), pourquoi.recharger()]); };
  const f = fiche.donnees;
  const role = utilisateur.role;

  if (fiche.erreur) return <Erreur message={fiche.erreur} />;
  if (!f) return <Chargement />;
  const action = (chemin: string, corps: object, succes: string) => agir(() => api(chemin, { corps }), succes).then(tout);

  return (
    <div className="grid gap-6">
      <div className="flex flex-wrap items-end justify-between gap-4 border-b border-filet pb-4">
        <div>
          <p className="chiffres text-sm text-doux">{f.numero} · {f.code_client} · réf. de paiement {f.reference_paiement}</p>
          <h1 className="text-[22px] font-semibold">{f.nom_client}</h1>
          <div className="mt-1 flex flex-wrap items-center gap-3"><Statut statut={f.statut} /><Drapeaux drapeaux={f.drapeaux} />
            {f.en_litige && <span className="badge-encre">Litige</span>}{f.suspendue && <span className="badge-contour">Suspendue</span>}</div>
        </div>
        {f.solde > 0 && (
          <BoutonAction variante="second" onClick={() => ouvrirFichier(`/api/factures/${f.id}/fiche-paiement.pdf`, `fiche_${f.numero}.pdf`)}>
            Fiche de paiement (PDF)
          </BoutonAction>
        )}
      </div>

      <div className="grid items-start gap-8 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
        <section className="grid gap-5">
          <dl className="grid grid-cols-2 gap-x-6 gap-y-3 carte px-5 py-4 sm:grid-cols-3">
            {[["Montant TTC", f.montant_ttc_affiche], ["Déjà réglé", f.total_paye_affiche], ["Avoirs", f.total_avoirs_affiche],
              ["Reste à payer", f.solde_affiche], ["Émise le", date(f.date_emission)], ["Échéance", date(f.date_echeance)],
              ["Retard", `${f.jours_retard} j`], ["Ancienneté", f.tranche ? TRANCHES[f.tranche] : "-"], ["Version", String(f.version)]]
              .map(([k, v]) => <div key={k}><dt className="etiquette">{k}</dt><dd className={`chiffres ${k === "Reste à payer" ? "text-lg font-medium" : ""}`}>{v}</dd></div>)}
          </dl>
          {f.trop_percu > 0 && <p className="text-sm text-encre">Trop-perçu de {f.trop_percu_affiche} à restituer ou imputer.</p>}
          {f.motif_cloture && <p className="text-sm">Clôturée : {f.motif_cloture}</p>}

          {pourquoi.donnees && (
            <div className="grid gap-2 carte p-4">
              <span className="etiquette">Pourquoi cette facture {pourquoi.donnees.dans_la_file ? "est dans la file du jour" : "n'est pas relancée"}</span>
              <p className="leading-relaxed">{pourquoi.donnees.dans_la_file ? pourquoi.donnees.explication : pourquoi.donnees.motif}</p>
              {pourquoi.donnees.detail && <ul className="chiffres grid gap-0.5 text-xs text-doux">{pourquoi.donnees.detail.map((d) => <li key={d}>{d}</li>)}</ul>}
            </div>
          )}

          {f.paiements.length > 0 && (
            <div className="grid gap-2">
              <h2 className="text-[15px] font-semibold">Paiements</h2>
              <ul className="grid gap-1 text-sm">
                {f.paiements.map((p) => (
                  <li key={p.id} className="flex flex-wrap justify-between gap-2 border-b border-filet py-1">
                    <span className="chiffres">{date(p.date_paiement)} · {p.id_transaction}</span>
                    <span className="chiffres">{p.montant_affiche ?? p.montant}</span>
                    <span className="text-doux">{p.statut_rapprochement === "rapproche" ? "rapproché" : "proposé, à valider"}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {role !== "auditeur" && f.statut !== "cloturee" && (
            <Actions f={f} role={role} dateSimulee={!!systeme?.date_simulee} action={action} tout={tout} />
          )}
        </section>

        <section className="grid gap-3">
          <h2 className="text-[15px] font-semibold">Historique</h2>
          {frise.donnees ? (
            <ol className="grid border-l-2 border-encre">
              {frise.donnees.evenements.map((e) => (
                <li key={e.id} className="relative grid gap-0.5 py-2 pl-5">
                  <span className={`absolute -left-[5px] top-3.5 h-2 w-2 rounded-full ${e.type_acteur === "humain" ? "bg-vert" : "bg-encre"}`} aria-hidden="true" />
                  <span className="chiffres text-xs text-doux">{heure(e.horodatage)} · {e.acteur}{e.type_acteur === "humain" ? "" : ` (${e.type_acteur})`}</span>
                  <span className="text-sm">{e.libelle}</span>
                </li>
              ))}
            </ol>
          ) : <Chargement />}
          <p className="text-xs text-doux">Point rouge : décision humaine. Point bleu nuit : règle appliquée par le système.</p>
        </section>
      </div>
    </div>
  );
}

function Actions({ f, role, dateSimulee, action, tout }: { f: Facture; role: string; dateSimulee: boolean;
  action: (chemin: string, corps: object, succes: string) => Promise<void>; tout: () => Promise<void> }) {
  const { agir } = useApp();
  const [promesse, setPromesse] = useState("");
  const [avoir, setAvoir] = useState("");
  const [motifAvoir, setMotifAvoir] = useState("");
  const validateur = role === "validateur";
  return (
    <div className="grid gap-4 border-t border-filet pt-4">
      <h2 className="text-[15px] font-semibold">Actions</h2>

      <div className="grid gap-2">
        <span className="etiquette">Réponse du client</span>
        <div className="flex flex-wrap items-center gap-2">
          <label className="sr-only" htmlFor="promesse">Date promise</label>
          <input id="promesse" type="date" className="champ chiffres" value={promesse} onChange={(e) => setPromesse(e.target.value)} />
          <BoutonAction variante="second" disabled={!promesse}
                        onClick={() => action(`/api/clients/${f.client_id}/reponses`, { type: "promesse", facture_id: f.id, date_promise: promesse },
                                              "Promesse enregistrée : relances suspendues jusqu'à cette date")}>
            Promesse de paiement
          </BoutonAction>
          <BoutonAction variante="second" onClick={() => action(`/api/clients/${f.client_id}/reponses`, { type: "paiement_annonce", facture_id: f.id },
                                                                  "Paiement annoncé : relances suspendues 3 jours")}>
            Paiement annoncé
          </BoutonAction>
          <BoutonAction variante="second" onClick={() => action(`/api/clients/${f.client_id}/reponses`, { type: "injoignable", facture_id: f.id },
                                                                  "Client injoignable : noté au journal")}>
            Injoignable
          </BoutonAction>
        </div>
      </div>

      <div className="flex flex-wrap gap-2">
        {!f.en_litige && <DecisionMotivee libelle="Déclarer un litige" action="Déclarer" variante="encre"
                                          onValider={(m) => action(`/api/factures/${f.id}/litige`, { motif: m }, "Litige déclaré : plus aucune relance automatique")} />}
        {f.en_litige && validateur && <DecisionMotivee libelle="Lever le litige" action="Lever"
                                                        onValider={(m) => action(`/api/factures/${f.id}/lever-litige`, { motif: m }, "Litige levé")} />}
        {!f.suspendue && <DecisionMotivee libelle="Suspendre les relances" action="Suspendre"
                                          onValider={(m) => action(`/api/factures/${f.id}/suspendre`, { motif: m }, "Relances suspendues")} />}
        {f.suspendue && <DecisionMotivee libelle="Reprendre les relances" action="Reprendre"
                                         onValider={(m) => action(`/api/factures/${f.id}/reprendre`, { motif: m }, "Relances reprises")} />}
        {f.a_verifier && <BoutonAction variante="second" onClick={() => action(`/api/factures/${f.id}/confirmer`, { motif: "Vérifiée" }, "Doute levé")}>Confirmer la facture</BoutonAction>}
      </div>

      {validateur && f.solde > 0 && (
        <div className="grid gap-2">
          <span className="etiquette">Décisions du validateur</span>
          <div className="flex flex-wrap items-center gap-2">
            <label className="sr-only" htmlFor="avoir">Montant de l'avoir</label>
            <input id="avoir" className="champ chiffres w-32" inputMode="decimal" placeholder="Montant" value={avoir} onChange={(e) => setAvoir(e.target.value)} />
            <label className="sr-only" htmlFor="motif-avoir">Motif de l'avoir</label>
            <input id="motif-avoir" className="champ flex-1" placeholder="Motif de l'avoir" value={motifAvoir} onChange={(e) => setMotifAvoir(e.target.value)} />
            <BoutonAction variante="second" disabled={!avoir || !motifAvoir.trim()}
                          onClick={async () => { await action(`/api/factures/${f.id}/avoirs`, { montant: avoir, motif: motifAvoir }, "Avoir émis"); setAvoir(""); setMotifAvoir(""); }}>
              Émettre un avoir
            </BoutonAction>
          </div>
          <DecisionMotivee libelle="Passer en perte" action="Confirmer le passage en perte" variante="encre"
                           onValider={(m) => action(`/api/factures/${f.id}/perte`, { motif: m }, "Facture passée en perte et clôturée")} />
        </div>
      )}

      {dateSimulee && f.solde > 0 && (
        <div className="grid gap-1 border border-dashed border-filet p-3">
          <span className="etiquette">Démonstration</span>
          <div><BoutonAction variante="second" onClick={() => agir(() => api("/api/demo/paiement", { corps: { facture_id: f.id } }),
                                                                     "Le client a payé par mobile money en citant la référence").then(tout)}>
            Simuler le paiement du client
          </BoutonAction></div>
        </div>
      )}
    </div>
  );
}
