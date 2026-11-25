/* Formes des réponses de l'API (miroir des dictionnaires renvoyés par FastAPI).
   Les chemins et corps de requête sont aussi décrits par lib/api-schema.d.ts, généré depuis l'OpenAPI
   (npm run types). Aucun calcul ici : les montants arrivent déjà formatés (champs *_affiche). */

export type Role = "gestionnaire" | "validateur" | "auditeur";
export type Utilisateur = { id: number; identifiant: string; nom: string; role: Role };

export type Statut = "a_echoir" | "echue" | "partiellement_payee" | "payee" | "en_litige" | "suspendue" | "cloturee";

export type Facture = {
  id: number; numero: string; client_id: number; code_client: string; nom_client: string;
  devise: string; decimales: number; date_emission: string; date_echeance: string; reference_paiement: string;
  montant_ttc: number; total_paye: number; total_avoirs: number; solde: number; trop_percu: number;
  montant_ttc_affiche: string; total_paye_affiche: string; total_avoirs_affiche: string; solde_affiche: string;
  trop_percu_affiche: string; jours_retard: number; tranche: string | null; statut: Statut; version: number;
  en_litige: boolean; suspendue: boolean; a_verifier: boolean; motif_verification: string | null;
  motif_cloture: string | null; drapeaux: string[];
};

export type Etape = { etape: string; jours: number; ton: string; validation: boolean; active: boolean };

export type Priorite = {
  rang: number; facture: Facture; score: string; etape: Etape; validation_humaine: boolean;
  raisons_validation: string[]; explication: string; detail: string[];
  facteurs: { anciennete: string; solde: string; historique: string };
  poids: { anciennete: string; solde: string; historique: string };
  points: { anciennete: string; solde: string; historique: string };
  points_max: { anciennete: string; solde: string; historique: string };
  historique: { nb_reglees: number; nb_reglees_en_retard: number; retard_moyen_reglement: number;
                nb_echues_ouvertes: number; derniere_relance: string | null; promesse_jusqu_au: string | null };
};

export type Exclusion = { facture: Facture; code: string; motif: string };

export type FileDuJour = {
  date_reference: string;
  resume: { a_relancer: number; validation_humaine: number; exclues: number; affichees: number };
  file: Priorite[]; exclues: Exclusion[];
};

export type EtatSysteme = {
  date_du_jour: string; date_simulee: boolean; arret_urgence: boolean; ia_active: boolean; entreprise: string;
  factures: number; reponses_a_traiter: number; relances: Record<string, number>;
  a_traiter: { lots_a_valider: number; lots_a_envoyer: number; paiements_a_valider: number;
               anomalies_ouvertes: number; factures_a_verifier: number; relances_en_echec: number };
};

export type LotValidation = {
  lot: string; client: { id: number; code: string; nom: string; canal_prefere: string; sensible: number };
  canal: string; escalade: boolean; message: string; raisons: string[]; groupable: boolean; redige_par_ia: boolean;
  date_preparation: string; factures: (Facture & { etape: string })[];
};

export type Paiement = {
  id: number; id_transaction: string; date_paiement: string; montant: number; montant_affiche: string; devise: string;
  reference_citee: string | null; telephone_payeur: string | null; operateur: string | null;
  statut_rapprochement: string; motif_rapprochement: string | null; facture_id: number | null;
  facture_proposee_id: number | null; methode_rapprochement: string | null;
};

export type Evenement = { id: number; horodatage: string; acteur: string; type_acteur: string; action: string;
                          regle: string | null; libelle: string };

export type LigneJournal = Evenement & { objet_type: string; objet_id: string | null; hash: string;
                                         avant: unknown; apres: unknown };

export type Anomalie = { id: number; import_id: number; ligne: number; gravite: string; code: string; message: string;
                         donnees: Record<string, string>; fichier: string; type: string; resolution: string | null };

export type RapportImport = {
  import_id: number; type: string; fichier: string; format: string; encodage: string | null; separateur: string | null;
  correspondance: Record<string, string | null>; lignes_lues: number; lignes_acceptees: number;
  lignes_avertissement: number; lignes_rejetees: number;
  anomalies: { ligne: number; gravite: string; code: string; message: string }[];
  rapprochement?: Record<string, number>;
};

export type Apercu = { format: string; encodage: string | null; separateur: string | null; entetes: string[];
                       correspondance: Record<string, string | null>; champs_manquants: string[];
                       lignes: string[][]; nombre_lignes: number };

type Montants = Record<string, { montant: number; affiche: string }>;
export type Indicateurs = {
  date_reference: string; periode: { debut: string; fin: string };
  encours: { total_du: Montants; total_echu: Montants; factures_echues: number };
  tranches: { tranche: string; nombre: number; montants: Montants }[];
  top10: { facture_id: number; numero: string; client: string; jours_retard: number; solde: number; affiche: string }[];
  relances: { par_statut: Record<string, number>; lots_a_valider: number; annulees_avant_envoi: number };
  efficacite: { recouvre_apres_relance: Montants; paiements_apres_relance: number; delai_moyen_jours: number | null;
                delai_moyen_par_etape: Record<string, number>; promesses: { tenues: number; non_tenues: number; en_cours: number } };
  garde_fous: Record<string, number | Record<string, number>>;
};

export type EtatIA = {
  active: boolean;
  redaction: { configuree: boolean; fournisseur: string | null; modele: string | null; appels: Record<string, number> };
  classification: { modele: string; categories: string[]; exactitude: number | null; rappel_litige: number | null; seuil_confiance: number };
};

export type Proposition = { categorie: string; confiance: number; probabilites: Record<string, number>; date: string | null;
                            litige_possible: boolean; mots_decisifs: string[]; confiance_faible: boolean };

export type ReponseEntrante = { id: number; client_id: number; code_client: string; nom_client: string; facture_id: number | null;
  numero: string | null; texte: string; recue_le: string; categorie_proposee: string | null; confiance: number | null;
  probabilites: Record<string, number> | null; date_proposee: string | null; litige_possible: number; statut: string };
