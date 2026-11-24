"use client";

import Link from "next/link";
import { useState } from "react";
import { BoutonAction, Chargement, DecisionMotivee, EnTetePage, Erreur, EtatVide } from "@/components/ui";
import { api } from "@/lib/api";
import { useApp, useDonnees } from "@/lib/donnees";
import { date } from "@/lib/libelles";
import type { Facture, Paiement } from "@/lib/types";

const MOTIFS: Record<string, string> = {
  PROPOSITION_MONTANT_CLIENT: "Sans référence : le montant et le téléphone désignent une seule facture",
  RAPPROCHEMENT_AMBIGU: "Sans référence : plusieurs factures possibles",
  REFERENCE_INVALIDE: "Référence mal saisie (chiffre de contrôle faux)",
  REFERENCE_INCONNUE: "Référence valide mais inconnue",
  FACTURE_DEJA_SOLDEE: "La facture citée est déjà soldée : doublon possible",
  FACTURE_CLOTUREE: "La facture citée est clôturée",
  DEVISE_DIFFERENTE: "Devise différente de celle de la facture",
  NON_IDENTIFIE: "Aucune facture ne correspond",
  ANNULATION: "Rapprochement annulé : à réaffecter",
};

export default function Paiements() {
  const { utilisateur, agir } = useApp();
  const { donnees, erreur, chargement, recharger } = useDonnees<Paiement[]>("/api/paiements?statut=a_valider");
  const factures = useDonnees<Facture[]>("/api/factures");
  const lecture = utilisateur.role === "auditeur";
  const parId = new Map((factures.donnees ?? []).map((f) => [f.id, f]));

  return (
    <div className="grid gap-6">
      <EnTetePage titre="Paiements à rapprocher"
                  sousTitre="Seuls les paiements citant une référence valide sont appliqués seuls. Les autres attendent votre décision.">
        {!lecture && (
          <BoutonAction variante="second" onClick={() => agir(() => api<{ resume: Record<string, number> }>("/api/rapprochement", { methode: "POST" }),
                                                                (r) => Object.keys(r.resume).length ? `Rapprochement : ${Object.entries(r.resume).map(([k, v]) => `${v} ${k.toLowerCase()}`).join(", ")}` : "Aucun nouveau paiement").then(recharger)}>
            Relancer le rapprochement
          </BoutonAction>
        )}
      </EnTetePage>
      {erreur && <Erreur message={erreur} />}
      {chargement && !donnees ? <Chargement /> : !donnees?.length ? (
        <EtatVide titre="Aucun paiement en attente">Tous les paiements importés sont rapprochés ou écartés.</EtatVide>
      ) : (
        <ul className="grid gap-4">
          {donnees.map((p) => <CartePaiement key={p.id} p={p} proposee={p.facture_proposee_id ? parId.get(p.facture_proposee_id) : undefined}
                                             factures={factures.donnees ?? []} lecture={lecture} apres={recharger} />)}
        </ul>
      )}
    </div>
  );
}

function CartePaiement({ p, proposee, factures, lecture, apres }: { p: Paiement; proposee?: Facture; factures: Facture[];
                                                                   lecture: boolean; apres: () => Promise<void> }) {
  const { agir } = useApp();
  const [autre, setAutre] = useState("");
  const [motif, setMotif] = useState("");
  const ouvertes = factures.filter((f) => f.solde > 0 && f.devise === p.devise && f.statut !== "cloturee");
  return (
    <li className="grid gap-3 carte p-5">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <div>
          <p className="chiffres text-lg">{p.montant_affiche}</p>
          <p className="chiffres text-xs text-doux">{p.id_transaction} · {date(p.date_paiement)} · {p.operateur} · {p.telephone_payeur ?? "téléphone inconnu"}</p>
        </div>
        <span className="badge-contour">À rapprocher</span>
      </div>
      <p className="text-sm"><span className="etiquette mr-2">Pourquoi</span>{MOTIFS[p.motif_rapprochement ?? ""] ?? p.motif_rapprochement}
        {p.reference_citee && <> · référence citée <span className="chiffres">{p.reference_citee}</span></>}</p>
      {proposee && (
        <p className="text-sm">Proposition : <Link href={`/app/factures/${proposee.id}`} className="chiffres underline underline-offset-2">{proposee.numero}</Link>{" "}
          de {proposee.nom_client}, solde {proposee.solde_affiche}</p>
      )}
      {!lecture && (
        <div className="flex flex-wrap items-end gap-2">
          {proposee && (
            <BoutonAction onClick={() => agir(() => api(`/api/paiements/${p.id}/valider`, { corps: {} }), "Paiement rapproché").then(apres)}>
              Confirmer la proposition
            </BoutonAction>
          )}
          <label className="grid gap-1 text-sm" htmlFor={`autre-${p.id}`}><span className="etiquette">Affecter à une autre facture</span>
            <select id={`autre-${p.id}`} className="champ max-w-[22rem]" value={autre} onChange={(e) => setAutre(e.target.value)}>
              <option value="">Choisir…</option>
              {ouvertes.map((f) => <option key={f.id} value={f.id}>{f.numero} · {f.nom_client} · {f.solde_affiche}</option>)}
            </select>
          </label>
          {autre && (
            <>
              <label className="sr-only" htmlFor={`motif-${p.id}`}>Motif</label>
              <input id={`motif-${p.id}`} className="champ" placeholder="Motif (obligatoire)" value={motif} onChange={(e) => setMotif(e.target.value)} />
              <BoutonAction disabled={!motif.trim()} onClick={() => agir(() => api(`/api/paiements/${p.id}/valider`, { corps: { facture_id: Number(autre), motif } }),
                                                                         "Paiement affecté").then(apres)}>
                Affecter
              </BoutonAction>
            </>
          )}
          <DecisionMotivee libelle="Écarter ce paiement" action="Confirmer" variante="encre" placeholder="Pourquoi l'écarter ?"
                           onValider={(m) => agir(() => api(`/api/paiements/${p.id}/rejeter`, { corps: { motif: m } }), "Paiement écarté").then(apres)} />
        </div>
      )}
    </li>
  );
}
