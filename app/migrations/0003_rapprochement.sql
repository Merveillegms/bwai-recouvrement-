-- Rapprochement des paiements et calendrier des jours ouvrés (Bénin).

ALTER TABLE paiements ADD COLUMN motif_rapprochement TEXT;   -- code expliquant l'état (REFERENCE_INCONNUE, …)
ALTER TABLE paiements ADD COLUMN rapproche_par TEXT;
ALTER TABLE paiements ADD COLUMN rapproche_le TEXT;

CREATE INDEX idx_paiements_statut ON paiements(statut_rapprochement);
CREATE INDEX idx_paiements_facture ON paiements(facture_id);
CREATE INDEX idx_avoirs_facture ON avoirs(facture_id);

INSERT INTO parametres (cle, valeur, description) VALUES
    ('retard_jours_ouvres', 'false', 'Compter le retard en jours ouvrés (sinon jours calendaires)'),
    ('jours_feries_fixes', '["01-01", "01-10", "05-01", "08-01", "08-15", "11-01", "12-25"]',
        'Fériés fixes du Bénin (MM-JJ) — à valider'),
    ('jours_feries_mobiles', '["lundi_paques", "ascension", "lundi_pentecote"]',
        'Fériés liés à Pâques, calculés chaque année'),
    ('jours_feries_supplementaires', '[]',
        'Dates ISO publiées chaque année (Ramadan, Tabaski, Maouloud, ponts)');
