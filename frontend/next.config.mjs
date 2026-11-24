/** Le frontend appelle l'API locale par le même domaine : /api/* est relayé vers FastAPI. */
const API = process.env.RECOUVREMENT_API ?? "http://127.0.0.1:8000";

/** @type {import('next').NextConfig} */
const config = {
  reactStrictMode: true,
  poweredByHeader: false,
  async rewrites() {
    return [{ source: "/api/:chemin*", destination: `${API}/api/:chemin*` }];
  },
};

export default config;
