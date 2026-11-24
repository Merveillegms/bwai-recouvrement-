-- IA encadrée : journal des appels, réponses entrantes à classer, messages rédigés par l'IA.

-- Chaque appel à un modèle : entrée (anonymisée), sortie brute, décision des contrôles.
CREATE TABLE ia_appels (
    id            INTEGER PRIMARY KEY,
    horodatage    TEXT NOT NULL,
    fonction      TEXT NOT NULL CHECK (fonction IN ('redaction', 'classification')),
    fournisseur   TEXT NOT NULL,
    modele        TEXT NOT NULL,
    objet         TEXT,                 -- lot de relance ou réponse entrante concernée
    entree        TEXT NOT NULL,        -- ce qui a été envoyé au modèle (jamais de nom, montant ni téléphone)
    sortie        TEXT,
    statut        TEXT NOT NULL CHECK (statut IN ('accepte', 'rejete', 'erreur')),
    raisons       TEXT,                 -- pourquoi la sortie a été rejetée
    duree_ms      INTEGER
);

-- Message reçu d'un client (SMS, WhatsApp…), avec la proposition du classifieur, en attente d'un humain.
CREATE TABLE reponses_entrantes (
    id                  INTEGER PRIMARY KEY,
    client_id           INTEGER NOT NULL REFERENCES clients(id),
    facture_id          INTEGER REFERENCES factures(id),
    texte               TEXT NOT NULL,
    recue_le            TEXT NOT NULL,
    categorie_proposee  TEXT,
    confiance           REAL,
    probabilites        TEXT CHECK (probabilites IS NULL OR json_valid(probabilites)),
    date_proposee       TEXT,
    litige_possible     INTEGER NOT NULL DEFAULT 0 CHECK (litige_possible IN (0, 1)),
    statut              TEXT NOT NULL DEFAULT 'a_traiter' CHECK (statut IN ('a_traiter', 'confirmee', 'corrigee', 'ecartee')),
    categorie_retenue   TEXT,
    traitee_par         TEXT,
    traitee_le          TEXT,
    reponse_id          INTEGER REFERENCES reponses_client(id)
);

ALTER TABLE relances ADD COLUMN redige_par_ia INTEGER NOT NULL DEFAULT 0 CHECK (redige_par_ia IN (0, 1));
ALTER TABLE relances ADD COLUMN message_gabarit TEXT;   -- texte du gabarit fixe, pour revenir en arrière

INSERT INTO parametres (cle, valeur, description) VALUES
    ('ia_seuil_confiance', '0.6',
        'En dessous, la catégorie proposée par le classifieur est signalée « confiance faible »'),
    ('ia_seuil_litige', '0.25',
        'Probabilité de litige à partir de laquelle un litige possible est signalé (priorité au rappel)'),
    ('ia_validation_obligatoire', 'true',
        'Un message rédigé par l''IA passe toujours en validation humaine');
