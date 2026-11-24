/* Icônes au trait, 16 px, couleur héritée. */
const base = { width: 16, height: 16, viewBox: "0 0 16 16", fill: "none", stroke: "currentColor", strokeWidth: 1.5,
               strokeLinecap: "round" as const, strokeLinejoin: "round" as const, "aria-hidden": true };

export const Icones = {
  jour: <svg {...base}><rect x="2" y="3" width="12" height="11" rx="2" /><path d="M2 6.5h12M5.5 1.5v3M10.5 1.5v3" /></svg>,
  validation: <svg {...base}><path d="M3 8.5l3 3 7-7" /></svg>,
  paiements: <svg {...base}><rect x="1.5" y="3.5" width="13" height="9" rx="1.5" /><path d="M1.5 6.5h13" /></svg>,
  reponses: <svg {...base}><path d="M2.5 3.5h11v7h-6l-3 2.5v-2.5h-2z" /></svg>,
  factures: <svg {...base}><path d="M4 1.5h5.5L12.5 4.5V14.5H4z" /><path d="M6 8h4.5M6 10.5h4.5" /></svg>,
  import: <svg {...base}><path d="M8 2v8M5 7l3 3 3-3M2.5 12.5h11" /></svg>,
  journal: <svg {...base}><path d="M3 3.5h10M3 8h10M3 12.5h6" /></svg>,
  tableau: <svg {...base}><path d="M2.5 13.5h11M4.5 11V8M8 11V4.5M11.5 11V6.5" /></svg>,
  reglages: <svg {...base}><circle cx="8" cy="8" r="2.2" /><path d="M8 1.5v2M8 12.5v2M1.5 8h2M12.5 8h2M3.4 3.4l1.4 1.4M11.2 11.2l1.4 1.4M3.4 12.6l1.4-1.4M11.2 4.8l1.4-1.4" /></svg>,
  sortie: <svg {...base}><path d="M6 2.5H3.5v11H6M10 5l3 3-3 3M13 8H6" /></svg>,
  ia: <svg {...base}><path d="M8 1.5l1.6 3.4 3.4 1.6-3.4 1.6L8 11.5 6.4 8.1 3 6.5l3.4-1.6z" /><path d="M12.5 11l.7 1.5 1.3.5-1.3.5-.7 1.5-.7-1.5-1.3-.5 1.3-.5z" /></svg>,
};
