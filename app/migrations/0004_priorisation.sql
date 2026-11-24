-- Priorisation : plafond de normalisation de l'ancienneté.

INSERT INTO parametres (cle, valeur, description) VALUES
    ('plafond_anciennete_jours', '120',
        'Retard (jours) à partir duquel le facteur ancienneté vaut 1 dans le score de priorité');

CREATE INDEX idx_relances_facture ON relances(facture_id, etape);
CREATE INDEX idx_reponses_client ON reponses_client(client_id, type);
