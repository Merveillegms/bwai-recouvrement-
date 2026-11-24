"use client";

import { useState } from "react";
import { Icones } from "@/components/icones";
import { BoutonAction, Chargement, DecisionMotivee, EnTetePage, EtatVide, Jauge } from "@/components/ui";
import { api } from "@/lib/api";
import { useApp, useDonnees } from "@/lib/donnees";
import { CATEGORIES_REPONSE, date, heure } from "@/lib/libelles";
import type { EtatIA, Facture, ReponseEntrante } from "@/lib/types";

type Client = { id: number; code: string; nom: string };
const AVEC_DATE = ["promesse", "demande_delai"];

export default function Reponses() {
  const { utilisateur, agir } = useApp();
  const lecture = utilisateur.role === "auditeur";
  const clients = useDonnees<Client[]>("/api/clients");
  const ia = useDonnees<EtatIA>("/api/ia/etat");
  const file = useDonnees<ReponseEntrante[]>("/api/reponses");
  const [client, setClient] = useState("");
  const [facture, setFacture] = useState("");
  const [texte, setTexte] = useState("");
  const codeClient = clients.donnees?.find((c) => String(c.id) === client)?.code;
  const factures = useDonnees<Facture[]>(codeClient ? `/api/factures?client=${codeClient}` : null);

  return (
    <>
      <EnTetePage titre="Réponses clients" sousTitre="Collez la réponse reçue par SMS ou WhatsApp. Le classifieur propose une catégorie, vous décidez." />

      {ia.donnees && (
        <p className="text-[13px] text-doux">
          {ia.donnees.active
            ? <>Classifieur local actif · exactitude mesurée {Math.round((ia.donnees.classification.exactitude ?? 0) * 100)} % · litiges détectés {Math.round((ia.donnees.classification.rappel_litige ?? 0) * 100)} %. Aucune proposition n'a d'effet sans votre confirmation.</>
            : <>IA désactivée : choisissez vous-même la catégorie de chaque réponse.</>}
        </p>
      )}

      {!lecture && (
        <form className="carte grid gap-3 p-5" onSubmit={(e) => e.preventDefault()}>
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="grid gap-1" htmlFor="r-client"><span className="etiquette">Client</span>
              <select id="r-client" className="champ" value={client} onChange={(e) => { setClient(e.target.value); setFacture(""); }}>
                <option value="">Choisir le client…</option>
                {clients.donnees?.map((c) => <option key={c.id} value={c.id}>{c.nom} ({c.code})</option>)}
              </select>
            </label>
            <label className="grid gap-1" htmlFor="r-facture"><span className="etiquette">Facture concernée (facultatif)</span>
              <select id="r-facture" className="champ" value={facture} onChange={(e) => setFacture(e.target.value)} disabled={!client}>
                <option value="">Aucune en particulier</option>
                {factures.donnees?.filter((f) => f.solde > 0).map((f) => <option key={f.id} value={f.id}>{f.numero} · {f.solde_affiche}</option>)}
              </select>
            </label>
          </div>
          <label className="grid gap-1" htmlFor="r-texte"><span className="etiquette">Message du client</span>
            <textarea id="r-texte" className="champ min-h-[5.5rem]" placeholder="Bonjour, je passe payer vendredi au bureau." value={texte} onChange={(e) => setTexte(e.target.value)} />
          </label>
          <div>
            <BoutonAction disabled={!client || !texte.trim()} onClick={() => agir(
              () => api<{ id: number; proposition: unknown }>("/api/reponses", { corps: { client_id: Number(client), texte, facture_id: facture ? Number(facture) : null } }),
              (r) => r.proposition ? "Réponse classée : vérifiez la proposition ci-dessous" : "Réponse enregistrée : choisissez sa catégorie ci-dessous",
            ).then(() => { setTexte(""); file.recharger(); })}>
              {Icones.ia}Analyser la réponse
            </BoutonAction>
          </div>
        </form>
      )}

      <section className="grid gap-3">
        <h2 className="text-[16px] font-semibold">À traiter</h2>
        {file.chargement && !file.donnees ? <Chargement /> : !file.donnees?.length ? (
          <EtatVide titre="Aucune réponse en attente">Les réponses analysées apparaîtront ici jusqu'à votre décision.</EtatVide>
        ) : (
          <ul className="grid gap-3">{file.donnees.map((r) => <CarteReponse key={r.id} r={r} lecture={lecture} apres={file.recharger} />)}</ul>
        )}
      </section>
    </>
  );
}

function CarteReponse({ r, lecture, apres }: { r: ReponseEntrante; lecture: boolean; apres: () => Promise<void> }) {
  const { agir } = useApp();
  const [categorie, setCategorie] = useState(r.categorie_proposee ?? "");
  const [jour, setJour] = useState(r.date_proposee ?? "");
  const factures = useDonnees<Facture[]>(`/api/factures?client=${r.code_client}`);
  const [facture, setFacture] = useState(r.facture_id ? String(r.facture_id) : "");
  const probas = Object.entries(r.probabilites ?? {}).sort((a, b) => b[1] - a[1]).slice(0, 3);
  const faible = r.confiance !== null && r.confiance < 0.6;

  return (
    <li className="carte grid gap-4 p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="font-semibold">{r.nom_client} <span className="font-normal text-doux">({r.code_client}){r.numero && ` · ${r.numero}`}</span></p>
          <p className="text-[12px] text-doux">Reçue le {heure(r.recue_le)}</p>
        </div>
        {r.litige_possible === 1 && <span className="badge-encre">Litige possible</span>}
      </div>
      <blockquote className="rounded-lg bg-fond px-4 py-3 text-[14px]">« {r.texte} »</blockquote>

      {r.categorie_proposee && (
        <div className="grid gap-2 rounded-lg border border-filet p-4">
          <p className="flex flex-wrap items-center gap-2 text-[13.5px]">
            <span className="etiquette">Proposition</span>
            <span className="badge-vert">{CATEGORIES_REPONSE[r.categorie_proposee]}</span>
            {faible && <span className="badge">Confiance faible</span>}
            {r.date_proposee && <span className="text-doux">date évoquée : <b className="text-encre">{date(r.date_proposee)}</b></span>}
          </p>
          <div className="grid gap-1.5">
            {probas.map(([c, p]) => (
              <div key={c} className="grid grid-cols-[170px_minmax(0,1fr)_42px] items-center gap-3 text-[12.5px]">
                <span className="text-doux">{CATEGORIES_REPONSE[c]}</span><Jauge valeur={p} max={1} /><span className="text-right font-semibold tabulaire">{Math.round(p * 100)} %</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {!lecture && (
        <div className="grid gap-3">
          <div className="flex flex-wrap items-end gap-2.5">
            <label className="grid gap-1" htmlFor={`cat-${r.id}`}><span className="etiquette">Catégorie retenue</span>
              <select id={`cat-${r.id}`} className="champ" value={categorie} onChange={(e) => setCategorie(e.target.value)}>
                <option value="">Choisir…</option>
                {Object.entries(CATEGORIES_REPONSE).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
            </label>
            {AVEC_DATE.includes(categorie) && (
              <label className="grid gap-1" htmlFor={`date-${r.id}`}><span className="etiquette">Date promise</span>
                <input id={`date-${r.id}`} type="date" className="champ tabulaire" value={jour} onChange={(e) => setJour(e.target.value)} />
              </label>
            )}
            {categorie === "litige" && (
              <label className="grid gap-1" htmlFor={`fac-${r.id}`}><span className="etiquette">Facture en litige</span>
                <select id={`fac-${r.id}`} className="champ" value={facture} onChange={(e) => setFacture(e.target.value)}>
                  <option value="">Choisir…</option>
                  {factures.donnees?.filter((f) => f.solde > 0).map((f) => <option key={f.id} value={f.id}>{f.numero} · {f.solde_affiche}</option>)}
                </select>
              </label>
            )}
            <BoutonAction disabled={!categorie || (AVEC_DATE.includes(categorie) && !jour) || (categorie === "litige" && !facture)}
                          onClick={() => agir(() => api<{ statut: string }>(`/api/reponses/${r.id}/confirmer`, {
                            corps: { categorie, date_promise: AVEC_DATE.includes(categorie) ? jour : null, facture_id: facture ? Number(facture) : null } }),
                            (x) => x.statut === "confirmee" ? "Proposition confirmée et appliquée" : "Catégorie corrigée et appliquée").then(apres)}>
              {categorie && categorie === r.categorie_proposee ? "Confirmer" : "Appliquer"}
            </BoutonAction>
          </div>
          <DecisionMotivee libelle="Écarter" action="Écarter la réponse" placeholder="Pourquoi l'écarter ?"
                           onValider={(m) => agir(() => api(`/api/reponses/${r.id}/ecarter`, { corps: { motif: m } }), "Réponse écartée").then(apres)} />
        </div>
      )}
    </li>
  );
}
