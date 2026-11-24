"use client";

import Link from "next/link";
import { useState } from "react";
import { BoutonAction, DecisionMotivee, EnTetePage, Erreur } from "@/components/ui";
import { api, ErreurApi, ouvrirFichier } from "@/lib/api";
import { useApp, useDonnees } from "@/lib/donnees";
import { heure } from "@/lib/libelles";
import type { Anomalie, Apercu, Facture, RapportImport } from "@/lib/types";

const TYPES = { factures: "Factures", clients: "Clients", paiements: "Paiements mobile money" } as const;
type TypeImport = keyof typeof TYPES;
const CHAMPS: Record<string, string> = {
  numero_facture: "Numéro de facture", code_client: "Code client", date_emission: "Date d'émission",
  date_echeance: "Date d'échéance", montant_ttc: "Montant TTC", devise: "Devise", litige: "Litige", nom: "Nom",
  telephone: "Téléphone", email: "E-mail", canal_prefere: "Canal préféré", langue: "Langue", sensible: "Client sensible",
  notes: "Notes", id_transaction: "Identifiant de transaction", date: "Date", montant: "Montant", reference: "Référence",
  telephone_payeur: "Téléphone du payeur", operateur: "Opérateur",
};

type ImportPasse = { id: number; type: string; fichier: string; importe_le: string; importe_par: string; lignes_lues: number;
                     lignes_acceptees: number; lignes_avertissement: number; lignes_rejetees: number };

export default function Import() {
  const { utilisateur, agir, notifier } = useApp();
  const lecture = utilisateur.role === "auditeur";
  const [type, setType] = useState<TypeImport>("factures");
  const [fichier, setFichier] = useState<File | null>(null);
  const [apercu, setApercu] = useState<Apercu | null>(null);
  const [correspondance, setCorrespondance] = useState<Record<string, string | null>>({});
  const [rapport, setRapport] = useState<RapportImport | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  const historique = useDonnees<ImportPasse[]>("/api/imports");
  const anomalies = useDonnees<Anomalie[]>("/api/anomalies");
  const aVerifier = useDonnees<(Facture & { code_client: string; nom_client: string })[]>("/api/factures/a-verifier");
  const enAttente = useDonnees<{ id: number; code: string; nom: string }[]>("/api/clients?en_attente=true");
  const toutRecharger = async () => { await Promise.all([historique.recharger(), anomalies.recharger(), aVerifier.recharger(), enAttente.recharger()]); };

  async function lire(f: File | null, t: TypeImport = type) {
    setFichier(f); setApercu(null); setRapport(null); setErreur(null);
    if (!f) return;
    const donnees = new FormData();
    donnees.append("fichier", f);
    try {
      const a = await api<Apercu>(`/api/imports/${t}/apercu`, { formulaire: donnees });
      setApercu(a);
      setCorrespondance(a.correspondance);
    } catch (e) {
      setErreur(e instanceof ErreurApi ? e.message : "Lecture impossible");
    }
  }

  async function importer() {
    if (!fichier) return;
    const donnees = new FormData();
    donnees.append("fichier", fichier);
    donnees.append("correspondance", JSON.stringify(correspondance));
    const r = await agir(() => api<RapportImport>(`/api/imports/${type}`, { formulaire: donnees }),
                         (r) => `${r.fichier} : ${r.lignes_acceptees + r.lignes_avertissement} lignes entrées, ${r.lignes_rejetees} rejetées`);
    if (r) { setRapport(r); setApercu(null); await toutRecharger(); }
  }

  return (
    <div className="grid gap-8">
      <EnTetePage titre="Import" sousTitre="CSV ou Excel. Un fichier déjà importé est refusé, même renommé. Rien n'entre à moitié." />

      {!lecture && (
        <section className="grid gap-4 carte p-5">
          <div className="flex flex-wrap items-end gap-3">
            <label className="grid gap-1 text-sm" htmlFor="type-import"><span className="etiquette">Contenu du fichier</span>
              <select id="type-import" className="champ" value={type} onChange={(e) => { const t = e.target.value as TypeImport; setType(t); lire(fichier, t); }}>
                {Object.entries(TYPES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
            </label>
            <label className="grid gap-1 text-sm" htmlFor="fichier"><span className="etiquette">Fichier</span>
              <input id="fichier" type="file" accept=".csv,.txt,.xlsx" className="text-sm" onChange={(e) => lire(e.target.files?.[0] ?? null)} />
            </label>
          </div>
          {erreur && <Erreur message={erreur} />}
          {apercu && (
            <div className="grid gap-3">
              <p className="text-sm text-doux">
                {apercu.nombre_lignes} lignes · format {apercu.format}
                {apercu.encodage && <> · encodage {apercu.encodage}</>}
                {apercu.separateur && <> · séparateur « {apercu.separateur === "\t" ? "tabulation" : apercu.separateur} »</>}
              </p>
              <div className="carte overflow-x-auto">
                <table className="donnees min-w-[520px]">
                  <thead><tr><th>Champ attendu</th><th>Colonne du fichier</th></tr></thead>
                  <tbody>
                    {Object.keys(correspondance).map((champ) => (
                      <tr key={champ} className="border-b border-filet">
                        <td>{CHAMPS[champ] ?? champ}{apercu.champs_manquants.includes(champ) && !correspondance[champ] && <span className="ml-2 font-semibold text-encre">obligatoire</span>}</td>
                        <td>
                          <label className="sr-only" htmlFor={`col-${champ}`}>Colonne pour {CHAMPS[champ] ?? champ}</label>
                          <select id={`col-${champ}`} className="champ" value={correspondance[champ] ?? ""}
                                  onChange={(e) => setCorrespondance({ ...correspondance, [champ]: e.target.value || null })}>
                            <option value="">(aucune)</option>
                            {apercu.entetes.map((h) => <option key={h} value={h}>{h}</option>)}
                          </select>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div><BoutonAction onClick={importer}>Importer {apercu.nombre_lignes} lignes</BoutonAction></div>
            </div>
          )}
        </section>
      )}

      {rapport && (
        <section className="grid gap-3">
          <h2 className="text-[16px] font-semibold">Rapport : {rapport.fichier}</h2>
          <dl className="flex flex-wrap gap-x-8 gap-y-2 carte px-5 py-3">
            {[["lues", rapport.lignes_lues], ["acceptées", rapport.lignes_acceptees], ["à vérifier", rapport.lignes_avertissement], ["rejetées", rapport.lignes_rejetees]]
              .map(([k, v]) => <div key={k as string}><dt className="etiquette">{k}</dt><dd className="chiffres text-xl">{v}</dd></div>)}
          </dl>
          {rapport.rapprochement && <p className="text-sm">Rapprochement : {Object.entries(rapport.rapprochement).map(([k, v]) => `${v} ${k.toLowerCase().replace(/_/g, " ")}`).join(" · ")}</p>}
          {rapport.lignes_rejetees > 0 && (
            <div><BoutonAction variante="second" onClick={() => ouvrirFichier(`/api/imports/${rapport.import_id}/rejets.csv`, `rejets_${rapport.import_id}.csv`, true).catch(() => notifier("Téléchargement impossible", "erreur"))}>
              Télécharger les lignes rejetées (CSV)
            </BoutonAction></div>
          )}
          <ul className="grid max-h-80 gap-1 overflow-y-auto text-sm">
            {rapport.anomalies.map((a, i) => (
              <li key={i} className="flex flex-wrap gap-x-3 border-b border-filet py-1">
                <span className="chiffres w-16 text-doux">ligne {a.ligne}</span>
                <span className={a.gravite === "rejet" ? "font-semibold text-encre" : "text-encre"}>{a.gravite === "rejet" ? "rejetée" : "à vérifier"}</span>
                <span>{a.message}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="grid gap-3">
        <h2 className="text-[16px] font-semibold">À traiter</h2>
        {!anomalies.donnees?.length && !aVerifier.donnees?.length && !enAttente.donnees?.length && (
          <p className="text-sm text-doux">Aucune anomalie en attente.</p>
        )}
        {enAttente.donnees?.map((c) => <ClientEnAttente key={c.id} client={c} lecture={lecture} apres={toutRecharger} />)}
        {aVerifier.donnees?.map((f) => (
          <div key={f.id} className="grid gap-2 border border-filet px-4 py-3">
            <div className="flex flex-wrap items-center gap-3">
              <span className="badge-contour">À vérifier</span>
              <Link href={`/app/factures/${f.id}`} className="chiffres underline-offset-2 hover:underline">{f.numero}</Link>
              <span>{f.nom_client}</span><span className="chiffres">{f.solde_affiche}</span>
              <span className="text-sm text-doux">{f.motif_verification?.replace(/_/g, " ").toLowerCase()}</span>
            </div>
            {!lecture && (
              <div className="flex flex-wrap gap-2">
                <BoutonAction variante="second" onClick={() => agir(() => api(`/api/factures/${f.id}/confirmer`, { corps: { motif: "Vérifiée" } }), "Doute levé : la facture peut être relancée").then(toutRecharger)}>
                  Confirmer la facture
                </BoutonAction>
                <DecisionMotivee libelle="Annuler (doublon ou erreur)" action="Annuler la facture" variante="encre"
                                 onValider={(m) => agir(() => api(`/api/factures/${f.id}/annuler`, { corps: { motif: m } }), "Facture annulée et clôturée").then(toutRecharger)} />
              </div>
            )}
          </div>
        ))}
        {anomalies.donnees?.map((a) => (
          <div key={a.id} className="grid gap-2 border border-filet px-4 py-3">
            <div className="flex flex-wrap items-center gap-3 text-sm">
              <span className="badge-encre">Rejetée</span>
              <span className="chiffres text-doux">{a.fichier} · ligne {a.ligne}</span>
              <span>{a.message}</span>
            </div>
            {!lecture && (
              <div className="flex flex-wrap gap-2">
                <BoutonAction variante="second" onClick={() => agir(() => api(`/api/anomalies/${a.id}/resolution`, { corps: { decision: "ignorer" } }), "Anomalie classée").then(toutRecharger)}>
                  Classer (la base fait foi)
                </BoutonAction>
                {a.code === "CONFLIT_NUMERO" && utilisateur.role === "validateur" && (
                  <DecisionMotivee libelle="Remplacer la facture par cette ligne" action="Remplacer" variante="encre"
                                   onValider={(m) => agir(() => api(`/api/anomalies/${a.id}/resolution`, { corps: { decision: "remplacer", motif: m } }), "Facture remplacée").then(toutRecharger)} />
                )}
              </div>
            )}
          </div>
        ))}
      </section>

      <section className="grid gap-2">
        <h2 className="text-[16px] font-semibold">Imports passés</h2>
        <div className="carte overflow-x-auto">
          <table className="donnees min-w-[640px]">
            <thead><tr>
              <th>Fichier</th><th>Type</th><th>Par</th>
              <th>Le</th><th className="text-right">Lues</th><th className="text-right">Rejetées</th>
            </tr></thead>
            <tbody>
              {historique.donnees?.map((i) => (
                <tr key={i.id} className="border-b border-filet">
                  <td>{i.fichier}</td><td>{i.type}</td><td>{i.importe_par}</td>
                  <td className="chiffres">{heure(i.importe_le)}</td><td className="chiffres text-right">{i.lignes_lues}</td>
                  <td className="chiffres text-right">{i.lignes_rejetees}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

function ClientEnAttente({ client, lecture, apres }: { client: { id: number; code: string; nom: string }; lecture: boolean; apres: () => Promise<void> }) {
  const { agir } = useApp();
  const [nom, setNom] = useState("");
  const [telephone, setTelephone] = useState("");
  const [canal, setCanal] = useState("sms");
  return (
    <div className="grid gap-2 border border-filet px-4 py-3">
      <div className="flex flex-wrap items-center gap-3 text-sm"><span className="badge-contour">Client inconnu</span><span className="chiffres">{client.code}</span>
        <span className="text-doux">créé à l'import d'une facture : complétez sa fiche pour libérer ses factures</span></div>
      {!lecture && (
        <form className="flex flex-wrap items-center gap-2" onSubmit={(e) => e.preventDefault()}>
          <label className="sr-only" htmlFor={`nom-${client.id}`}>Nom</label>
          <input id={`nom-${client.id}`} className="champ" placeholder="Nom du client" value={nom} onChange={(e) => setNom(e.target.value)} />
          <label className="sr-only" htmlFor={`tel-${client.id}`}>Téléphone</label>
          <input id={`tel-${client.id}`} className="champ chiffres" placeholder="+229 01…" value={telephone} onChange={(e) => setTelephone(e.target.value)} />
          <label className="sr-only" htmlFor={`canal-${client.id}`}>Canal</label>
          <select id={`canal-${client.id}`} className="champ" value={canal} onChange={(e) => setCanal(e.target.value)}>
            <option value="sms">SMS</option><option value="whatsapp">WhatsApp</option><option value="email">E-mail</option>
          </select>
          <BoutonAction variante="second" disabled={!nom.trim()} onClick={() => agir(() => api<{ factures_liberees: number }>(`/api/clients/${client.id}/valider`, { corps: { nom, telephone: telephone || null, canal_prefere: canal } }),
                                                                                    (r) => `Client validé, ${r.factures_liberees} facture(s) libérée(s)`).then(apres)}>
            Valider le client
          </BoutonAction>
        </form>
      )}
    </div>
  );
}
