import type { Config } from "tailwindcss";

/* Charte Recouvra : deux couleurs seulement, l'encre (bleu nuit presque noir) et le vert émeraude,
   sur des gris neutres légèrement teintés. Pas d'italique, pas de troisième couleur. */
const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        encre: "#0b1324",
        "encre-2": "#18233a",
        "encre-3": "#24314d",
        vert: "#0e9f6e",
        "vert-fonce": "#0b8a5f",
        "vert-pale": "#e7f6f0",
        fond: "#f6f8fa",
        doux: "#566074",
        filet: "#e3e7ed",
        "filet-2": "#eef1f5",
      },
      fontFamily: {
        titre: ["Sora", "Segoe UI", "system-ui", "sans-serif"],
        texte: ["Inter", "Segoe UI", "system-ui", "sans-serif"],
        chiffre: ["JetBrains Mono", "Consolas", "monospace"],
      },
      boxShadow: {
        carte: "0 1px 2px rgba(11, 19, 36, .04)",
        flottant: "0 24px 50px -28px rgba(11, 19, 36, .45)",
      },
    },
  },
  plugins: [],
};

export default config;
