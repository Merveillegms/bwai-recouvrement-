# Scénario de la vidéo (2 min 50)

Préparation : `python tasks.py reset`, puis `python tasks.py demo` ; navigateur en plein écran sur
http://127.0.0.1:3000 ; IA activée par le validateur dans Réglages avant l'enregistrement ; un deuxième terminal
ouvert dans le dossier du projet pour la coupure. Voix posée, phrases courtes, sous-titres.

| Temps | À l'écran | Voix |
|---|---|---|
| 0:00 à 0:20 | Page d'accueil : la file se trie, le paiement MTN MoMo annule une relance | « Un gestionnaire relance à la main, sans priorité, et relance parfois une facture déjà payée. Recouvra envoie la bonne relance au bon moment. » |
| 0:20 à 0:50 | Connexion gestionnaire, « Charger le jeu de démonstration », page Import : rapport, lignes rejetées avec motif, client inconnu | « On importe des fichiers réels, avec leurs défauts. Doublons, lignes invalides et paiements ambigus sont détectés, avec leur motif, et rien n'entre à moitié. » |
| 0:50 à 1:20 | Aujourd'hui : tuiles, tableau, clic sur la ligne 1, panneau avec l'explication et les jauges | « La file du jour est priorisée par un score transparent. Chaque rang s'explique en une phrase. Les gros montants vont d'abord à l'humain. » |
| 1:20 à 1:50 | « Préparer les relances », Validation : « Faire rédiger par l'IA », message avec badge, connexion validateur, approbation | « L'IA rédige sans jamais voir un nom ni un montant : le code insère les valeurs exactes et vérifie tout. Litiges et gros montants attendent le validateur. » |
| 1:50 à 2:20 | Terminal : `python -m pytest tests/test_coupure.py -s` (les trois coupures défilent), puis Validation : « Envoyer », derniers messages envoyés | « On tue le programme en plein envoi, à trois moments différents. Au redémarrage, rien n'est envoyé deux fois. » |
| 2:20 à 2:50 | Tableau de bord, puis Journal (badge « chaîne intacte »), puis `docs/mesure_gains.md` | « Face à une relance naïve : zéro facture payée relancée, zéro doublon, trois fois plus de montant traité dans la première heure. Et chaque décision se retrouve dans le journal. » |

Répéter deux fois avant l'enregistrement. Capture en 1080p, sans notifications système.
