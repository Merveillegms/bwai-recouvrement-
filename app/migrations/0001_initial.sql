-- Schéma initial du système de recouvrement.
-- Montants : entiers en unités mineures de la devise (XOF/XAF : 0 décimale, EUR : centimes).
-- Dates : texte ISO 8601 (AAAA-MM-JJ) ; horodatages : ISO 8601 UTC.

CREATE TABLE devises (
    code       TEXT PRIMARY KEY CHECK (length(code) = 3),
    decimales  INTEGER NOT NULL CHECK (decimales BETWEEN 0 AND 3),
    libelle    TEXT NOT NULL
);

INSERT INTO devises (code, decimales, libelle) VALUES
    ('XOF', 0, 'Franc CFA (UEMOA)'),
    ('XAF', 0, 'Franc CFA (CEMAC)'),
    ('EUR', 2, 'Euro');

-- Règles réglables. Chaque modification incrémente la version et passe au journal.
CREATE TABLE parametres (
    cle          TEXT PRIMARY KEY,
    valeur       TEXT NOT NULL CHECK (json_valid(valeur)),
    description  TEXT NOT NULL,
    version      INTEGER NOT NULL DEFAULT 1,
    modifie_le   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    modifie_par  TEXT NOT NULL DEFAULT 'systeme'
);

INSERT INTO parametres (cle, valeur, description) VALUES
    ('seuil_gros_montant', '{"XOF": 1000000, "XAF": 1000000, "EUR": 1500}',
        'Solde restant (unités majeures) à partir duquel la validation humaine est obligatoire'),
    ('sequence_relances', '[
        {"etape": "R0", "jours": -3, "ton": "informatif", "validation": false, "active": false},
        {"etape": "R1", "jours": 1,  "ton": "tres_courtois", "validation": false, "active": true},
        {"etape": "R2", "jours": 10, "ton": "courtois", "validation": false, "active": true},
        {"etape": "R3", "jours": 30, "ton": "ferme", "validation": true, "active": true},
        {"etape": "R4", "jours": 45, "ton": "formel", "validation": true, "active": true},
        {"etape": "R5", "jours": 90, "ton": "escalade", "validation": true, "active": true}
    ]', 'Étapes de relance : jours par rapport à l''échéance et validation humaine'),
    ('delai_min_entre_relances_jours', '7', 'Délai minimal entre deux relances d''une même facture'),
    ('poids_priorite', '{"anciennete": 0.5, "solde": 0.3, "historique": 0.2}',
        'Poids des facteurs du score de priorité (somme = 1)'),
    ('fenetre_quasi_doublon_jours', '7', 'Écart maximal de dates d''émission pour un quasi-doublon'),
    ('facteur_montant_aberrant', '10', 'Montant > facteur × médiane des autres factures du client'),
    ('min_factures_montant_aberrant', '3', 'Nombre minimal d''autres factures pour juger un montant aberrant'),
    ('heures_envoi', '{"debut": "08:00", "fin": "19:00"}', 'Plage horaire raisonnable d''envoi'),
    ('date_du_jour_simulee', 'null', 'Date métier forcée (démo et tests) ; null = date réelle'),
    ('ia_active', 'false', 'Interrupteur global de l''IA'),
    ('arret_urgence', 'false', 'Suspend toutes les relances');

CREATE TABLE utilisateurs (
    id                 INTEGER PRIMARY KEY,
    identifiant        TEXT NOT NULL UNIQUE,
    nom                TEXT NOT NULL,
    role               TEXT NOT NULL CHECK (role IN ('gestionnaire', 'validateur', 'auditeur')),
    mot_de_passe_hash  TEXT NOT NULL,
    actif              INTEGER NOT NULL DEFAULT 1 CHECK (actif IN (0, 1))
);

CREATE TABLE imports (
    id                    INTEGER PRIMARY KEY,
    type                  TEXT NOT NULL CHECK (type IN ('clients', 'factures', 'paiements')),
    fichier               TEXT NOT NULL,
    empreinte             TEXT NOT NULL UNIQUE,  -- SHA-256 du contenu : un fichier n'entre qu'une fois
    importe_le            TEXT NOT NULL,
    importe_par           TEXT NOT NULL,
    lignes_lues           INTEGER NOT NULL,
    lignes_acceptees      INTEGER NOT NULL,
    lignes_rejetees       INTEGER NOT NULL,
    lignes_avertissement  INTEGER NOT NULL
);

CREATE TABLE import_anomalies (
    id         INTEGER PRIMARY KEY,
    import_id  INTEGER NOT NULL REFERENCES imports(id),
    ligne      INTEGER NOT NULL,
    gravite    TEXT NOT NULL CHECK (gravite IN ('rejet', 'avertissement')),
    code       TEXT NOT NULL,
    message    TEXT NOT NULL,
    donnees    TEXT NOT NULL CHECK (json_valid(donnees))
);

CREATE TABLE clients (
    id                 INTEGER PRIMARY KEY,
    code               TEXT NOT NULL UNIQUE,
    nom                TEXT NOT NULL,
    telephone          TEXT,
    email              TEXT,
    canal_prefere      TEXT NOT NULL CHECK (canal_prefere IN ('sms', 'whatsapp', 'email')),
    langue             TEXT NOT NULL DEFAULT 'fr',
    sensible           INTEGER NOT NULL DEFAULT 0 CHECK (sensible IN (0, 1)),
    statut_validation  TEXT NOT NULL DEFAULT 'valide' CHECK (statut_validation IN ('valide', 'en_attente')),
    notes              TEXT,
    import_id          INTEGER REFERENCES imports(id),
    cree_le            TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE factures (
    id                   INTEGER PRIMARY KEY,
    numero               TEXT NOT NULL,
    client_id            INTEGER NOT NULL REFERENCES clients(id),
    date_emission        TEXT NOT NULL,
    date_echeance        TEXT NOT NULL,
    montant_ttc          INTEGER NOT NULL CHECK (montant_ttc > 0),
    devise               TEXT NOT NULL REFERENCES devises(code),
    reference_paiement   TEXT NOT NULL UNIQUE,
    statut               TEXT NOT NULL CHECK (statut IN
                           ('a_echoir', 'echue', 'partiellement_payee', 'payee',
                            'en_litige', 'suspendue', 'cloturee')),
    en_litige            INTEGER NOT NULL DEFAULT 0 CHECK (en_litige IN (0, 1)),
    suspendue            INTEGER NOT NULL DEFAULT 0 CHECK (suspendue IN (0, 1)),
    a_verifier           INTEGER NOT NULL DEFAULT 0 CHECK (a_verifier IN (0, 1)),
    motif_verification   TEXT,
    version              INTEGER NOT NULL DEFAULT 1,  -- incrémentée à chaque changement (revalidation avant envoi)
    import_id            INTEGER REFERENCES imports(id),
    cree_le              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    maj_le               TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (client_id, numero)
);

CREATE INDEX idx_factures_statut ON factures(statut);
CREATE INDEX idx_factures_echeance ON factures(date_echeance);

CREATE TABLE avoirs (
    id          INTEGER PRIMARY KEY,
    facture_id  INTEGER NOT NULL REFERENCES factures(id),
    montant     INTEGER NOT NULL CHECK (montant > 0),
    date_avoir  TEXT NOT NULL,
    motif       TEXT NOT NULL,
    cree_par    TEXT NOT NULL,
    cree_le     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE paiements (
    id                      INTEGER PRIMARY KEY,
    id_transaction          TEXT UNIQUE,  -- identifiant opérateur : un paiement n'entre qu'une fois
    date_paiement           TEXT NOT NULL,
    montant                 INTEGER NOT NULL CHECK (montant > 0),
    devise                  TEXT NOT NULL REFERENCES devises(code),
    reference_citee         TEXT,
    telephone_payeur        TEXT,
    operateur               TEXT,
    source                  TEXT NOT NULL CHECK (source IN ('mobile_money', 'virement', 'especes', 'manuel')),
    statut_rapprochement    TEXT NOT NULL DEFAULT 'non_rapproche' CHECK (statut_rapprochement IN
                              ('non_rapproche', 'rapproche', 'a_valider', 'rejete')),
    methode_rapprochement   TEXT,
    facture_id              INTEGER REFERENCES factures(id),
    facture_proposee_id     INTEGER REFERENCES factures(id),
    import_id               INTEGER REFERENCES imports(id),
    cree_le                 TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK (statut_rapprochement <> 'rapproche' OR facture_id IS NOT NULL)
);

CREATE TABLE reponses_client (
    id            INTEGER PRIMARY KEY,
    client_id     INTEGER NOT NULL REFERENCES clients(id),
    facture_id    INTEGER REFERENCES factures(id),
    type          TEXT NOT NULL CHECK (type IN
                    ('promesse', 'paiement_annonce', 'litige', 'injoignable',
                     'demande_delai', 'demande_info', 'sans_rapport')),
    date_promise  TEXT,
    texte         TEXT,
    source        TEXT NOT NULL CHECK (source IN ('saisie', 'ia')),
    confirme      INTEGER NOT NULL DEFAULT 0 CHECK (confirme IN (0, 1)),
    saisi_par     TEXT NOT NULL,
    cree_le       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- Messages réellement « envoyés » par le connecteur bac à sable (un message peut regrouper
-- plusieurs factures d'un même client).
CREATE TABLE messages_sortants (
    id            INTEGER PRIMARY KEY,
    cle_envoi     TEXT NOT NULL UNIQUE,
    client_id     INTEGER NOT NULL REFERENCES clients(id),
    canal         TEXT NOT NULL CHECK (canal IN ('sms', 'whatsapp', 'email')),
    destinataire  TEXT NOT NULL,
    contenu       TEXT NOT NULL,
    statut        TEXT NOT NULL CHECK (statut IN ('en_attente', 'envoye', 'echec')),
    accuse        TEXT,
    cree_le       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    envoye_le     TEXT
);

CREATE TABLE relances (
    id                INTEGER PRIMARY KEY,
    facture_id        INTEGER NOT NULL REFERENCES factures(id),
    client_id         INTEGER NOT NULL REFERENCES clients(id),
    etape             TEXT NOT NULL CHECK (etape IN ('R0', 'R1', 'R2', 'R3', 'R4', 'R5')),
    canal             TEXT NOT NULL CHECK (canal IN ('sms', 'whatsapp', 'email')),
    periode           TEXT NOT NULL,
    cle_idempotence   TEXT NOT NULL UNIQUE,  -- facture + étape + canal + période : jamais deux fois
    statut            TEXT NOT NULL CHECK (statut IN
                        ('brouillon', 'a_valider', 'validee', 'en_cours_envoi',
                         'envoyee', 'echec', 'annulee')),
    motif_validation  TEXT,
    message           TEXT,
    version_facture   INTEGER NOT NULL,  -- version de la facture au moment de la préparation
    solde_prepare     INTEGER NOT NULL,
    message_id        INTEGER REFERENCES messages_sortants(id),
    cree_le           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    maj_le            TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX idx_relances_statut ON relances(statut);

CREATE TABLE validations (
    id                INTEGER PRIMARY KEY,
    relance_id        INTEGER NOT NULL REFERENCES relances(id),
    decideur_id       INTEGER NOT NULL REFERENCES utilisateurs(id),
    decision          TEXT NOT NULL CHECK (decision IN ('approuver', 'modifier', 'suspendre', 'rejeter')),
    motif             TEXT,
    contenu_approuve  TEXT,
    decide_le         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    -- Rejeter ou suspendre exige un motif.
    CHECK (decision IN ('approuver', 'modifier') OR length(trim(coalesce(motif, ''))) > 0)
);

-- Verrou simple contre deux traitements concurrents de la même file.
CREATE TABLE verrous (
    nom        TEXT PRIMARY KEY,
    detenteur  TEXT NOT NULL,
    acquis_le  TEXT NOT NULL,
    expire_le  TEXT NOT NULL
);

-- Piste d'audit : ajout seul, chaînée par empreintes.
CREATE TABLE journal (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    horodatage      TEXT NOT NULL,
    acteur          TEXT NOT NULL,
    type_acteur     TEXT NOT NULL CHECK (type_acteur IN ('humain', 'systeme', 'ia')),
    action          TEXT NOT NULL,
    objet_type      TEXT NOT NULL,
    objet_id        TEXT,
    avant           TEXT CHECK (avant IS NULL OR json_valid(avant)),
    apres           TEXT CHECK (apres IS NULL OR json_valid(apres)),
    regle           TEXT,
    hash_precedent  TEXT NOT NULL,
    hash            TEXT NOT NULL UNIQUE
);

CREATE INDEX idx_journal_objet ON journal(objet_type, objet_id);

CREATE TRIGGER journal_interdit_modification
BEFORE UPDATE ON journal
BEGIN
    SELECT RAISE(ABORT, 'journal en ajout seul : modification interdite');
END;

CREATE TRIGGER journal_interdit_suppression
BEFORE DELETE ON journal
BEGIN
    SELECT RAISE(ABORT, 'journal en ajout seul : suppression interdite');
END;
