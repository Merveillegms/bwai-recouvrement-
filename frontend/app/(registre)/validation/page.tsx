"use client";

import Link from "next/link";
import { useState } from "react";
import { BoutonAction, Chargement, DecisionMotivee, EnTetePage, Erreur, Etape, EtatVide, Tampon } from "@/components/ui";
import { api } from "@/lib/api";
import { useApp, useDonnees } from "@/lib/donnees";
import { CANAUX, date, heure } from "@/lib/libelles";
import type { LotValidation } from "@/lib/types";

type FileValidation = { lots: LotValidation[]; groupables: string[] };
type LotSimple = { lot: string; client: { code: string; nom: string }; canal: string; statut: string;
                   relances: { id: number; numero: string; etape: string }[] };
type Message = { id: number; cle_envoi: string; canal: string; destinataire: string; statut: string; accuse: string | null;
                 envoye_le: string | null };

export default function Validation() {
  const { utilisateur, agir } = useApp();
  const file = useDonnees<FileValidation>("/api/validation");
  const prets = useDonnees<LotSimple[]>("/api/relances/lots?statut=validee");
  const echecs = useDonnees<LotSimple[]>("/api/relances/lots?statut=echec");
  const messages = useDonnees<Message[]>("/api/messages");
  const validateur = utilisateur.role === "validateur";
  const lecture = utilisateur.role === "auditeur";
  const toutRecharger = async () => { await Promise.all([file.recharger(), prets.recharger(), echecs.recharger(), messages.recharger()]); };

  const lots = file.donnees?.lots ?? [];
  const groupables = file.donnees?.groupables ?? [];

  return (
    <div className="grid gap-8">
      <EnTetePage titre="Validation et envoi"
                  sousTitre={<><span className="chiffres text-tampon">{lots.length}</span> messages attendent une décision ·{" "}
                    <span className="chiffres">{prets.donnees?.length ?? 0}</span> validés prêts à partir</>}>
        {validateur && groupables.length > 0 && (
          <BoutonAction variante="second" onClick={() => agir(
            () => api<{ validees: string[]; annulees: string[]; refusees: unknown[] }>("/api/validation/approuver-groupe", { corps: { lots: groupables } }),
            (r) => `${r.validees.length} lots ordinaires approuvés${r.annulees.length ? `, ${r.annulees.length} annulés (situation changée)` : ""}`,
          ).then(toutRecharger)}>
            Approuver les {groupables.length} lots ordinaires (R3)
          </BoutonAction>
        )}
        {!lecture && (
          <BoutonAction disabled={!prets.donnees?.length} onClick={() => agir(
            () => api<{ envoyes: number; annules: number; echecs: number; reprise: { confirmes: number; remis_en_file: number } }>("/api/relances/envoyer", { methode: "POST" }),
            (r) => [`${r.envoyes} message(s) envoyé(s)`, r.annules && `${r.annules} annulé(s) juste avant l'envoi`,
                    r.echecs && `${r.echecs} en échec`,
                    (r.reprise.confirmes + r.reprise.remis_en_file) && "envoi interrompu repris sans doublon"].filter(Boolean).join(" · "),
          ).then(toutRecharger)}>
            Envoyer les messages validés
          </BoutonAction>
        )}
      </EnTetePage>

      {!validateur && lots.length > 0 && (
        <p className="text-sm text-encre-pale">Les décisions sont réservées au validateur. Vous voyez les messages tels qu'ils partiront.</p>
      )}
      {file.erreur && <Erreur message={file.erreur} />}
      {file.chargement && !file.donnees ? <Chargement /> : lots.length === 0 ? (
        <EtatVide titre="Aucun message en attente de décision">
          Préparez les relances du jour depuis « Aujourd'hui » : les cas sensibles apparaîtront ici.
        </EtatVide>
      ) : (
        <ol className="grid gap-6">
          {lots.map((l) => <CarteLot key={l.lot} lot={l} validateur={validateur} apres={toutRecharger} />)}
        </ol>
      )}

      {(echecs.donnees?.length ?? 0) > 0 && (
        <section className="grid gap-2">
          <h2 className="text-xl font-semibold">Envois en échec</h2>
          <ul className="grid gap-2">
            {echecs.donnees!.map((l) => (
              <li key={l.lot} className="flex flex-wrap items-center justify-between gap-3 border border-tampon px-4 py-2">
                <span>{l.client.nom} · {CANAUX[l.canal]} · {l.relances.map((r) => r.numero).join(", ")}</span>
                {!lecture && <BoutonAction variante="second" onClick={() => agir(() => api("/api/relances/reessayer", { corps: { lot: l.lot } }),
                                                                                  "Remis en file : il sera revérifié avant l'envoi").then(toutRecharger)}>
                  Nouvel essai
                </BoutonAction>}
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="grid gap-2">
        <h2 className="text-xl font-semibold">Derniers messages envoyés</h2>
        {!messages.donnees?.length ? <p className="text-sm text-encre-pale">Aucun envoi pour l'instant.</p> : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px] border-collapse text-sm">
              <thead><tr className="border-b border-encre text-left">
                <th className="py-1.5 pr-4 font-medium">Envoyé le</th><th className="pr-4 font-medium">Canal</th>
                <th className="pr-4 font-medium">Destinataire</th><th className="pr-4 font-medium">État</th><th className="font-medium">Accusé</th>
              </tr></thead>
              <tbody>
                {messages.donnees.slice(0, 12).map((m) => (
                  <tr key={m.id} className="border-b border-filet">
                    <td className="chiffres py-1.5 pr-4">{m.envoye_le ? heure(m.envoye_le) : "-"}</td>
                    <td className="pr-4">{CANAUX[m.canal] ?? m.canal}</td>
                    <td className="chiffres pr-4">{m.destinataire}</td>
                    <td className="pr-4">{m.statut === "envoye" ? <span className="text-ok">envoyé</span> : <span className="text-tampon">{m.statut}</span>}</td>
                    <td className="chiffres text-encre-pale">{m.accuse}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
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
    <li className="grid gap-4 border border-filet bg-[#f8f5ec] p-5">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-2">
        <div>
          <h2 className="text-xl font-semibold">{lot.client.nom}</h2>
          <p className="chiffres text-xs text-encre-pale">{lot.client.code} · {lot.escalade ? "dossier interne" : CANAUX[lot.canal]} · préparé le {date(lot.date_preparation)}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {lot.escalade ? <Tampon>Escalade</Tampon> : <Tampon>À valider</Tampon>}
          {lot.groupable && <span className="text-xs text-encre-pale">lot ordinaire</span>}
        </div>
      </div>
      <p className="text-sm"><span className="etiquette mr-2">Pourquoi</span>{lot.raisons.join(" · ")}</p>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[520px] border-collapse text-sm">
          <tbody>
            {lot.factures.map((f) => (
              <tr key={f.id} className="border-b border-filet">
                <td className="py-1 pr-3"><Etape etape={f.etape} /></td>
                <td className="chiffres pr-3"><Link className="hover:underline" href={`/factures/${f.id}`}>{f.numero}</Link></td>
                <td className="pr-3 text-encre-pale">{f.jours_retard} j de retard</td>
                <td className="chiffres text-right">{f.solde_affiche}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="grid gap-1">
        <span className="etiquette">{lot.escalade ? "Note de dossier" : "Message tel qu'il partira"}{objet && ` · objet : ${objet}`}</span>
        {edition ? (
          <>
            <label className="sr-only" htmlFor={`texte-${lot.lot}`}>Message modifié</label>
            <textarea id={`texte-${lot.lot}`} className="champ min-h-[16rem] w-full font-texte text-sm leading-relaxed"
                      value={texte} onChange={(e) => setTexte(e.target.value)} />
            <p className="text-xs text-encre-pale">Le texte modifié est revérifié : chaque montant, numéro et référence doit rester exact.</p>
          </>
        ) : (
          <pre className="whitespace-pre-wrap border-l-2 border-filet bg-papier px-4 py-3 font-texte text-sm leading-relaxed">{corps}</pre>
        )}
      </div>

      {validateur && (
        <div className="flex flex-wrap items-center gap-2">
          {edition ? (
            <>
              <BoutonAction onClick={() => decider("/api/validation/approuver", { contenu: texte, motif: "Message modifié" }, "Message modifié approuvé")}>
                Approuver le message modifié
              </BoutonAction>
              <button type="button" className="bouton bouton-second" onClick={() => { setEdition(false); setTexte(corps); }}>Annuler la modification</button>
            </>
          ) : (
            <>
              <BoutonAction onClick={() => decider("/api/validation/approuver", {}, "Approuvé : il partira au prochain envoi")}>Approuver</BoutonAction>
              {!lot.escalade && <button type="button" className="bouton bouton-second" onClick={() => setEdition(true)}>Modifier le message</button>}
              <DecisionMotivee libelle="Rejeter" action="Confirmer le rejet" variante="danger"
                               onValider={(motif) => decider("/api/validation/rejeter", { motif }, "Rejeté : cette étape ne sera plus proposée")} />
              <DecisionMotivee libelle="Suspendre les factures" action="Confirmer la suspension" variante="danger"
                               onValider={(motif) => decider("/api/validation/suspendre", { motif }, "Factures suspendues : plus aucune relance")} />
            </>
          )}
        </div>
      )}
    </li>
  );
}
