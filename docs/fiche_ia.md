# Fiche IA : Recouvra

L'IA intervient à deux endroits, toujours sous contrôle. Elle **ne calcule rien** (soldes, retards, scores et
dates d'échéance sont calculés par du code déterministe) et **ne décide de rien de sensible** (aucune
proposition ne change seule le statut d'une facture). Un interrupteur global la désactive : l'outil fonctionne
alors à l'identique avec les gabarits fixes et la saisie manuelle des réponses.

Mesures reproductibles : `python -m app.ia.evaluation --redaction 6` (résultats dans `docs/ia_evaluation.json`).

## 1. Rédaction des messages de relance

| Élément | Choix |
|---|---|
| Modèle | Google Gemini `gemini-3.5-flash` (Google AI Studio), réflexion réglée sur « faible » |
| Alternative branchée | Hugging Face, modèle Meta `Llama-3.1-8B-Instruct` (même interface, choix dans `.env`) |
| Hébergement | API distante ; clé dans `.env`, jamais versionnée, jamais journalisée |
| Repli | Gabarit fixe testé, utilisé si l'IA est désactivée, indisponible ou rejetée |

### Données envoyées au modèle

Uniquement : l'étape de relance (R0 à R4), le ton attendu, le canal, « une seule » ou « plusieurs » factures,
si les factures sont à des étapes différentes, la longueur maximale et la liste des marqueurs à utiliser.

**Jamais envoyés** : nom du client, montant, date, numéro de facture, référence de paiement, téléphone. Un test
vérifie qu'aucune de ces données ne figure dans ce qui part vers le modèle (`tests/test_ia.py`).

### Contrôles avant d'accepter un texte

Le modèle écrit avec des marqueurs (`[[CLIENT]]`, `[[FACTURES]]`, `[[TOTAL]]`, `[[PAIEMENT]]`, `[[SIGNATURE]]`) que
le code remplace par les valeurs calculées. Le texte est rejeté, et le gabarit conservé, si :

1. un marqueur manque, est en double ou est inventé ;
2. le modèle a écrit **un seul chiffre** (il ne doit inventer ni montant, ni date, ni numéro) ;
3. un mot interdit (menace, intimidation, mention de tiers) ou un tutoiement apparaît ;
4. le message dépasse la longueur du canal (SMS 640, WhatsApp 1 500, e-mail 5 000 caractères) ;
5. après insertion des valeurs, le vérificateur des garde-fous trouve le moindre écart : chaque numéro, solde
   et référence doit être présent et exact, aucun autre montant ni référence n'est toléré ;
6. le lot a changé pendant l'appel au modèle.

Un message accepté part **toujours en validation humaine** (paramètre `ia_validation_obligatoire`), le
validateur peut le modifier (le texte est revérifié) ou revenir au gabarit en un clic. Il est revérifié une
dernière fois juste avant l'envoi.

### Évaluation (jeu de démonstration, 15/12/2026)

| Mesure | Résultat |
|---|---|
| Lots rédigés | 6 |
| Acceptés par tous les contrôles | 6 (100 %) |
| Rejetés ou en erreur | 0 |
| Durée moyenne d'un appel | 11,6 s (environ 20 s sans le réglage de réflexion) |

Erreurs rencontrées pendant la mise au point, et traitement :

- `gemini-2.5-flash` refusé aux nouveaux comptes (erreur 404) : passage à `gemini-3.5-flash`, modèle configurable ;
- surcharge passagère du service (erreur 503) : une seconde tentative automatique, puis repli sur le gabarit ;
- dans tous les cas d'erreur, aucune relance n'est bloquée : le gabarit fixe prend le relais.

## 2. Classification des réponses des clients

| Élément | Choix |
|---|---|
| Modèle | Bayésien naïf multinomial (`nb-multinomial-1`), écrit dans le projet, sans dépendance |
| Hébergement | Local, hors ligne ; entraîné au démarrage en moins d'une seconde |
| Données d'entraînement | 150 messages fictifs étiquetés à la main (`data/ia/entrainement.csv`), français du Bénin, avec abréviations et fautes courantes |
| Catégories | promesse, paiement annoncé, litige, demande de délai, demande d'information, sans rapport |
| Extraction de date | Règles (« vendredi », « demain », « le 20 », « fin du mois », « 05/01 »…) relatives à la date du jour |

Le texte du client n'est jamais traité comme une instruction : pour ce modèle, ce n'est qu'un ensemble de mots.
Il n'est envoyé à aucun service extérieur.

### Évaluation sur 48 messages jamais vus à l'entraînement (`data/ia/evaluation.csv`)

| Catégorie | Précision | Rappel |
|---|---|---|
| Promesse | 67 % | 100 % |
| Paiement annoncé | 100 % | 100 % |
| **Litige** | 80 % | **100 %** |
| Demande de délai | 88 % | 88 % |
| Demande d'information | 100 % | 88 % |
| Sans rapport | 100 % | 38 % |
| **Exactitude globale** | **85 %** | |

### Erreurs observées (7 sur 48)

| Message | Attendu | Proposé | Confiance |
|---|---|---|---|
| Laissez moi jusqu'à la fin du mois prochain | demande de délai | promesse | 0,97 |
| ok d'accord | sans rapport | promesse | 0,90 |
| Rappelez-moi svp | demande d'information | demande de délai | 0,74 |
| Arrêtez les messages | sans rapport | litige | 0,55 |
| Je veux passer une nouvelle commande | sans rapport | litige | 0,51 |
| Bonsoir | sans rapport | promesse | 0,37 |
| Vous vendez du ciment ? | sans rapport | promesse | 0,34 |

Limite principale : les messages très courts ou hors sujet sont mal reconnus (rappel de 38 % sur « sans
rapport »). Ces erreurs sont sans danger ici, car l'humain voit toujours la proposition avant tout effet. Nous
n'avons pas ajusté le modèle sur ces exemples : le jeu d'évaluation resterait alors sans valeur.

### Seuils de revue humaine et justification

| Seuil | Couverture | Exactitude au-dessus du seuil |
|---|---|---|
| 0,5 | 92 % | 89 % |
| **0,6 (retenu)** | **85 %** | **93 %** |
| 0,8 | 77 % | 95 % |

- **Toute** proposition attend la confirmation d'un humain ; le seuil de 0,6 signale en plus « confiance faible »
  les 15 % de réponses les plus incertaines, où se concentrent 4 des 7 erreurs.
- **Litige possible** dès 25 % de probabilité : priorité au rappel. Les 8 litiges du jeu d'évaluation sont
  signalés (rappel 100 %), au prix de 2 fausses alertes. Un litige manqué ferait relancer un client qui
  conteste ; une fausse alerte coûte quelques secondes de lecture.
- Une réponse classée « litige » ne déclare le litige qu'après confirmation humaine **et** désignation de la
  facture concernée.

## 3. Traçabilité et sécurité

- Table `ia_appels` : chaque appel avec le fournisseur, le modèle, ce qui a été envoyé, la sortie brute, la
  décision des contrôles, les raisons de rejet et la durée.
- Journal d'audit : action `redaction_ia` (acteur de type « ia » avec le nom du modèle), puis la décision humaine.
- Interrupteur global `ia_active` (réservé au validateur, journalisé), désactivé par défaut.
- Aucun secret dans le dépôt : `.env` est exclu par `.gitignore`, `.env.exemple` documente les variables.

## 4. Coûts

- Classification : nulle (locale).
- Rédaction : quota gratuit de Google AI Studio pour le prototype ; à l'usage, environ un appel par message
  client et par jour (les factures d'un même client sont regroupées), soit quelques dizaines d'appels par jour
  pour une PME.
