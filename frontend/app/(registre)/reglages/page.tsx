"use client";

import { useState } from "react";
import { BoutonAction, DecisionMotivee, EnTetePage, Tampon } from "@/components/ui";
import { api } from "@/lib/api";
import { useApp, useDonnees } from "@/lib/donnees";
import { dateLongue } from "@/lib/libelles";
import type { FileDuJour } from "@/lib/types";

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

      <section className="grid gap-3 border-2 border-tampon p-5">
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="text-xl font-semibold">Arrêt d'urgence</h2>
          {systeme?.arret_urgence ? <Tampon>Actif</Tampon> : <span className="text-sm text-ok">inactif : les relances fonctionnent</span>}
        </div>
        <p className="max-w-prose text-sm text-encre-pale">Bloque immédiatement toute préparation et tout envoi de relance, par exemple après une erreur de tarif. Réservé au validateur, motif obligatoire, inscrit au journal.</p>
        {validateur && (systeme?.arret_urgence ? (
          <div><BoutonAction onClick={() => agir(() => api("/api/arret-urgence", { corps: { actif: false } }), "Arrêt d'urgence levé")}>Lever l'arrêt d'urgence</BoutonAction></div>
        ) : (
          <DecisionMotivee libelle="Tout arrêter maintenant" action="Confirmer l'arrêt" variante="danger" placeholder="Motif de l'arrêt"
                           onValider={(motif) => agir(() => api("/api/arret-urgence", { corps: { actif: true, motif } }), "Arrêt d'urgence activé")} />
        ))}
      </section>

      <section className="grid gap-3">
        <h2 className="text-xl font-semibold">Poids de la priorité</h2>
        <p className="max-w-prose text-sm text-encre-pale">
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
          <div className="overflow-x-auto">
            <table className="w-full min-w-[560px] border-collapse text-sm">
              <thead><tr className="border-b border-encre text-left">
                <th className="py-1 pr-3 font-medium">Nouveau rang</th><th className="pr-3 font-medium">Avant</th><th className="pr-3 font-medium">Facture</th>
                <th className="pr-3 font-medium">Client</th><th className="text-right font-medium">Score</th>
              </tr></thead>
              <tbody>
                {simulation.slice(0, 15).map((s) => (
                  <tr key={s.facture_id} className="border-b border-filet">
                    <td className="chiffres py-1 pr-3">{s.rang}</td>
                    <td className="chiffres pr-3 text-encre-pale">{s.ancien_rang}{s.rang < s.ancien_rang ? " ↑" : s.rang > s.ancien_rang ? " ↓" : ""}</td>
                    <td className="chiffres pr-3">{s.numero}</td><td className="pr-3">{s.client}</td>
                    <td className="chiffres text-right">{s.ancien_score} → {s.score}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {systeme?.date_simulee && !lecture && (
        <section className="grid gap-3 border border-dashed border-filet p-5">
          <h2 className="text-xl font-semibold">Démonstration</h2>
          <p className="text-sm text-encre-pale">Date métier simulée : {dateLongue(systeme.date_du_jour)}. Faire passer le temps recalcule les statuts et fait avancer les étapes de relance.</p>
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
