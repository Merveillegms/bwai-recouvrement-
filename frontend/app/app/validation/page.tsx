"use client";

import Link from "next/link";
import { useState } from "react";
import { Icones } from "@/components/icones";
import { BoutonAction, Chargement, DecisionMotivee, EnTetePage, Erreur, Etape, EtatVide, Tuile } from "@/components/ui";
import { api } from "@/lib/api";
import { useApp, useDonnees } from "@/lib/donnees";
import { CANAUX, date, heure } from "@/lib/libelles";
import type { EtatIA, LotValidation } from "@/lib/types";

type FileValidation = { lots: LotValidation[]; groupables: string[] };
type LotSimple = { lot: string; client: { code: string; nom: string }; canal: string; statut: string;
                   relances: { id: number; numero: string; etape: string }[] };
type Message = { id: number; cle_envoi: string; canal: string; destinataire: string; statut: string; accuse: string | null; envoye_le: string | null };

export default function Validation() {
  const { utilisateur, agir } = useApp();
  const file = useDonnees<FileValidation>("/api/validation");
  const prets = useDonnees<LotSimple[]>("/api/relances/lots?statut=validee");
  const echecs = useDonnees<LotSimple[]>("/api/relances/lots?statut=echec");
  const messages = useDonnees<Message[]>("/api/messages");
  const ia = useDonnees<EtatIA>("/api/ia/etat");
  const validateur = utilisateur.role === "validateur";
  const lecture = utilisateur.role === "auditeur";
  const tout = async () => { await Promise.all([file.recharger(), prets.recharger(), echecs.recharger(), messages.recharger()]); };
  const lots = file.donnees?.lots ?? [];
  const groupables = file.donnees?.groupables ?? [];
  const iaPrete = ia.donnees?.active && ia.donnees.redaction.configuree;

  return (
    <>
      <EnTetePage titre="Validation et envoi" sousTitre="Chaque message est revérifié juste avant de partir : montants, références et situation de la facture.">
        {!lecture && iaPrete && (
          <BoutonAction variante="second" titre={`Modèle : ${ia.donnees?.redaction.modele}`} onClick={() => agir(
            () => api<{ acceptes: number; rejetes: number; erreurs: number }>("/api/ia/rediger", { corps: { limite: 8 } }),
            (r) => `IA : ${r.acceptes} message(s) rédigé(s), ${r.rejetes + r.erreurs} conservé(s) au gabarit`,
          ).then(tout)}>
            {Icones.ia}Faire rédiger par l'IA
          </BoutonAction>
        )}
        {validateur && groupables.length > 0 && (
          <BoutonAction variante="encre" onClick={() => agir(
            () => api<{ validees: string[]; annulees: string[] }>("/api/validation/approuver-groupe", { corps: { lots: groupables } }),
            (r) => `${r.validees.length} lots ordinaires approuvés${r.annulees.length ? `, ${r.annulees.length} annulés (situation changée)` : ""}`,
          ).then(tout)}>
            Approuver les {groupables.length} lots ordinaires
          </BoutonAction>
        )}
        {!lecture && (
          <BoutonAction disabled={!prets.donnees?.length} onClick={() => agir(
            () => api<{ envoyes: number; annules: number; echecs: number; reprise: { confirmes: number; remis_en_file: number } }>("/api/relances/envoyer", { methode: "POST" }),
            (r) => [`${r.envoyes} message(s) envoyé(s)`, r.annules && `${r.annules} annulé(s) juste avant l'envoi`, r.echecs && `${r.echecs} en échec`,
                    (r.reprise.confirmes + r.reprise.remis_en_file) && "envoi interrompu repris sans doublon"].filter(Boolean).join(", "),
          ).then(tout)}>
            Envoyer les messages validés
          </BoutonAction>
        )}
      </EnTetePage>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Tuile libelle="À valider" valeur={lots.length} note="messages en attente de décision" />
        <Tuile libelle="Lots ordinaires" valeur={groupables.length} note="approbation groupée possible" />
        <Tuile libelle="Prêts à partir" valeur={prets.donnees?.length ?? 0} note="validés, non envoyés" accent />
        <Tuile libelle="En échec" valeur={echecs.donnees?.length ?? 0} note="fournisseur indisponible" />
      </div>

      {!validateur && lots.length > 0 && <p className="text-[13.5px] text-doux">Les décisions sont réservées au validateur. Vous voyez les messages tels qu'ils partiront.</p>}
      {file.erreur && <Erreur message={file.erreur} />}
      {file.chargement && !file.donnees ? <Chargement /> : lots.length === 0 ? (
        <EtatVide titre="Aucun message en attente de décision">Préparez les relances depuis Aujourd'hui : les cas sensibles arriveront ici.</EtatVide>
      ) : (
        <ol className="grid gap-4">{lots.map((l) => <CarteLot key={l.lot} lot={l} validateur={validateur} apres={tout} />)}</ol>
      )}

      {(echecs.donnees?.length ?? 0) > 0 && (
        <section className="grid gap-3">
          <h2 className="text-[16px] font-semibold">Envois en échec</h2>
          {echecs.donnees!.map((l) => (
            <div key={l.lot} className="carte flex flex-wrap items-center justify-between gap-3 px-4 py-3">
              <span><b>{l.client.nom}</b> <span className="text-doux">· {CANAUX[l.canal]} · {l.relances.map((r) => r.numero).join(", ")}</span></span>
              {!lecture && <BoutonAction variante="second" onClick={() => agir(() => api("/api/relances/reessayer", { corps: { lot: l.lot } }), "Remis en file, il sera revérifié avant l'envoi").then(tout)}>Nouvel essai</BoutonAction>}
            </div>
          ))}
        </section>
      )}

      <section className="grid gap-3">
        <h2 className="text-[16px] font-semibold">Derniers messages envoyés</h2>
        {!messages.donnees?.length ? <p className="text-[13.5px] text-doux">Aucun envoi pour l'instant.</p> : (
          <div className="carte overflow-x-auto">
            <table className="donnees min-w-[640px]">
              <thead><tr><th>Envoyé le</th><th>Canal</th><th>Destinataire</th><th>État</th><th>Accusé</th></tr></thead>
              <tbody>
                {messages.donnees.slice(0, 12).map((m) => (
                  <tr key={m.id}>
                    <td className="tabulaire">{m.envoye_le ? heure(m.envoye_le) : "-"}</td>
                    <td>{CANAUX[m.canal] ?? m.canal}</td>
                    <td className="chiffres text-[12.5px]">{m.destinataire}</td>
                    <td>{m.statut === "envoye" ? <span className="badge-vert">Envoyé</span> : <span className="badge-encre">{m.statut}</span>}</td>
                    <td className="chiffres text-[12px] text-doux">{m.accuse}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  );
}

function CarteLot({ lot, validateur, apres }: { lot: LotValidation; validateur: boolean; apres: () => Promise<void> }) {
  const { agir } = useApp();
  const [edition, setEdition] = useState(false);
  const objet = lot.message.startsWith("Objet : ") ? lot.message.split("\n\n")[0].replace("Objet : ", "") : null;
  const corps = objet ? lot.message.split("\n\n").slice(1).join("\n\n") : lot.message;
  const [texte, setTexte] = useState(corps);
  const decider = (chemin: string, donnees: Record<string, unknown>, succes: string) =>
    agir(() => api<{ statut: string; raisons?: string[] }>(chemin, { corps: { lot: lot.lot, ...donnees } }),
         (r) => r.statut === "annulee" && r.raisons ? `Lot annulé : ${r.raisons.join(" ; ")}` : succes).then(apres);

  return (
    <li className="carte grid gap-4 p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-[16px] font-semibold">{lot.client.nom}</h2>
          <p className="text-[12.5px] text-doux">{lot.client.code} · {lot.escalade ? "dossier interne" : CANAUX[lot.canal]} · préparé le {date(lot.date_preparation)}</p>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          {lot.redige_par_ia && <span className="badge-vert">{Icones.ia}Rédigé par l'IA</span>}
          {lot.escalade ? <span className="badge-contour">Escalade</span> : <span className="badge-encre">À valider</span>}
          {lot.groupable && <span className="badge">Lot ordinaire</span>}
        </div>
      </div>
      <p className="text-[13px]"><span className="etiquette mr-2">Pourquoi</span>{lot.raisons.join(" · ")}</p>

      <div className="overflow-x-auto rounded-lg border border-filet">
        <table className="donnees min-w-[520px]">
          <tbody>
            {lot.factures.map((f) => (
              <tr key={f.id}>
                <td className="w-12"><Etape etape={f.etape} /></td>
                <td><Link className="chiffres text-[12.5px] hover:text-vert" href={`/app/factures/${f.id}`}>{f.numero}</Link></td>
                <td className="text-doux">{f.jours_retard} j de retard</td>
                <td className="chiffres text-right font-medium">{f.solde_affiche}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="grid gap-1.5">
        <span className="etiquette">{lot.escalade ? "Note de dossier" : "Message tel qu'il partira"}{objet && ` · objet : ${objet}`}</span>
        {edition ? (
          <>
            <label className="sr-only" htmlFor={`texte-${lot.lot}`}>Message modifié</label>
            <textarea id={`texte-${lot.lot}`} className="champ min-h-[16rem] w-full leading-relaxed" value={texte} onChange={(e) => setTexte(e.target.value)} />
            <p className="text-[12px] text-doux">Le texte modifié est revérifié : chaque montant, numéro et référence doit rester exact.</p>
          </>
        ) : (
          <pre className="whitespace-pre-wrap rounded-lg bg-fond px-4 py-3 font-texte text-[13.5px] leading-relaxed">{corps}</pre>
        )}
      </div>

      {validateur && (
        <div className="flex flex-wrap items-center gap-2">
          {edition ? (
            <>
              <BoutonAction onClick={() => decider("/api/validation/approuver", { contenu: texte, motif: "Message modifié" }, "Message modifié approuvé")}>Approuver le message modifié</BoutonAction>
              <button type="button" className="btn-sec" onClick={() => { setEdition(false); setTexte(corps); }}>Annuler la modification</button>
            </>
          ) : (
            <>
              <BoutonAction onClick={() => decider("/api/validation/approuver", {}, "Approuvé : il partira au prochain envoi")}>Approuver</BoutonAction>
              {!lot.escalade && <button type="button" className="btn-sec" onClick={() => setEdition(true)}>Modifier le message</button>}
              {lot.redige_par_ia && (
                <BoutonAction variante="second" onClick={() => agir(() => api("/api/validation/gabarit", { corps: { lot: lot.lot } }), "Texte du gabarit restauré").then(apres)}>
                  Revenir au gabarit
                </BoutonAction>
              )}
              <DecisionMotivee libelle="Rejeter" action="Confirmer le rejet" variante="encre"
                               onValider={(m) => decider("/api/validation/rejeter", { motif: m }, "Rejeté : cette étape ne sera plus proposée")} />
              <DecisionMotivee libelle="Suspendre les factures" action="Confirmer la suspension" variante="encre"
                               onValider={(m) => decider("/api/validation/suspendre", { motif: m }, "Factures suspendues : plus aucune relance")} />
            </>
          )}
        </div>
      )}
    </li>
  );
}
