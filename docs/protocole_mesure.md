# Protocole de mesure réelle des gains

Les erreurs du comparatif (`docs/mesure_gains.md`) sont mesurées sur les données. Les **temps humains**, eux,
reposent sur des hypothèses (3 minutes par relance manuelle, 30 secondes par message à valider, 2 minutes de
lancement). Ce protocole permet de les remplacer par un chronométrage.

## Préparation

1. `python tasks.py reset` puis `python tasks.py demo`.
2. Imprimer ou ouvrir dans Excel `data/demo/factures_lot1.csv` et `data/demo/paiements_mobile_money.csv` :
   c'est tout ce dont dispose le gestionnaire « manuel ».
3. Deux personnes : un **testeur** qui traite, un **observateur** qui chronomètre et note les erreurs.

## Passage 1 : traitement manuel (sans l'outil)

Consigne au testeur : « Nous sommes le 15/12/2026. Préparez les messages de relance à envoyer aujourd'hui pour
les 50 premières lignes du fichier, comme vous le feriez d'habitude (tableur, bloc-notes, téléphone). »

L'observateur note :

| Mesure | Comment |
|---|---|
| Temps total | du début de la lecture au dernier message rédigé |
| Factures déjà payées relancées | comparer avec la colonne « statut » de `attendus.json` |
| Doublons relancés | même facture relancée deux fois |
| Montants faux | montant réclamé différent du solde de `attendus.json` |
| Litiges relancés | factures marquées « oui » dans la colonne litige |
| Lignes invalides non signalées | lignes rejetées dans `attendus.json` et traitées sans remarque |
| Relances oubliées | factures échues non relancées |

## Passage 2 : avec Recouvra (autre testeur, ou même testeur une semaine plus tard)

1. Connexion « gestionnaire », chargement du jeu de démonstration (ou import des mêmes fichiers).
2. « Préparer les relances du jour », puis connexion « validateur » et traitement de la file de validation.
3. « Envoyer les messages validés ».

L'observateur note le temps total et vérifie les mêmes erreurs dans `data/sortants/`.

## Restitution

Reporter les deux temps et les erreurs dans le tableau de `docs/mesure_gains.md` (section « Temps »), en
remplaçant les hypothèses, et indiquer le nombre de testeurs. Conserver les feuilles de l'observateur.
