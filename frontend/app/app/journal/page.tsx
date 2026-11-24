"use client";

import { useMemo, useState } from "react";
import { BoutonAction, Chargement, EnTetePage, Erreur, EtatVide } from "@/components/ui";
import { ouvrirFichier } from "@/lib/api";
import { useApp, useDonnees } from "@/lib/donnees";
import { heure } from "@/lib/libelles";
import type { LigneJournal } from "@/lib/types";

const ACTIONS: Record<string, string> = {
  import_fichier: "Import de fichier", creation_facture: "Facture importée", changement_statut: "Changement de statut",
  rapprochement: "Paiement rapproché", rapprochement_a_valider: "Paiement à valider", preparation_relance: "Relance préparée",
  validation_approuver: "Relance approuvée", validation_modifier: "Message modifié", validation_rejeter: "Relance rejetée",
  validation_suspendre: "Factures suspendues", annulation_lot: "Annulée avant envoi", envoi_relance: "Message envoyé",
  reprise_envoi_confirme: "Reprise : envoi confirmé", reprise_envoi_non_effectue: "Reprise : remis en file",
  reponse_client: "Réponse du client", declaration_litige: "Litige déclaré", modification_parametre: "Paramètre modifié",
  connexion: "Connexion", connexion_refusee: "Connexion refusée",
};
const PAGE = 50;

export default function Journal() {
  const { notifier } = useApp();
  const [f, setF] = useState({ action: "", acteur: "", client: "", depuis: "", jusqu_a: "" });
  const [decalage, setDecalage] = useState(0);
  const params = useMemo(() => new URLSearchParams(Object.entries(f).filter(([, v]) => v) as [string, string][]), [f]);
  const { donnees, erreur, chargement } = useDonnees<{ total: number; lignes: LigneJournal[] }>(`/api/journal?${params}&limite=${PAGE}&decalage=${decalage}`);
  const integrite = useDonnees<{ intact: boolean; lignes_verifiees: number; lignes_alterees: number[] }>("/api/journal/verification");
  const maj = (cle: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => { setDecalage(0); setF({ ...f, [cle]: e.target.value }); };

  return (
    <div className="grid gap-5">
      <EnTetePage titre="Journal" sousTitre="Chaque décision, humaine ou automatique, avec sa règle. Le journal ne se modifie pas : il s'ajoute.">
        {integrite.donnees && (integrite.donnees.intact
          ? <span className="text-sm text-vert">Chaîne d'empreintes intacte · <span className="chiffres">{integrite.donnees.lignes_verifiees}</span> lignes vérifiées</span>
          : <span className="badge-encre">Altération détectée : lignes {integrite.donnees.lignes_alterees.join(", ")}</span>)}
        <BoutonAction variante="second" onClick={() => ouvrirFichier(`/api/journal/export.csv?${params}`, "journal.csv", true).catch(() => notifier("Export impossible", "erreur"))}>
          Exporter en CSV
        </BoutonAction>
      </EnTetePage>

      <form className="flex flex-wrap items-end gap-3 text-sm" onSubmit={(e) => e.preventDefault()}>
        <label className="grid gap-1" htmlFor="j-action"><span className="etiquette">Action</span>
          <select id="j-action" className="champ" value={f.action} onChange={maj("action")}>
            <option value="">Toutes</option>{Object.entries(ACTIONS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </label>
        <label className="grid gap-1" htmlFor="j-acteur"><span className="etiquette">Acteur</span>
          <select id="j-acteur" className="champ" value={f.acteur} onChange={maj("acteur")}>
            <option value="">Tous</option>{["systeme", "gestionnaire", "validateur", "auditeur"].map((a) => <option key={a} value={a}>{a}</option>)}
          </select>
        </label>
        <label className="grid gap-1" htmlFor="j-client"><span className="etiquette">Code client</span>
          <input id="j-client" className="champ w-24" placeholder="C003" value={f.client} onChange={maj("client")} />
        </label>
        <label className="grid gap-1" htmlFor="j-depuis"><span className="etiquette">Depuis le</span>
          <input id="j-depuis" type="date" className="champ" value={f.depuis} onChange={maj("depuis")} />
        </label>
        <label className="grid gap-1" htmlFor="j-jusqu"><span className="etiquette">Jusqu'au</span>
          <input id="j-jusqu" type="date" className="champ" value={f.jusqu_a} onChange={maj("jusqu_a")} />
        </label>
      </form>

      {erreur && <Erreur message={erreur} />}
      {chargement && !donnees ? <Chargement /> : !donnees?.lignes.length ? <EtatVide titre="Aucune ligne pour ces critères" /> : (
        <>
          <div className="carte overflow-x-auto">
            <table className="donnees min-w-[860px]">
              <thead><tr>
                <th>N°</th><th>Quand</th><th>Qui</th>
                <th>Quoi</th><th>Règle</th><th>Empreinte</th>
              </tr></thead>
              <tbody>
                {donnees.lignes.map((l) => (
                  <tr key={l.id} className="border-b border-filet align-top">
                    <td className="chiffres text-doux">{l.id}</td>
                    <td className="chiffres whitespace-nowrap">{heure(l.horodatage)}</td>
                    <td>{l.acteur}{l.type_acteur !== "humain" && <span className="text-doux"> ({l.type_acteur})</span>}</td>
                    <td>{l.libelle}</td>
                    <td className="chiffres text-xs text-doux">{l.regle}</td>
                    <td className="chiffres text-xs text-doux" title={l.hash}>{l.hash.slice(0, 10)}…</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="flex flex-wrap items-center gap-3 text-sm">
            <button type="button" className="btn-sec" disabled={decalage === 0} onClick={() => setDecalage(Math.max(0, decalage - PAGE))}>Plus récentes</button>
            <span className="chiffres text-doux">{decalage + 1} à {Math.min(decalage + PAGE, donnees.total)} sur {donnees.total}</span>
            <button type="button" className="btn-sec" disabled={decalage + PAGE >= donnees.total} onClick={() => setDecalage(decalage + PAGE)}>Plus anciennes</button>
          </div>
        </>
      )}
    </div>
  );
}
