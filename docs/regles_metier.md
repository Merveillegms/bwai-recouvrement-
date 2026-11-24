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

1. `id_transaction` déjà connu → rejet `DOUBLON_PAIEMENT`.
2. Référence valide et connue → **rapprochement automatique**.
3. Référence valide mais inconnue → à valider (`REFERENCE_INCONNUE`).
4. Référence présente mais chiffre de contrôle faux → à valider (`REFERENCE_INVALIDE`).
5. Pas de référence : téléphone du payeur → client, puis montant = solde d'**une seule** facture ouverte
   → proposition à valider (`PROPOSITION_MONTANT_CLIENT`).
6. Plusieurs factures possibles → à valider (`RAPPROCHEMENT_AMBIGU`).

Aucun rapprochement ambigu n'est appliqué automatiquement.

## 9. Séquence de relances (paramètre `sequence_relances`)

| Étape | Jours / échéance | Ton | Validation humaine |
|---|---|---|---|
| R0 (option) | −3 | informatif | Non |
| R1 | +1 | très courtois | Non (sauf client sensible) |
| R2 | +10 | courtois et précis | Non |
| R3 | +30 | ferme et poli | Oui |
| R4 | +45 | formel, échéancier | Oui |
| R5 | +90 | escalade hors outil | Oui |

- Délai minimal entre deux relances d'une même facture : 7 jours.
- Une relance au plus par client et par jour : les factures d'un même client sont regroupées.

## 10. Priorisation

Hiérarchie (détail en phase 3) : litiges exclus → gros montants vers l'humain → score décroissant →
numéro de facture (départage stable). Score = somme pondérée de l'ancienneté, du solde et de
l'historique de retard (poids : 0,5 / 0,3 / 0,2). Aucune prédiction de non-paiement.
