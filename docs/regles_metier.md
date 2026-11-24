# Règles métier

Ce document fixe par écrit les règles du système. Le code les applique, le générateur de données
([app/generateur.py](../app/generateur.py)) les encode dans `data/demo/attendus.json`, et les tests
vérifient que les deux concordent. Toute modification de règle passe par ce document.

Les points marqués **[à valider]** doivent être confirmés avec un gestionnaire ou un mentor.

## 1. Montants

- Stockés en **entiers, en unités mineures** de la devise : XOF et XAF sans décimale, EUR en centimes.
- Lus et calculés en `Decimal`, jamais en `float`.
- Devises autorisées : `XOF`, `XAF`, `EUR` (table `devises`).
- Un montant XOF/XAF avec une partie décimale non nulle (`150000,50`) est rejeté (`DECIMALES_INVALIDES`).
  `150000.00` est accepté.
- Séparateurs tolérés à l'import : espace des milliers (`1 250 000`), virgule ou point décimal.
- Arrondi : une seule fonction, demi-supérieur (`ROUND_HALF_UP`) à l'unité mineure de la devise.

## 2. Retard et ancienneté

- **Jours de retard** = date de référence − date d'échéance, en **jours calendaires**.
  La date de référence est injectable (paramètre `date_du_jour_simulee`) pour les tests et la démo.
- Une facture dont l'échéance est **aujourd'hui** n'est pas en retard (retard 0).
- Une facture soldée a un retard de 0 et pas de tranche.
- **Tranches** : `non_echue` (≤ 0), `1-15`, `16-30`, `31-60`, `61-90`, `plus_90`.
- Option (désactivée par défaut) : jours ouvrés et jours fériés du **Bénin**.
  Fixes : 1er janvier, 9-10 janvier (fêtes des religions endogènes), 1er mai, 1er août (indépendance),
  15 août, 26 octobre (forces armées), 1er novembre, 25 décembre. Mobiles : lundi de Pâques, Ascension,
  lundi de Pentecôte, Ramadan, Tabaski, Maouloud (dates publiées chaque année, à saisir en paramètre).
  **[à valider]**

## 2 bis. Contexte

- Pays : **Bénin** — devise XOF, téléphones `+229 01XXXXXXXX` (10 chiffres depuis novembre 2024).
- Opérateurs mobile money : MTN MoMo, Moov Money, Celtiis Cash.

## 3. Solde

```
total payé = somme des paiements rapprochés (statut « rapproche »)
solde      = max(montant TTC − total payé − avoirs, 0)
trop-perçu = max(total payé + avoirs − montant TTC, 0)
```

Un paiement « à valider » ou « rejeté » ne compte **jamais** dans le solde.

## 4. Statuts

Le statut est déterminé dans cet ordre (la première règle vraie l'emporte) :

| Ordre | Statut | Condition | Relance automatique |
|---|---|---|---|
| 1 | `cloturee` | avoir total ou passage en perte validé | Non |
| 2 | `en_litige` | litige déclaré | Non, humain obligatoire |
| 3 | `suspendue` | suspendue par un humain | Non |
| 4 | `payee` | solde = 0 | **Jamais** |
| 5 | `partiellement_payee` | 0 < total payé < montant | Oui, sur le solde, si retard ≥ 1 |
| 6 | `echue` | retard ≥ 1 | Oui |
| 7 | `a_echoir` | sinon | Non (rappel préventif R0 en option) |

## 5. Drapeaux (indépendants du statut)

| Drapeau | Condition | Effet |
|---|---|---|
| `gros_montant` | solde ≥ seuil de la devise (XOF/XAF : 1 000 000 ; EUR : 1 500) | Validation humaine obligatoire |
| `client_sensible` | client marqué sensible | Validation humaine à chaque étape |
| `sans_contact` | client sans téléphone ni e-mail (ou client inconnu) | Pas d'envoi : traité par un humain |
| `a_verifier` | anomalie d'import non bloquante (voir § 6) | Aucune relance tant qu'un humain n'a pas levé le doute |

## 6. Contrôles à l'import

Un import est **transactionnel** : une erreur technique annule tout. Les lignes invalides sont rejetées
une par une avec leur motif ; les lignes valides entrent. Un fichier déjà importé (même empreinte SHA-256)
est refusé en entier.

### Rejets (la ligne n'entre pas)

| Code | Règle |
|---|---|
| `CHAMP_MANQUANT` | numéro, client, émission, échéance, montant ou devise vide |
| `DATE_INVALIDE` | date inexistante ou illisible (formats acceptés : `AAAA-MM-JJ`, `JJ/MM/AAAA`) |
| `MONTANT_INVALIDE` | montant non numérique |
| `MONTANT_NEGATIF` | montant < 0 |
| `MONTANT_NUL` | montant = 0 |
| `DECIMALES_INVALIDES` | décimales non nulles sur une devise sans décimale |
| `DEVISE_INCONNUE` | devise hors liste |
| `DOUBLON_EXACT` | même client + même numéro + mêmes valeurs qu'une ligne précédente du même fichier |
| `CONFLIT_NUMERO` | même client + même numéro mais valeurs différentes (fichier ou base) : résolution humaine |
| `DOUBLON_IMPORT` | facture déjà présente en base à l'identique (ré-import via un autre fichier) |

### Avertissements (la ligne entre, marquée `a_verifier`)

| Code | Règle |
|---|---|
| `CLIENT_INCONNU` | code client absent : client créé « en attente de validation » |
| `ECHEANCE_AVANT_EMISSION` | échéance antérieure à l'émission |
| `QUASI_DOUBLON` | même client, même montant, émissions à ≤ 7 jours, numéro différent (la 2ᵉ occurrence est marquée) |
| `MONTANT_ABERRANT` | montant > 10 × médiane des **autres** factures du client **dans la même devise**, si au moins 3 autres factures |

Seuls les montants anormalement **hauts** sont signalés : un petit montant n'est pas un risque de relance
abusive. **[à valider]**

Autre rejet : `VALEUR_INVALIDE` (colonne litige ou sensible ni « oui » ni « non »).

### Clients

| Code | Règle |
|---|---|
| `CHAMP_MANQUANT` | code ou nom vide → rejet |
| `DOUBLON_EXACT` | ligne identique déjà lue dans le fichier → rejet |
| `DOUBLON_IMPORT` | client déjà en base, identique → rejet (sans conséquence) |
| `CONFLIT_CODE` | même code, informations différentes (fichier ou base) → rejet, à corriger à la main |
| `CANAL_INVALIDE` | canal hors `sms`, `whatsapp`, `email` → rejet |

- Canal vide : WhatsApp si un téléphone est connu, sinon e-mail si une adresse est connue, sinon SMS.
- Un client créé « en attente » par un import de factures est **complété** (et validé) par un fichier clients.

### Fichier refusé en entier

| Code | Cause |
|---|---|
| `FICHIER_DEJA_IMPORTE` | même empreinte SHA-256 qu'un import précédent, même sous un autre nom |
| `FICHIER_ILLISIBLE` | vide, corrompu, aucun séparateur reconnu |
| `COLONNES_MANQUANTES` | une colonne obligatoire n'est pas reconnue : correspondance manuelle à fournir |
| `FICHIER_VIDE` | en-tête sans aucune ligne |

### Compteurs du rapport

`lignes_lues` = `lignes_acceptees` (sans anomalie) + `lignes_avertissement` (entrées, à vérifier) + `lignes_rejetees`.

### Résolution humaine (motif obligatoire sauf mention contraire)

| Situation | Décisions possibles |
|---|---|
| `CONFLIT_NUMERO` | **ignorer** la ligne (la base fait foi) ou **remplacer** la facture en base — refusé si un paiement y est rapproché ou une relance envoyée |
| `DOUBLON_EXACT`, `DOUBLON_IMPORT`, autres rejets | **ignorer** (prise de connaissance, motif facultatif) |
| Facture à vérifier | **confirmer** (motif facultatif) ou **annuler** : statut `cloturee`, conservée pour l'audit |
| Client en attente | **valider** la fiche (nom obligatoire) : ses factures dont c'était le seul doute sont libérées |

## 7. Référence de paiement

- Format `RC` + 8 chiffres + 1 chiffre de contrôle (algorithme de Damm), affichée `RC-1234-5678-9`.
- Dérivée de façon stable de (code client, numéro de facture).
- Saisie tolérante : minuscules, espaces, tirets et points ignorés.
- Le chiffre de contrôle détecte toute erreur sur un chiffre et toute inversion de deux chiffres voisins.

## 8. Rapprochement des paiements

Dans l'ordre :

1. `id_transaction` déjà connu → rejet `DOUBLON_PAIEMENT` (dès l'import).
2. Référence valide et connue, facture ouverte, même devise → **rapprochement automatique** (seul cas automatique).
3. Référence valide mais inconnue → à valider (`REFERENCE_INCONNUE`).
4. Référence présente mais chiffre de contrôle faux → à valider (`REFERENCE_INVALIDE`), avec proposition si
   le montant et le téléphone désignent une seule facture.
5. Référence connue mais facture déjà soldée (`FACTURE_DEJA_SOLDEE`, doublon possible), clôturée
   (`FACTURE_CLOTUREE`) ou dans une autre devise (`DEVISE_DIFFERENTE`) → à valider.
6. Pas de référence : téléphone du payeur → client (comparaison sur les 8 derniers chiffres, ce qui couvre
   l'ancien et le nouveau format béninois), puis montant = solde d'**une seule** facture ouverte
   → proposition à valider (`PROPOSITION_MONTANT_CLIENT`).
7. Plusieurs factures possibles → à valider (`RAPPROCHEMENT_AMBIGU`) ; aucune → `NON_IDENTIFIE`.

Les paiements avec référence sont traités en premier, pour que les propositions par montant portent sur
des soldes à jour. Relancer le rapprochement ne retraite rien (idempotent).

Décisions humaines : **valider** (confirmer la proposition, ou choisir une autre facture avec un motif),
**rejeter** (paiement étranger, motif obligatoire), **annuler un rapprochement** (validateur, motif obligatoire :
le paiement repart à valider, la facture retrouve son solde).

## 8 bis. Transitions de statut

Le statut enregistré n'est modifié que par une seule fonction (`statuts.actualiser`), qui vérifie la
transition, incrémente la version de la facture et journalise l'ancien et le nouveau statut avec la règle.

- `cloturee` est un état final.
- **Réservé à un humain** : entrer en litige, suspension ou clôture ; en sortir ; faire revenir une facture
  payée vers un état dû (annulation de rapprochement).
- **Automatique** : passage à échéance (`a_echoir` → `echue`), paiements rapprochés par référence.
- Un avoir réduit le solde ; des avoirs couvrant **tout** le montant clôturent la facture (annulation).
- Litige levé, reprise, avoir et passage en perte sont réservés au rôle validateur (sauf déclarer un litige
  ou suspendre, ouverts au gestionnaire).

## 9. Séquence de relances (paramètre `sequence_relances`)

| Étape | Jours / échéance | Ton | Validation humaine |
|---|---|---|---|
| R0 (option) | −3 | informatif | Non |
| R1 | +1 | très courtois | Non (sauf client sensible) |
| R2 | +10 | courtois et précis | Non |
| R3 | +30 | ferme et poli | Oui |
| R4 | +45 | formel, échéancier | Oui |
| R5 | +90 | escalade hors outil | Oui |

- Délai minimal entre deux relances d'une même facture : 7 jours (date **métier** d'envoi).
- Une relance au plus par client et par jour : les factures d'un même client sont regroupées dans un
  **lot d'envoi** (un seul message, même s'il mêle plusieurs devises : un total par devise, jamais d'addition
  entre devises).
- **Idempotence** : clé `facture | étape | échéance`, contrainte UNIQUE en base. Le canal n'en fait pas partie,
  pour qu'une même étape ne parte jamais deux fois, même sur deux canaux.
- Une facture dont une relance attend validation ou envoi est écartée de la file (`RELANCE_EN_ATTENTE`).
- Ton du lot = étape la plus avancée. Si les factures du lot sont à des étapes différentes, le corps du message
  reste neutre et exact (pas de « malgré nos rappels » pour une facture jamais relancée).
- Validation humaine **par lot** : si une seule facture du lot l'exige, tout le lot attend (un message n'est
  jamais envoyé en deux morceaux le même jour).
- Canal : le canal préféré s'il est joignable, sinon le premier joignable (WhatsApp, SMS, e-mail) ; aucun
  contact → pas de message, facture signalée « à traiter par un humain ».
- R5 ne produit aucun message client : un dossier d'escalade est remis au responsable du recouvrement.
- Envoi refusé hors de la plage horaire (08:00 – 19:00, réglable) et pendant un arrêt d'urgence.

### Messages

Français standard, vouvoiement, légère touche béninoise (« nous espérons que vous allez bien et que les affaires
se portent bien », « bonne journée à vous »), plus formel à mesure que les étapes avancent. Montants, dates,
références et numéros sont insérés par le code. Mots interdits (menace, intimidation, mention de tiers)
et tutoiement sont détectés : un écart envoie le lot en validation humaine. Longueur maximale : SMS 640,
WhatsApp 1 500, e-mail 5 000 caractères.

### Réponses des clients (saisie humaine)

| Réponse | Effet |
|---|---|
| Promesse / demande de délai | date obligatoire (≤ 90 j) ; relances suspendues jusqu'à cette date, puis reprises |
| Paiement annoncé | relances suspendues 3 jours (réglable) |
| Litige | la facture passe en litige (facture obligatoire) |
| Injoignable, demande d'information, sans rapport | tracé au journal, sans effet |

## 10. Priorisation

Une hiérarchie de règles documentée, **pas une prédiction** de non-paiement.

### Score (0 à 100)

```
A = min(jours de retard / 120, 1)                                    ancienneté
S = min(solde / seuil gros montant de la devise, 1)                   solde
H = factures du client réglées en retard / factures du client réglées historique (0 sans historique)
score = 100 × (0,5 × A + 0,3 × S + 0,2 × H)        arrondi au centième, demi-supérieur
```

Poids et plafond dans les paramètres (`poids_priorite`, `plafond_anciennete_jours`) ; seuls des poids
positifs de somme 1 sont acceptés ; leur modification est réservée au validateur et journalisée.
L'historique ne contient que des faits chiffrés (jamais d'étiquette « mauvais payeur ») : factures réglées,
réglées en retard, retard moyen de règlement, factures échues ouvertes, dernière relance, promesse en cours.

### Ordre de la file « Aujourd'hui »

1. Gros montants d'abord (ils partent en validation humaine) ;
2. score décroissant ;
3. retard décroissant ;
4. solde décroissant ;
5. numéro de facture croissant (départage stable : même entrée, même ordre).

### Exclusions (chacune avec son motif, consultable)

| Code | Cause |
|---|---|
| `PAYEE`, `CLOTUREE` | rien à recouvrer |
| `EN_LITIGE`, `SUSPENDUE` | traitement humain uniquement |
| `NON_ECHUE` | échéance non dépassée |
| `A_VERIFIER` | anomalie d'import en attente de décision |
| `PROMESSE_EN_COURS` | promesse de paiement confirmée non échue |
| `RELANCE_RECENTE` | cette facture a été relancée il y a moins de 7 jours |
| `ETAPE_DEJA_FAITE` | l'étape atteinte a déjà été envoyée : attendre la suivante |

### Étape proposée

L'étape la plus avancée atteinte par le retard (R1 dès 1 j, R2 dès 10 j, R3 dès 30 j, R4 dès 45 j, R5 dès 90 j).
Les étapes intermédiaires manquées ne sont pas rattrapées (pas de R1 puis R2 la même semaine).

### Validation humaine signalée

Gros montant, client sensible, client sans contact, étape R3 à R5.

### Explication

Phrase par gabarit, sans IA : « Priorité 3 : 45 jours de retard, solde de 320 000 FCFA, 2 retards sur
3 factures réglées », et détail du calcul facteur par facteur.

## 11. Garde-fous

### Revalidation (juste avant l'envoi, et à l'approbation)

Pour chaque facture du lot, l'état réel est relu et comparé à celui de la préparation. Le lot est **annulé**
(raison journalisée, aucun message) si :

- la version de la facture a changé (paiement, avoir, litige, suspension, correction…) ou son solde ;
- son statut n'est plus « échue » ou « partiellement payée » ;
- une donnée est à vérifier, ou un paiement reçu attend d'être rapproché de cette facture ;
- le client a fait une promesse de paiement en cours ;
- le message ne correspond plus exactement aux données calculées : chaque numéro, solde et référence doit
  y figurer, aucun autre montant ni référence n'est toléré ; ton et longueur conformes.

Une annulation automatique libère la clé d'idempotence : la facture, toujours due, pourra être relancée à la
même étape avec ses nouvelles valeurs. Les factures visées par un paiement en attente de rapprochement ne sont
d'ailleurs même pas proposées (`PAIEMENT_EN_ATTENTE`).

### Validation humaine (rôle validateur)

| Décision | Effet |
|---|---|
| Approuver | revalidation, puis lot « validé » ; refusé si le message doit être corrigé |
| Modifier | le nouveau texte repasse par la vérification automatique ; refusé s'il contient une valeur fausse |
| Suspendre (motif) | lot annulé, factures suspendues |
| Rejeter (motif) | lot annulé ; l'étape n'est plus proposée pour ces factures (`ETAPE_REJETEE`) |
| Validation groupée | approuve d'un coup les lots dont le **seul** motif est l'étape R3 ; chaque lot est revalidé et journalisé |

Chaque décision enregistre le décideur, l'heure et le contenu exact approuvé (table `validations`, empreinte
du contenu au journal).

### Envoi, idempotence et reprise

1. Verrou `envoi` : un seul envoi à la fois ; un verrou laissé par un processus mort est repris immédiatement.
2. Reprise : chaque lot resté « en cours d'envoi » est vérifié auprès du connecteur (accusé par clé d'envoi) :
   envoyé → confirmé ; non envoyé → remis en file et revalidé. **Jamais de second envoi.**
3. Pour chaque lot validé : revalidation, passage « en cours d'envoi » et enregistrement du message sortant
   (une transaction), appel du connecteur, puis « envoyé » + accusé (une transaction).
4. Panne du fournisseur : lot « en échec », relançable à la main (« nouvel essai »), revalidé avant l'envoi.

Testé par une coupure brutale d'un vrai processus à plusieurs instants (avant un envoi, et après un envoi mais
avant son enregistrement).

### Accès

- Connexion par identifiant et mot de passe (PBKDF2), jeton de session de 8 h (seule son empreinte est stockée).
- Gestionnaire : importe, prépare, envoie, saisit les réponses. Validateur : décide (validation, litige levé,
  avoir, perte, poids, arrêt d'urgence). Auditeur : lecture seule, téléphones masqués.
- Anti double-clic : en-tête `Idempotency-Key` ; la même clé rejoue la même réponse sans refaire l'action.
- Arrêt d'urgence : un clic (validateur, motif obligatoire) bloque toute préparation et tout envoi.
- Le journal ne contient aucun numéro de téléphone.
- Limite connue : la base SQLite n'est pas chiffrée (protéger le poste : chiffrement du disque, session Windows).
