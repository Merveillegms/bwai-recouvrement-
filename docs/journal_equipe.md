# Journal de bord de l'équipe

Décisions techniques et métier, dans l'ordre où elles ont été prises.

| Date | Décision | Raison |
|---|---|---|
| 2026-11-24 | Back complet avant le front ; le contrat d'API est figé en fin de phase 5 | Le moteur porte l'essentiel des points |
| 2026-11-24 | Interface distinctive mais sobre, sans landing page | Le barème ne valorise pas une interface élaborée |
| 2026-11-24 | `python tasks.py` au lieu d'un Makefile | `make` absent par défaut sous Windows |
| 2026-11-24 | Seuil gros montant : 1 000 000 FCFA (1 500 EUR) | Réglable dans `parametres` |
| 2026-11-24 | Licence MIT | Simple et permissive |
| 2026-11-24 | Montants en entiers d'unités mineures + `Decimal` | Aucun `float` pour l'argent |
| 2026-11-24 | Migrations SQL numérotées avec empreinte ; une migration appliquée n'est jamais modifiée | Reproductibilité |
| 2026-11-24 | Journal chaîné par SHA-256 + déclencheurs SQL anti-modification | Altération détectable |
| 2026-11-24 | Référence de paiement `RC` + 8 chiffres + contrôle de Damm | Lisible, détecte les fautes de frappe |
| 2026-11-24 | Date de référence du jeu de démo : 2026-12-15 ; graine 20261124 | Résultats figés |
| 2026-11-24 | Python 3.10 minimum | Version installée sur les postes de l'équipe |
| 2026-11-24 | Pays de référence : Bénin (XOF, +229, MTN MoMo / Moov Money / Celtiis Cash, jours fériés béninois) | Contexte du hackathon |
| 2026-11-24 | Messages : vouvoiement, français standard, légère touche béninoise | Choix de l'équipe |
| 2026-11-24 | Entreprise fictive « Distribution Atlantique SARL » (paramètre `entreprise`) | Signature et bloc de paiement |
| 2026-11-24 | Clé d'idempotence facture + étape + échéance (sans le canal) | Une étape ne part jamais deux fois, même sur deux canaux |
| 2026-11-24 | Validation humaine décidée par lot (un message par client et par jour) | Jamais de message en deux morceaux |
| 2026-11-24 | Fiche PDF avec fpdf2 (LGPL-3.0, utilisée comme bibliothèque) | Simple, sans dépendance système |
