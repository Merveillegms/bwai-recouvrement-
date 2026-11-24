import type { Config } from "tailwindcss";

/* Piste « Registre comptable » : papier, encre, filets, tampons. Les couleurs viennent des variables CSS
   de app/globals.css, pour qu'un seul endroit définisse la palette. */
const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        papier: "var(--papier)",
        "papier-fonce": "var(--papier-fonce)",
        encre: "var(--encre)",
        "encre-pale": "var(--encre-pale)",
        filet: "var(--filet)",
        lavis: "var(--lavis)",
        tampon: "var(--tampon)",
        ok: "var(--ok)",
        alerte: "var(--alerte)",
      },
      fontFamily: {
        titre: ["Spectral", "Georgia", "serif"],
        texte: ["IBM Plex Sans", "Segoe UI", "system-ui", "sans-serif"],
        chiffre: ["IBM Plex Mono", "Consolas", "monospace"],
      },
    },
  },
  plugins: [],
};

export default config;
