# Mesure des gains

Jeu : factures_lot1.csv (128 lignes piégées) + paiements mobile money, au 2026-12-15. Généré par `python -m app.mesure_gains`.

Référence : relance naïve (chaque ligne échue du fichier, dans l'ordre du fichier, un message par facture). Le gestionnaire connaît les paiements de plus de 7 jours (suivi mis à jour chaque semaine), pas les plus récents.

## Erreurs (mesurées sur les données)

| Erreur | Référence naïve | Recouvra |
|---|---|---|
| Factures déjà payées relancées | 1 | 0 |
| Clients relancés alors qu'un paiement est arrivé (sans bonne référence) | 2 | 0 |
| Doublons relancés deux fois | 2 | 0 |
| Montants réclamés faux (paiement récent ignoré) | 0 | 0 |
| Factures en litige relancées | 3 | 0 |
| Lignes invalides relancées | 11 | 0 |
| Données douteuses relancées sans vérification | 4 | 0 |
| Relances tentées sans aucun contact | 3 | 0 |
| Messages en trop au même client le même jour | 73 | 0 |
| Anomalies du fichier signalées | 0 sur 19 | 19 |

## Volume et priorité

| Indicateur | Référence naïve | Recouvra |
|---|---|---|
| Relances | 90 | 65 |
| Messages envoyés | 90 | 24 |
| Solde dû traité dans la première heure (20 factures) | 8 704 500 FCFA | 31 563 000 FCFA |

## Temps (hypothèses à remplacer par un chronométrage)

| Poste | Minutes |
|---|---|
| Traitement manuel (90 relances × 3.0 min) | 270.0 |
| Avec Recouvra (lancement + 22 messages à valider × 0.5 min + calcul) | 13.0 |
| Gain | 95.2 % |

Temps machine mesurés : import 0.043 s, rapprochement 0.02 s, priorisation 0.009 s, preparation 0.022 s.
