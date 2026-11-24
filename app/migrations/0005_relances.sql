-- Relances : regroupement par client (lot d'envoi), identité de l'entreprise, contrôle horaire.

ALTER TABLE relances ADD COLUMN lot_envoi TEXT;          -- un lot = un message à un client, un jour donné
ALTER TABLE relances ADD COLUMN date_preparation TEXT;   -- date métier de préparation
ALTER TABLE relances ADD COLUMN date_envoi TEXT;         -- date métier d'envoi (délai entre relances, historique)
CREATE INDEX idx_relances_lot ON relances(lot_envoi);

INSERT INTO parametres (cle, valeur, description) VALUES
    ('entreprise', '{
        "nom": "Distribution Atlantique SARL",
        "ville": "Cotonou",
        "telephone": "+229 01 97 00 00 00",
        "email": "recouvrement@distribution-atlantique.example",
        "mobile_money": [
            {"operateur": "MTN MoMo", "numero": "01 97 00 00 00"},
            {"operateur": "Moov Money", "numero": "01 95 00 00 00"}
        ]
    }', 'Identité de l''entreprise qui relance (signature et bloc de paiement) — données fictives'),
    ('controle_heures_envoi', 'true', 'Refuser les envois hors de la plage horaire raisonnable'),
    ('delai_paiement_annonce_jours', '3',
        'Un paiement annoncé par le client suspend les relances pendant ce nombre de jours');
