"use client";

import { useState } from "react";
import { BoutonAction, DecisionMotivee, EnTetePage } from "@/components/ui";
import { api } from "@/lib/api";
import { useApp, useDonnees } from "@/lib/donnees";
import { dateLongue } from "@/lib/libelles";
import type { EtatIA, FileDuJour } from "@/lib/types";

type Simulation = { facture_id: number; numero: string; client: string; rang: number; ancien_rang: number; score: string; ancien_score: string };

export default function Reglages() {
  const { utilisateur, systeme, agir } = useApp();
  const validateur = utilisateur.role === "validateur";
  const lecture = utilisateur.role === "auditeur";
  const file = useDonnees<FileDuJour>("/api/aujourdhui");
  const actuels = file.donnees?.file[0]?.poids ?? null;
  const [poids, setPoids] = useState({ anciennete: "0.5", solde: "0.3", historique: "0.2" });
  const [simulation, setSimulation] = useState<Simulation[] | null>(null);
  const [jours, setJours] = useState("7");

  return (
    <div className="grid gap-8">
      <EnTetePage titre="Réglages" />

      <section className="grid gap-3 carte p-5">
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="text-[16px] font-semibold">Arrêt d'urgence</h2>
          {systeme?.arret_urgence ? <span className="badge-encre">Actif</span> : <span className="text-sm text-vert">inactif : les relances fonctionnent</span>}
        </div>
        <p className="max-w-prose text-sm text-doux">Bloque immédiatement toute préparation et tout envoi de relance, par exemple après une erreur de tarif. Réservé au validateur, motif obligatoire, inscrit au journal.</p>
        {validateur && (systeme?.arret_urgence ? (
          <div><BoutonAction onClick={() => agir(() => api("/api/arret-urgence", { corps: { actif: false } }), "Arrêt d'urgence levé")}>Lever l'arrêt d'urgence</BoutonAction></div>
        ) : (
          <DecisionMotivee libelle="Tout arrêter maintenant" action="Confirmer l'arrêt" variante="encre" placeholder="Motif de l'arrêt"
                           onValider={(motif) => agir(() => api("/api/arret-urgence", { corps: { actif: true, motif } }), "Arrêt d'urgence activé")} />
        ))}
      </section>

      <section className="grid gap-3">
        <h2 className="text-[16px] font-semibold">Poids de la priorité</h2>
        <p className="max-w-prose text-sm text-doux">
          Le score combine l'ancienneté du retard, le solde et l'historique de règlement du client. Simulez d'autres poids
          pour voir l'effet sur le classement avant de les enregistrer. Leur somme doit faire 1.
          {actuels && <> Poids actuels : ancienneté {actuels.anciennete}, solde {actuels.solde}, historique {actuels.historique}.</>}
        </p>
        <form className="flex flex-wrap items-end gap-3 text-sm" onSubmit={(e) => e.preventDefault()}>
          {(["anciennete", "solde", "historique"] as const).map((k) => (
            <label key={k} className="grid gap-1" htmlFor={`p-${k}`}><span className="etiquette">{k === "anciennete" ? "Ancienneté" : k === "solde" ? "Solde" : "Historique"}</span>
              <input id={`p-${k}`} className="champ chiffres w-24" inputMode="decimal" value={poids[k]} onChange={(e) => setPoids({ ...poids, [k]: e.target.value })} />
            </label>
          ))}
          <BoutonAction variante="second" onClick={async () => { const r = await agir(() => api<Simulation[]>("/api/priorisation/simulation", { corps: poids })); if (r) setSimulation(r); }}>
            Simuler
          </BoutonAction>
          {validateur && <BoutonAction onClick={() => agir(() => api("/api/parametres/poids_priorite", { methode: "PUT", corps: poids }), "Poids enregistrés").then(() => file.recharger())}>Enregistrer</BoutonAction>}
        </form>
        {simulation && (
          <div className="carte overflow-x-auto">
            <table className="donnees min-w-[560px]">
              <thead><tr>
                <th>Nouveau rang</th><th>Avant</th><th>Facture</th>
                <th>Client</th><th className="text-right">Score</th>
              </tr></thead>
              <tbody>
                {simulation.slice(0, 15).map((s) => (
                  <tr key={s.facture_id} className="border-b border-filet">
                    <td className="chiffres">{s.rang}</td>
                    <td className="chiffres text-doux">{s.ancien_rang}{s.rang < s.ancien_rang ? " ↑" : s.rang > s.ancien_rang ? " ↓" : ""}</td>
                    <td className="chiffres">{s.numero}</td><td>{s.client}</td>
                    <td className="chiffres text-right">{s.ancien_score} → {s.score}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <SectionIA validateur={validateur} />

      {systeme?.date_simulee && !lecture && (
        <section className="grid gap-3 border border-dashed border-filet p-5">
          <h2 className="text-[16px] font-semibold">Démonstration</h2>
          <p className="text-sm text-doux">Date métier simulée : {dateLongue(systeme.date_du_jour)}. Faire passer le temps recalcule les statuts et fait avancer les étapes de relance.</p>
          <form className="flex flex-wrap items-end gap-3 text-sm" onSubmit={(e) => e.preventDefault()}>
            <label className="grid gap-1" htmlFor="jours"><span className="etiquette">Jours</span>
              <input id="jours" className="champ chiffres w-20" inputMode="numeric" value={jours} onChange={(e) => setJours(e.target.value)} />
            </label>
            <BoutonAction variante="second" onClick={() => agir(() => api<{ date: string }>("/api/demo/avancer", { corps: { jours: Number(jours) } }),
                                                                  (r) => `Nous sommes le ${dateLongue(r.date)}`)}>
              Avancer l'horloge
            </BoutonAction>
            <BoutonAction variante="second" onClick={() => agir(() => api<{ preparation: { relances: number }; envoi: { envoyes: number } }>("/api/demo/executer", { methode: "POST" }),
                                                                  (r) => `${r.preparation.relances} relances préparées, ${r.envoi.envoyes} messages envoyés`)}>
              Préparer et envoyer la file du jour
            </BoutonAction>
          </form>
        </section>
      )}
    </div>
  );
}

function SectionIA({ validateur }: { validateur: boolean }) {
  const { agir } = useApp();
  const ia = useDonnees<EtatIA>("/api/ia/etat");
  const d = ia.donnees;
  if (!d) return null;
  const appels = Object.values(d.redaction.appels).reduce((a, b) => a + b, 0);
  return (
    <section className="carte grid gap-4 p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="text-[16px] font-semibold">IA encadrée</h2>
          {d.active ? <span className="badge-vert">Active</span> : <span className="badge">Désactivée</span>}
        </div>
        {validateur && (
          <BoutonAction variante={d.active ? "second" : "principal"}
                        onClick={() => agir(() => api("/api/ia/activer", { corps: { actif: !d.active } }), d.active ? "IA désactivée : tout continue sans elle" : "IA activée").then(ia.recharger)}>
            {d.active ? "Désactiver l'IA" : "Activer l'IA"}
          </BoutonAction>
        )}
      </div>
      <p className="max-w-prose text-[13.5px] text-doux">L'IA ne calcule rien et ne décide de rien de sensible. Désactivée, l'outil fonctionne exactement de la même façon avec les gabarits fixes et la saisie manuelle des réponses.</p>
      <dl className="grid gap-4 sm:grid-cols-2">
        <div className="rounded-lg bg-fond p-4">
          <dt className="etiquette">Rédaction des messages</dt>
          <dd className="mt-1 text-[13.5px]">{d.redaction.configuree
            ? <>Modèle <b>{d.redaction.modele}</b> ({d.redaction.fournisseur}). {appels} appel(s) : {d.redaction.appels.accepte ?? 0} accepté(s), {(d.redaction.appels.rejete ?? 0) + (d.redaction.appels.erreur ?? 0)} replié(s) sur le gabarit.</>
            : <>Aucune clé configurée : ajoutez GEMINI_API_KEY dans le fichier .env pour activer la rédaction.</>}</dd>
        </div>
        <div className="rounded-lg bg-fond p-4">
          <dt className="etiquette">Classification des réponses</dt>
          <dd className="mt-1 text-[13.5px]">Modèle local {d.classification.modele}, hors ligne. Exactitude mesurée {Math.round((d.classification.exactitude ?? 0) * 100)} %, litiges détectés {Math.round((d.classification.rappel_litige ?? 0) * 100)} %. Seuil de confiance {d.classification.seuil_confiance}.</dd>
        </div>
      </dl>
    </section>
  );
}
