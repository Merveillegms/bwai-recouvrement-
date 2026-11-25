/* Mots du métier affichés à l'écran (aucune logique : de simples traductions de codes). */

export const STATUTS: Record<string, string> = {
  a_echoir: "à échoir", echue: "échue", partiellement_payee: "partiellement payée", payee: "payée",
  en_litige: "en litige", suspendue: "suspendue", cloturee: "clôturée",
};

export const TRANCHES: Record<string, string> = {
  non_echue: "non échue", "1-15": "1 à 15 j", "16-30": "16 à 30 j", "31-60": "31 à 60 j", "61-90": "61 à 90 j",
  plus_90: "plus de 90 j",
};

export const DRAPEAUX: Record<string, string> = {
  gros_montant: "gros montant", client_sensible: "client sensible", sans_contact: "sans contact",
  a_verifier: "à vérifier",
};

export const CANAUX: Record<string, string> = { sms: "SMS", whatsapp: "WhatsApp", email: "e-mail" };

export const ROLES: Record<string, string> = {
  gestionnaire: "gestionnaire", validateur: "validateur", auditeur: "auditeur (lecture seule)",
};

export function date(iso: string | null | undefined): string {
  if (!iso) return "";
  const [a, m, j] = iso.slice(0, 10).split("-");
  return `${j}/${m}/${a}`;
}

export function dateLongue(iso: string): string {
  return new Date(`${iso.slice(0, 10)}T12:00:00`).toLocaleDateString("fr-FR", {
    weekday: "long", day: "numeric", month: "long", year: "numeric",
  });
}

export function heure(iso: string): string {
  return new Date(iso).toLocaleString("fr-FR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

export const CATEGORIES_REPONSE: Record<string, string> = {
  promesse: "Promesse de paiement", paiement_annonce: "Paiement annoncé", litige: "Litige",
  demande_delai: "Demande de délai", demande_info: "Demande d'information", sans_rapport: "Sans rapport",
};
