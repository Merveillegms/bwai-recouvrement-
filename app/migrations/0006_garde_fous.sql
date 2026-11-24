-- Garde-fous : sessions, anti double-clic (clés d'idempotence des requêtes), annulations motivées.

CREATE TABLE sessions (
    jeton_hash      TEXT PRIMARY KEY,               -- SHA-256 du jeton : le jeton lui-même n'est jamais stocké
    utilisateur_id  INTEGER NOT NULL REFERENCES utilisateurs(id),
    cree_le         TEXT NOT NULL,
    expire_le       TEXT NOT NULL
);

-- Réponse mémorisée par clé d'idempotence de requête : un double clic rejoue la même réponse.
CREATE TABLE requetes_idempotentes (
    cle             TEXT NOT NULL,
    utilisateur     TEXT NOT NULL,
    methode         TEXT NOT NULL,
    chemin          TEXT NOT NULL,
    statut_http     INTEGER NOT NULL,
    reponse         BLOB NOT NULL,
    type_contenu    TEXT,
    cree_le         TEXT NOT NULL,
    PRIMARY KEY (cle, utilisateur)
);

ALTER TABLE relances ADD COLUMN motif_annulation TEXT;
