-- Libellés de paramètres sans tiret cadratin (charte de l'interface).

UPDATE parametres SET description = 'Identité de l''entreprise qui relance (signature et bloc de paiement), données fictives'
    WHERE cle = 'entreprise';
UPDATE parametres SET description = 'Fériés fixes du Bénin (MM-JJ), à valider' WHERE cle = 'jours_feries_fixes';
