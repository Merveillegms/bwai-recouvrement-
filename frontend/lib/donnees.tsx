"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { api, ErreurApi } from "./api";
import type { EtatSysteme, Utilisateur } from "./types";

/** Charge une ressource de l'API et permet de la recharger après une action. */
export function useDonnees<T>(chemin: string | null) {
  const [donnees, setDonnees] = useState<T | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  const [chargement, setChargement] = useState(true);
  const demande = useRef(0);

  const recharger = useCallback(async () => {
    if (!chemin) return;
    const numero = ++demande.current;
    setChargement(true);
    try {
      const d = await api<T>(chemin);
      if (numero === demande.current) {
        setDonnees(d);
        setErreur(null);
      }
    } catch (e) {
      if (numero === demande.current) setErreur(e instanceof ErreurApi ? e.message : "Erreur inattendue");
    } finally {
      if (numero === demande.current) setChargement(false);
    }
  }, [chemin]);

  useEffect(() => {
    recharger();
  }, [recharger]);

  return { donnees, erreur, chargement, recharger };
}

/* ------------------------------------------------------------- contexte de l'application */
type Message = { id: number; texte: string; ton: "ok" | "erreur" };

type Contexte = {
  utilisateur: Utilisateur;
  systeme: EtatSysteme | null;
  rafraichirSysteme: () => Promise<void>;
  notifier: (texte: string, ton?: "ok" | "erreur") => void;
  /** Exécute une action : notifie le résultat ou l'erreur lisible, puis rafraîchit l'en-tête. */
  agir: <T>(action: () => Promise<T>, succes?: string | ((r: T) => string)) => Promise<T | undefined>;
};

const Ctx = createContext<Contexte | null>(null);

export function useApp(): Contexte {
  const c = useContext(Ctx);
  if (!c) throw new Error("useApp hors de FournisseurApp");
  return c;
}

export function FournisseurApp({ utilisateur, children }: { utilisateur: Utilisateur; children: ReactNode }) {
  const [systeme, setSysteme] = useState<EtatSysteme | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);

  const rafraichirSysteme = useCallback(async () => {
    try {
      setSysteme(await api<EtatSysteme>("/api/etat-systeme"));
    } catch {
      /* l'en-tête reste sur sa dernière valeur */
    }
  }, []);

  useEffect(() => {
    rafraichirSysteme();
  }, [rafraichirSysteme]);

  const notifier = useCallback((texte: string, ton: "ok" | "erreur" = "ok") => {
    const id = Date.now() + Math.random();
    setMessages((m) => [...m, { id, texte, ton }]);
    setTimeout(() => setMessages((m) => m.filter((x) => x.id !== id)), ton === "erreur" ? 9000 : 4500);
  }, []);

  const agir = useCallback(async <T,>(action: () => Promise<T>, succes?: string | ((r: T) => string)) => {
    try {
      const r = await action();
      if (succes) notifier(typeof succes === "function" ? succes(r) : succes);
      await rafraichirSysteme();
      return r;
    } catch (e) {
      notifier(e instanceof ErreurApi ? e.message : "Action impossible : erreur inattendue", "erreur");
      return undefined;
    }
  }, [notifier, rafraichirSysteme]);

  return (
    <Ctx.Provider value={{ utilisateur, systeme, rafraichirSysteme, notifier, agir }}>
      {children}
      <div className="fixed z-50 flex flex-col gap-2" aria-live="polite"
           style={{ right: "max(16px, env(safe-area-inset-right, 0px))", bottom: "calc(16px + env(safe-area-inset-bottom, 0px))", maxWidth: "min(26rem, calc(100vw - 32px))" }}>
        {messages.map((m) => (
          <div key={m.id} role={m.ton === "erreur" ? "alert" : "status"}
               className={`flex items-start gap-3 rounded-xl px-4 py-3 text-[13.5px] shadow-flottant ${m.ton === "erreur" ? "bg-encre text-white" : "border border-filet bg-white text-encre"}`}>
            <span className={`mt-0.5 grid h-5 w-5 flex-none place-items-center rounded-full text-[11px] font-bold ${m.ton === "erreur" ? "bg-white text-encre" : "bg-vert text-white"}`} aria-hidden="true">
              {m.ton === "erreur" ? "!" : "✓"}
            </span>
            {m.texte}
          </div>
        ))}
      </div>
    </Ctx.Provider>
  );
}
