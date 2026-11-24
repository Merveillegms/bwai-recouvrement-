"use client";

import Link from "next/link";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { session } from "@/lib/api";

/* Page d'accueil de Recouvra. Une animation principale (la file du jour qui se trie, puis un paiement qui
   annule une relance), des compteurs et des apparitions au défilement. Tout reste lisible au repos et
   l'animation s'arrête si l'utilisateur a réduit les animations dans son système. */

const FACTURES = [
  { id: "a", nom: "Supermarché Bon Prix", meta: "64 j de retard · R4", montant: "5 300 000", score: 92, etiquette: "À valider", sombre: true },
  { id: "b", nom: "Quincaillerie Moderne", meta: "349 j de retard · R5", montant: "249 000", score: 78, etiquette: "Escalade" },
  { id: "c", nom: "Maquis Chez Awa", meta: "52 j de retard · R4", montant: "75 000", score: 44, etiquette: "À valider", sombre: true },
  { id: "d", nom: "Boulangerie Les Délices", meta: "25 j de retard · R2", montant: "100 000", score: 14, etiquette: "Automatique" },
];
const INITIAL = ["d", "c", "a", "b"];
const FINAL = ["a", "b", "c", "d"];

function animationsReduites() {
  return typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function FileAnimee() {
  const [ordre, setOrdre] = useState(FINAL);
  const [scores, setScores] = useState(true);
  const [paye, setPaye] = useState(true);
  const minuteurs = useRef<ReturnType<typeof setTimeout>[]>([]);

  const jouer = () => {
    minuteurs.current.forEach(clearTimeout);
    if (animationsReduites()) { setOrdre(FINAL); setScores(true); setPaye(true); return; }
    setOrdre(INITIAL); setScores(false); setPaye(false);
    const t = (ms: number, fn: () => void) => minuteurs.current.push(setTimeout(fn, ms));
    t(450, () => setScores(true));
    t(1600, () => setOrdre(FINAL));
    t(3400, () => setPaye(true));
  };
  useEffect(() => { jouer(); return () => minuteurs.current.forEach(clearTimeout); }, []);

  return (
    <div className="relative overflow-hidden rounded-[18px] bg-encre p-[18px] text-white shadow-flottant" aria-label="Démonstration animée de la file du jour">
      <div className="flex items-center justify-between px-1 pb-3.5 text-[13px]">
        <strong className="font-titre text-[15px]">File du jour</strong>
        <button type="button" onClick={jouer} className="rounded-md bg-encre-2 px-2.5 py-1 text-[11.5px] text-[#c9d3e3] hover:text-white">Rejouer</button>
      </div>
      <div className="relative" style={{ height: FACTURES.length * 72 - 8 }}>
        {FACTURES.map((f) => {
          const rang = ordre.indexOf(f.id);
          const annulee = paye && f.id === "d";
          return (
            <div key={f.id} className="absolute inset-x-0 grid h-16 grid-cols-[26px_minmax(0,1fr)_auto] items-center gap-3 rounded-xl border px-3.5 transition-all duration-700 [transition-timing-function:cubic-bezier(.2,.8,.2,1)]"
                 style={{ transform: `translateY(${rang * 72}px)`, opacity: annulee ? 0.5 : 1,
                          background: annulee ? "#0f2e2a" : "#131e35", borderColor: annulee ? "#135c46" : "#1d2a45" }}>
              <span className="grid h-[26px] w-[26px] place-items-center rounded-md bg-encre-2 text-[12px] font-semibold text-[#c9d3e3]">{rang + 1}</span>
              <span className="min-w-0">
                <span className="block truncate text-[14px] font-semibold">{f.nom}</span>
                <span className="hidden text-[11.5px] text-[#8b97ad] sm:block">{f.meta}</span>
                <span className="mt-1.5 block h-1 overflow-hidden rounded bg-encre-2">
                  <span className="block h-full rounded bg-vert transition-[width] duration-1000" style={{ width: scores ? `${f.score}%` : "0%" }} />
                </span>
              </span>
              <span className="text-right">
                <span className="chiffres block text-[13px]">{f.montant}</span>
                <span className={`mt-1 inline-block rounded-full px-2 py-0.5 text-[10.5px] font-semibold transition-colors ${annulee ? "bg-vert text-white" : f.sombre ? "bg-white text-encre" : "bg-encre-2 text-[#c9d3e3]"}`}>
                  {annulee ? "Payée, annulée" : f.etiquette}
                </span>
              </span>
            </div>
          );
        })}
      </div>
      <div role="status" className={`mt-4 flex items-center gap-3 rounded-xl bg-white px-3.5 py-3 text-[13px] text-encre transition-all duration-500 ${paye ? "translate-y-0 opacity-100" : "translate-y-3 opacity-0"}`}>
        <span className="grid h-8 w-8 flex-none place-items-center rounded-full bg-vert font-bold text-white">✓</span>
        <span><b className="block">Paiement MTN MoMo reçu</b>Boulangerie Les Délices : relance annulée avant l'envoi.</span>
      </div>
    </div>
  );
}

function Revele({ children, className = "", delai = 0 }: { children: ReactNode; className?: string; delai?: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const [cache, setCache] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el || animationsReduites() || el.getBoundingClientRect().top < window.innerHeight) return;  // déjà visible : jamais caché
    setCache(true);
    const obs = new IntersectionObserver(([e]) => { if (e.isIntersecting) { setCache(false); obs.disconnect(); } }, { threshold: 0.15 });
    obs.observe(el);
    return () => obs.disconnect();
  }, []);
  return (
    <div ref={ref} className={`transition-all duration-700 ${cache ? "translate-y-4 opacity-0" : "translate-y-0 opacity-100"} ${className}`}
         style={{ transitionDelay: `${delai}ms` }}>{children}</div>
  );
}

function Compteur({ fin, suffixe = "" }: { fin: number; suffixe?: string }) {
  const ref = useRef<HTMLSpanElement>(null);
  const [valeur, setValeur] = useState(fin);
  useEffect(() => {
    const el = ref.current;
    if (!el || fin === 0 || animationsReduites()) return;
    const obs = new IntersectionObserver(([e]) => {
      if (!e.isIntersecting) return;
      obs.disconnect();
      const debut = performance.now();
      const pas = (t: number) => { const p = Math.min(1, (t - debut) / 1200); setValeur(Math.round(fin * (1 - (1 - p) ** 3))); if (p < 1) requestAnimationFrame(pas); };
      setValeur(0);
      requestAnimationFrame(pas);
    }, { threshold: 0.4 });
    obs.observe(el);
    return () => obs.disconnect();
  }, [fin]);
  return <span ref={ref} className="tabulaire">{valeur}{suffixe}</span>;
}

const MARQUEURS = [
  ["[[CLIENT]]", "Boulangerie Les Délices"],
  ["[[FACTURES]]", "Facture FAC-2026-0125, échéance 20/11/2026 : reste à payer 100 000 FCFA"],
  ["[[PAIEMENT]]", "MTN MoMo 01 97 00 00 00, référence RC-2557-7942-8"],
];

function MessageIA() {
  const ref = useRef<HTMLDivElement>(null);
  const [remplis, setRemplis] = useState(MARQUEURS.length);
  useEffect(() => {
    const el = ref.current;
    if (!el || animationsReduites()) return;
    setRemplis(0);
    const minuteurs: ReturnType<typeof setTimeout>[] = [];
    const obs = new IntersectionObserver(([e]) => {
      if (!e.isIntersecting) return;
      obs.disconnect();
      MARQUEURS.forEach((_, i) => minuteurs.push(setTimeout(() => setRemplis(i + 1), 800 + i * 750)));
    }, { threshold: 0.4 });
    obs.observe(el);
    return () => { obs.disconnect(); minuteurs.forEach(clearTimeout); };
  }, []);
  const m = (i: number) => (
    <span className={`transition-colors duration-500 ${i < remplis ? "font-semibold text-encre" : "chiffres rounded-md bg-vert-pale px-1.5 text-[13px] text-vert-fonce"}`}>
      {i < remplis ? MARQUEURS[i][1] : MARQUEURS[i][0]}
    </span>
  );
  return (
    <div ref={ref} className="carte p-6 text-[15px] leading-[1.75] shadow-flottant">
      <div className="mb-3.5 flex justify-between border-b border-filet pb-3 text-[12px] text-doux"><span>WhatsApp · relance R2</span><span>Contrôlé, prêt à valider</span></div>
      Bonjour {m(0)}, nous espérons que vous allez bien et que vos affaires se portent bien.<br /><br />
      Sauf erreur de notre part, le règlement suivant reste en attente malgré notre premier rappel :<br />{m(1)}<br /><br />
      {m(2)}<br /><br />Bonne journée à vous.
    </div>
  );
}

export function Accueil() {
  const [connecte, setConnecte] = useState(false);
  useEffect(() => setConnecte(!!session()), []);
  const cible = connecte ? "/app" : "/connexion";
  const bande = { paddingLeft: "max(20px, env(safe-area-inset-left, 0px))", paddingRight: "max(20px, env(safe-area-inset-right, 0px))" };

  return (
    <div className="bg-white text-[16px] text-encre">
      <header className="sticky z-30 border-b border-filet bg-white/90 backdrop-blur" style={{ ...bande, top: "env(safe-area-inset-top, 0px)" }}>
        <div className="mx-auto flex max-w-[1160px] items-center gap-7 py-3.5">
          <Link href="/" className="flex items-center gap-2.5 font-titre text-[18px] font-bold">
            <span className="grid h-[30px] w-[30px] place-items-center rounded-lg bg-vert text-[15px] text-white">R</span>Recouvra
          </Link>
          <nav className="hidden gap-6 text-[14.5px] text-doux md:flex" aria-label="Sections">
            <a href="#fonctionnement" className="hover:text-encre">Fonctionnement</a>
            <a href="#garde-fous" className="hover:text-encre">Garde-fous</a>
            <a href="#ia" className="hover:text-encre">IA encadrée</a>
          </nav>
          <Link href={cible} className="btn ml-auto">{connecte ? "Ouvrir l'application" : "Se connecter"}</Link>
        </div>
      </header>

      <section style={bande}>
        <div className="mx-auto grid max-w-[1160px] items-center gap-14 py-14 md:py-20 lg:grid-cols-[1fr_1.05fr]">
          <Revele>
            <span className="text-[12.5px] font-semibold uppercase tracking-[0.14em] text-vert">Recouvrement des factures impayées</span>
            <h1 className="mt-4 text-[clamp(2.3rem,5vw,3.6rem)] font-bold leading-[1.05]">La bonne relance, <span className="text-vert">au bon moment.</span></h1>
            <p className="mt-5 max-w-[34rem] text-[18px] text-doux">Recouvra priorise vos factures en retard, prépare des relances courtoises par SMS, WhatsApp ou e-mail, et ne relance jamais une facture déjà payée. Chaque décision est expliquée et inscrite au journal.</p>
            <div className="mt-8 flex flex-wrap gap-3">
              <Link href={cible} className="btn px-5 py-3 text-[15px]">Ouvrir l'application</Link>
              <a href="#fonctionnement" className="btn-sec px-5 py-3 text-[15px]">Voir comment ça marche</a>
            </div>
            <div className="mt-7 flex flex-wrap gap-x-5 gap-y-2 text-[14px] text-doux">
              {["Fonctionne hors ligne", "Validation humaine des cas sensibles", "Paiements mobile money"].map((t) => (
                <span key={t} className="flex items-center gap-2"><span className="h-1.5 w-1.5 rounded-full bg-vert" />{t}</span>
              ))}
            </div>
          </Revele>
          <Revele delai={150}><FileAnimee /></Revele>
        </div>
      </section>

      <section className="bg-encre text-white" style={bande} aria-label="Résultats mesurés sur le jeu de test">
        <div className="mx-auto grid max-w-[1160px] grid-cols-2 gap-8 py-12 md:grid-cols-4">
          {[
            [<Compteur key="0" fin={0} />, "facture payée relancée sur tout le jeu de test piégé"],
            [<Compteur key="1" fin={0} />, "envoi en double, même après une coupure brutale du programme"],
            [<span key="2" className="text-vert"><Compteur fin={100} suffixe=" %" /></span>, "des décisions retrouvées et expliquées à partir du seul journal"],
            [<span key="3" className="text-vert"><Compteur fin={300} /></span>, "tests automatiques qui vérifient chaque règle à chaque version"],
          ].map(([valeur, texte], i) => (
            <Revele key={i} delai={i * 90}>
              <div className="font-titre text-[clamp(2rem,3.6vw,2.8rem)] font-bold leading-none">{valeur}</div>
              <p className="mt-2 max-w-[16rem] text-[14.5px] text-[#a9b4c8]">{texte}</p>
            </Revele>
          ))}
        </div>
      </section>

      <section id="fonctionnement" style={bande}>
        <div className="mx-auto grid max-w-[1160px] gap-11 py-20 md:py-24">
          <Revele className="grid max-w-[40rem] gap-3">
            <span className="text-[12.5px] font-semibold uppercase tracking-[0.14em] text-vert">Fonctionnement</span>
            <h2 className="text-[clamp(1.8rem,3.4vw,2.5rem)] font-bold leading-tight">Quatre étapes, de l'import à l'encaissement.</h2>
            <p className="text-[17px] text-doux">Les montants, les retards et les priorités sont calculés par des règles écrites et testées. Aucune estimation, aucune boîte noire.</p>
          </Revele>
          <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
            {[
              ["01", "Importer", "Fichiers CSV ou Excel, encodages et colonnes variés. Doublons, champs manquants et montants aberrants sont signalés avec leur motif."],
              ["02", "Prioriser", "Un score transparent combine l'ancienneté, le solde et l'historique du client. Chaque rang s'explique en une phrase."],
              ["03", "Relancer", "Une séquence graduée, un seul message par client et par jour, avec la référence de paiement mobile money à citer."],
              ["04", "Maîtriser", "Litiges et gros montants passent par un validateur. Tout est revérifié juste avant l'envoi, puis journalisé."],
            ].map(([n, t, d], i) => (
              <Revele key={n} delai={i * 90} className="grid content-start gap-2.5 border-t-2 border-filet pt-5">
                <span className="chiffres text-[13px] text-vert">{n}</span>
                <h3 className="text-[19px] font-semibold">{t}</h3>
                <p className="text-[15px] text-doux">{d}</p>
              </Revele>
            ))}
          </div>
        </div>
      </section>

      <section id="garde-fous" className="bg-fond" style={bande}>
        <div className="mx-auto grid max-w-[1160px] gap-11 py-20 md:py-24">
          <Revele className="grid max-w-[40rem] gap-3">
            <span className="text-[12.5px] font-semibold uppercase tracking-[0.14em] text-vert">Garde-fous</span>
            <h2 className="text-[clamp(1.8rem,3.4vw,2.5rem)] font-bold leading-tight">Sûr, même quand tout va mal.</h2>
            <p className="text-[17px] text-doux">Un paiement qui arrive pendant la préparation, un double clic, une coupure de courant : le système le détecte et ne fait jamais deux fois la même action.</p>
          </Revele>
          <div className="grid gap-4 md:grid-cols-2">
            {[
              ["Humain dans la boucle", "Litiges, gros montants, clients sensibles et relances fermes attendent un validateur. Chaque décision garde son auteur, son heure et son motif.", "M4 10.5l4 4 8-9"],
              ["Jamais de double envoi", "Chaque relance a une clé unique en base. Coupé en pleine file, le programme reprend là où il s'était arrêté, sans doublon.", "M3 5h14v10H3zM7 10h6"],
              ["Calculs déterministes", "Soldes, retards et arrondis sont exacts et vérifiables, en FCFA comme en euros. L'IA ne calcule jamais rien.", "M10 3v14M3 10h14"],
              ["Journal infalsifiable", "Chaque ligne porte l'empreinte de la précédente. Une modification après coup est détectée immédiatement.", "M5 4h10M5 8h10M5 12h6M5 16h8"],
            ].map(([t, d, chemin], i) => (
              <Revele key={t} delai={i * 90} className="carte grid content-start gap-2.5 p-7">
                <span className="grid h-10 w-10 place-items-center rounded-[10px] bg-vert-pale text-vert">
                  <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={chemin} /></svg>
                </span>
                <h3 className="text-[19px] font-semibold">{t}</h3>
                <p className="text-[15px] text-doux">{d}</p>
              </Revele>
            ))}
          </div>
        </div>
      </section>

      <section id="ia" style={bande}>
        <div className="mx-auto grid max-w-[1160px] items-center gap-12 py-20 md:py-24 lg:grid-cols-[0.9fr_1.1fr]">
          <Revele>
            <span className="text-[12.5px] font-semibold uppercase tracking-[0.14em] text-vert">IA encadrée</span>
            <h2 className="mt-3 text-[clamp(1.8rem,3.4vw,2.5rem)] font-bold leading-tight">L'IA rédige. Le code vérifie.</h2>
            <p className="mt-3 text-[17px] text-doux">Le modèle de langage ne voit ni nom, ni montant, ni numéro. Il écrit avec des marqueurs, et le code y insère les valeurs exactes.</p>
            <ul className="mt-6 grid gap-3 text-[15.5px] text-doux">
              {["Un seul chiffre écrit par le modèle et le message est rejeté.", "Ton contrôlé : vouvoiement, aucune menace, aucune mention de tiers.",
                "Les réponses des clients sont classées hors ligne, puis confirmées par un humain.", "Un interrupteur coupe l'IA : tout continue de fonctionner sans elle."].map((t) => (
                <li key={t} className="grid grid-cols-[22px_minmax(0,1fr)] gap-2.5"><span className="font-bold text-vert">✓</span>{t}</li>
              ))}
            </ul>
          </Revele>
          <Revele delai={120}><MessageIA /></Revele>
        </div>
      </section>

      <section className="bg-fond" style={bande}>
        <Revele className="mx-auto grid max-w-[1160px] gap-3 py-20">
          <span className="text-[12.5px] font-semibold uppercase tracking-[0.14em] text-vert">Pensé pour le Bénin</span>
          <h2 className="max-w-[40rem] text-[clamp(1.8rem,3.4vw,2.5rem)] font-bold leading-tight">Vos clients paient par mobile money. Recouvra le sait.</h2>
          <p className="max-w-[44rem] text-[17px] text-doux">Chaque facture reçoit une référence courte avec chiffre de contrôle. Le client la cite en payant, et le paiement est rapproché tout seul. Une faute de frappe est détectée, jamais appliquée à la mauvaise facture.</p>
          <div className="mt-2 flex flex-wrap gap-2.5">
            {["MTN MoMo", "Moov Money", "Celtiis Cash", "FCFA", "+229"].map((t) => <span key={t} className="rounded-full border border-filet bg-white px-4 py-2 text-[14px] font-semibold">{t}</span>)}
          </div>
        </Revele>
      </section>

      <section className="bg-encre text-white" style={bande}>
        <div className="mx-auto flex max-w-[1160px] flex-wrap items-center justify-between gap-7 py-20">
          <div>
            <h2 className="max-w-[30rem] text-[clamp(1.8rem,3.4vw,2.5rem)] font-bold leading-tight">Prêt à relancer sans risque ?</h2>
            <p className="mt-2.5 text-[#a9b4c8]">Chargez le jeu de démonstration et voyez la file du jour se construire en un clic.</p>
          </div>
          <Link href={cible} className="btn px-5 py-3 text-[15px]">Ouvrir l'application</Link>
        </div>
      </section>

      <footer className="border-t border-filet" style={bande}>
        <div className="mx-auto flex max-w-[1160px] flex-wrap justify-between gap-3 py-7 text-[13.5px] text-doux">
          <span>Recouvra · Hackathon BWAI 2026</span><span>Prototype local, données fictives, licence MIT</span>
        </div>
      </footer>
    </div>
  );
}
