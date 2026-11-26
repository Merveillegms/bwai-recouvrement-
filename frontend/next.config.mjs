/** Le frontend appelle l'API par le même domaine : /api/* est relayé vers FastAPI.
 *  En local : http://127.0.0.1:8000. En ligne (Vercel) : la variable RECOUVREMENT_API donne l'adresse Render. */
if (process.env.VERCEL && !process.env.RECOUVREMENT_API) {
  throw new Error(
    "Variable RECOUVREMENT_API manquante : renseignez l'adresse de l'API Render " +
    "(par exemple https://recouvra-api.onrender.com) dans Settings > Environment Variables, puis redéployez.",
  );
}
const API = (process.env.RECOUVREMENT_API ?? "http://127.0.0.1:8000").replace(/\/+$/, "");

/** @type {import('next').NextConfig} */
const config = {
  reactStrictMode: true,
  poweredByHeader: false,
  async rewrites() {
    return [{ source: "/api/:chemin*", destination: `${API}/api/:chemin*` }];
  },
};

export default config;
