# Roadmap — Hackathon BWAI · Projet 1 : Recouvrement des factures impayées

> **Pitch** : un assistant de recouvrement qui envoie la bonne relance au bon moment, ne relance jamais une facture déjà payée, ne fait jamais deux fois la même action, et explique chacune de ses décisions.

## Règles non négociables

- **Calculs déterministes** : soldes, retards et arrondis sont faits par du code, jamais par l'IA. Montants en `Decimal` ou en entiers FCFA, jamais en `float`.
- **Humain dans la boucle** : litiges, gros montants et cas incertains sont validés par une personne.
- **Idempotence** : clé unique en base (contrainte `UNIQUE`) ; aucune action n'est exécutée deux fois.
- **Traçabilité** : journal en ajout seul, chaîné par empreintes.
- **Local** : données réinitialisables, reprise après interruption, fonctionne sans réseau et sans IA.

## Barème (sur 100)

| Critère | Points | Ce qui le porte |
|---|---|---|
| Faisabilité métier | 25 | Règles métier écrites, jeu de données piégé, mesure des gains |
| Qualité technique | 20 | Moteur pur et testé, couverture, architecture claire |
| Utilité et parcours | 15 | File « Aujourd'hui », validation, historique |
| Automatisation et IA | 15 | Séquence de relances, IA encadrée et évaluée |
| Sécurité et maîtrise | 15 | Garde-fous, idempotence, reprise, rôles, journal |
| Usage et présentation | 10 | README, vidéo, démo fluide |

## Stack

| Couche | Choix |
|---|---|
| Cœur / API | Python 3.10+ · FastAPI · SQLite |
| Données | pandas (import) · `Decimal` |
| Tests | pytest (+ hypothesis pour les tests par propriétés) |
| Interface | Next.js · TypeScript · Tailwind (client typé généré depuis l'OpenAPI) |
| IA (bonus) | derrière une interface remplaçable, désactivable |
| Commandes | `python tasks.py init / demo / test / reset` |

**Ordre de construction : le back d'abord, le front ensuite.** Le front ne calcule rien ; il consomme l'API. Le contrat d'API (schémas Pydantic) est figé à la fin de la phase 5, puis le front démarre.

---

## Partie A — Back-end

### Phase 0 · Préparation ✅ (24/11)
- [x] Dépôt Git, licence MIT, `.gitignore`, `.gitattributes`
- [x] Environnement virtuel, dépendances à versions figées (`requirements.in` → `requirements.txt`)
- [x] Commandes `init` / `demo` / `test` / `reset` (`tasks.py`)
- [x] Schéma SQLite + migrations versionnées avec empreinte (`app/migrations/`)
- [x] pytest configuré : 39 tests verts (schéma, journal chaîné, références, générateur)
- [x] Générateur de données à graine fixe (138 lignes de factures, 35 paiements, 18 clients) + `attendus.json` ligne par ligne :
  - [x] à échoir, échéance le jour même, échues aux bornes de tranches (1, 7, 15, 16, 30, 31, 60, 61, 90, 91, 120 j)
  - [x] payées totalement / partiellement / en deux fois / trop-perçu
  - [x] doublons exacts, conflits de numéro, quasi-doublons, ré-import via un 2ᵉ fichier
  - [x] 13 lignes invalides (champ manquant, date impossible, montant négatif/nul/non numérique, décimales XOF, devise inconnue)
  - [x] montants extrêmes (500 FCFA, 15 M FCFA) et montant aberrant
  - [x] clients : bon payeur, retardataire, sensible, sans contact, inconnu
  - [x] litiges déclarés, dont un partiellement payé
  - [x] paiements : référence correcte, saisie libre, mal saisie, inconnue, absente, ambiguë, en double
  - [x] dates : jour férié, fin de mois, fin février, changement d'année, échéance avant émission
  - [x] formats : dates JJ/MM/AAAA, montants « 1 250 000 », espaces parasites, EUR « 1250,50 », lot 2 en Windows-1252 avec virgule et autres noms de colonnes
- [x] Règles métier écrites dans [docs/regles_metier.md](docs/regles_metier.md)
- [x] Journal de bord de l'équipe : [docs/journal_equipe.md](docs/journal_equipe.md)
- [ ] Interroger un gestionnaire / mentor et valider les points **[à valider]** des règles métier
- [ ] Mesurer la référence manuelle (temps pour 50 factures, erreurs)

**Sortie** : `init` + `test` passent sur une machine neuve ; le jeu de données est généré. ✅ (à refaire sur le poste d'un coéquipier)

### Phase 1 · Import et validation ✅ (24/11)
- [x] Import CSV / XLSX (factures, clients, paiements), détection encodage (UTF-8, BOM, Windows-1252) et séparateur
- [x] Correspondance de colonnes par synonymes (accents et casse ignorés) + correspondance manuelle + aperçu sans écriture
- [x] Empreinte du fichier : refus d'un fichier déjà importé, même renommé (refus journalisé)
- [x] Import transactionnel (tout ou rien), testé par une panne simulée en plein import
- [x] Contrôles : champs obligatoires, dates, montants (`1 250 000`, `1250,50`), décimales par devise, échéance ≥ émission, devise, client connu, montant aberrant
- [x] Doublons : exact, conflit de numéro, quasi-doublon (fichier et base), ré-import inter-fichiers
- [x] Résolution humaine journalisée : ignorer / remplacer un conflit, confirmer / annuler une facture douteuse, valider un client inconnu
- [x] Rapport d'import + export CSV des rejets avec motif
- [x] API : `/api/imports/*`, `/api/anomalies`, `/api/factures/a-verifier`, `/api/clients/{id}/valider` (auditeur en lecture seule)

**Sortie** : chaque anomalie du jeu piégé est détectée, prouvée par un test. ✅ 100 % des lignes conformes à `attendus.json` (clients, 2 lots de factures, paiements) ; 125 tests, couverture 92 %.

### Phase 2 · Moteur de calcul (fonctions pures) ✅ (24/11)
- [x] Solde = TTC − paiements rapprochés − avoirs ; trop-perçu et paiement partiel
- [x] Une seule fonction d'arrondi (`montants.arrondir`, demi-supérieur)
- [x] Retard calculé à une « date du jour » injectable ; jours ouvrés en option avec fériés béninois (Pâques calculé)
- [x] Tranches : non échue, 1-15, 16-30, 31-60, 61-90, > 90
- [x] Statuts : à échoir, échue, partiellement payée, payée, en litige, suspendue, clôturée
- [x] Table de transitions autorisées, décisions réservées à l'humain ; chaque transition est journalisée et incrémente la version
- [x] Rapprochement : référence exacte → montant + téléphone → proposition à valider ; références inconnues / mal saisies, facture déjà soldée, autre devise ; aucun rapprochement ambigu appliqué seul ; idempotent
- [x] Actions humaines : litige, suspension, avoir, passage en perte, valider / rejeter / annuler un rapprochement
- [x] Tests unitaires, tests par propriétés, non-régression sur le jeu figé

**Sortie** : 100 % des cas donnent le bon statut et le bon retard ; couverture du moteur > 90 %. ✅ 115 factures et 34 paiements conformes à l'oracle (statut, retard, tranche, solde, trop-perçu, drapeaux, rapprochement) ; couverture du moteur 96 % ; 160 tests.

### Phase 3 · Priorisation ✅ (24/11)
- [x] Score = somme pondérée (ancienneté, solde, historique de retard), en `Decimal` ; poids et plafond dans `parametres`
- [x] Hiérarchie documentée : exclusions → gros montants en tête → score ↓ → retard ↓ → solde ↓
- [x] Départage stable (numéro de facture)
- [x] Historique client chiffré, sans étiquette « mauvais payeur »
- [x] Explication par gabarit + détail du calcul facteur par facteur ; « pourquoi cette facture est-elle ici ? »
- [x] File « Aujourd'hui » : étape proposée, validation humaine signalée, filtres (tranche, client, montant, étape), exclusions motivées (payée, litige, suspendue, à vérifier, promesse, relance récente, étape déjà faite)
- [x] Bonus : simulation de nouveaux poids sans enregistrement ; modification réservée au validateur

**Sortie** : ordre identique au calcul manuel ; chaque rang a son explication. ✅ Jeu de 5 factures calculé à la main reproduit exactement ; propriétés (score borné, monotone) ; aucune facture oubliée ni comptée deux fois sur le jeu de démo ; 173 tests, couverture 93 %.

### Phase 4 · Relances ✅ (24/11)
- [x] Séquence réglable : R0 (−3 j, option) · R1 (+1 j) · R2 (+10 j) · R3 (+30 j, humain) · R4 (+45 j, humain) · R5 (+90 j, escalade)
- [x] Délai minimal entre deux relances (date métier) ; un seul message par client et par jour (lot d'envoi, multi-devises)
- [x] Gabarits par étape et canal (SMS, WhatsApp, e-mail), vouvoiement + touche béninoise, singulier/pluriel, lots à étapes mixtes exacts ; contrôle de ton et de longueur
- [x] Référence de paiement avec clé de contrôle ; fiche de paiement PDF (fpdf2)
- [x] Connecteur bac à sable (dossier `data/sortants/` + table `messages_sortants`), dédupliqué par clé d'envoi, derrière une interface unique
- [x] Saisie des réponses : promesse / délai (suspend jusqu'à la date), paiement annoncé, litige, injoignable
- [x] Escalade R5 : dossier interne, jamais de message client ; arrêt d'urgence et plage horaire respectés

**Sortie** : chaque facture éligible génère le bon message, à la bonne étape, une seule fois. ✅ Vérifié sur tout le jeu de démo (une relance par facture éligible, étape exacte, valeurs du message identiques aux données calculées, idempotent) ; 233 tests, couverture 93 %.

### Phase 5 · Garde-fous ✅ (24/11)
- [x] Revalidation juste avant l'envoi et à l'approbation (version, solde, statut, paiement en attente, promesse) ; annulation journalisée
- [x] Vérification que le message ne contient que les valeurs calculées (numéros, soldes, références ; aucun montant inventé)
- [x] File de validation humaine : litige, gros montant, R3-R5, client sensible, donnée incertaine, message non conforme
- [x] Actions : approuver / modifier / suspendre / rejeter (motif obligatoire) ; message modifié revérifié
- [x] Validation groupée des lots ordinaires (R3 seule raison), chaque lot revalidé et journalisé
- [x] Idempotence : clé facture + étape + échéance, `UNIQUE` en base, même transaction ; anti double-clic `Idempotency-Key`
- [x] Verrou contre deux envois concurrents, repris si le processus détenteur est mort
- [x] États : brouillon → à valider → validée → en cours d'envoi → envoyée / échec / annulée
- [x] Reprise au démarrage des lots « en cours d'envoi » via l'accusé du connecteur
- [x] Test qui tue un vrai processus en pleine file (3 instants) et vérifie l'absence de doublon
- [x] Sessions (PBKDF2, jeton 8 h) ; rôles gestionnaire / validateur / auditeur ; téléphones masqués pour l'auditeur
- [x] Arrêt d'urgence global journalisé (validateur, motif obligatoire)
- [ ] Base chiffrée : non (limite documentée)

**Sortie** : « je tue le programme en pleine file d'envoi, je le relance, aucune relance en double » fonctionne à chaque essai. ✅ Coupures à 0,8 / 1,6 / 2,7 s : cas « tué avant l'envoi » (remis en file) et « tué après l'envoi, avant l'enregistrement » (confirmé sans renvoi) couverts ; 259 tests, couverture 94 %.
**→ Contrat d'API figé, le front peut démarrer.**

### Phase 6 · Journal, audit, indicateurs (API)
- [ ] Journal : horodatage, acteur (humain / système / IA), action, objet, avant, après, règle
- [ ] Trigger SQL qui refuse `UPDATE` / `DELETE` ; chaînage par empreintes + endpoint de vérification
- [ ] Recherche et export CSV du journal
- [ ] Historique par facture + « pourquoi cette facture est-elle ici ? »
- [ ] Indicateurs : total à recouvrer, tranches, top 10, charge de validation, recouvré après relance, délai moyen, promesses tenues, anomalies évitées
- [ ] Horloge simulée (avancer de N jours), scénario de démo, `reset`

**Sortie** : à partir du seul journal, on explique chaque relance envoyée, bloquée ou annulée.

### Phase 7 · IA encadrée (bonus, désactivable)
- [ ] Rédaction : reçoit des champs calculés + gabarit ; valeurs sensibles injectées après génération via marqueurs ; repli sur gabarit fixe
- [ ] Vérificateur : extraction des montants / dates / références et comparaison exacte ; mots interdits, longueur
- [ ] Classification des réponses (promesse, paiement, litige, délai, info, sans rapport) avec seuil de confiance ; ne change jamais seule un statut sensible
- [ ] Évaluation sur 30-50 exemples étiquetés : exactitude, rappel sur litiges, taux de blocage
- [ ] Protection contre l'injection, minimisation des données, journal entrées/sorties, interrupteur global

**Sortie** : 0 message envoyé avec une valeur différente des données calculées.

---

## Partie B — Front-end (après la phase 5)

> Identité distinctive mais sobre, sans landing page. Je te proposerai 2 ou 3 pistes visuelles à choisir avant de coder.

- [ ] Client d'API typé généré depuis l'OpenAPI
- [ ] Pages : import (+ correspondance de colonnes, rapport), file « Aujourd'hui », file de validation, fiche facture avec frise, journal, tableau de bord, paramètres
- [ ] Boutons désactivés pendant l'appel + clé d'idempotence envoyée à chaque action
- [ ] Rôles visibles (gestionnaire / validateur / auditeur)
- [ ] Contrôle de l'horloge simulée pour la démo
- [ ] `demo` lance API + front ensemble

---

## Partie C — Tests, mesures, livrables

### Tests et robustesse
- [ ] Pyramide : unitaires · intégration · bout en bout · robustesse (interruption, double clic, concurrence, fichier corrompu) · sécurité · IA
- [ ] Rapport de couverture dans le dépôt
- [ ] 10 000 factures : temps d'import et de calcul mesurés
- [ ] Sauvegarde / restauration en une commande
- [ ] Aucun secret dans le dépôt ; licences des dépendances déclarées

### Mesure des gains
- [ ] Protocole : 50 factures traitées à la main puis avec l'outil, chronométrées
- [ ] Erreurs comptées : facture payée relancée, doublon, mauvaise priorité, mauvais montant, relance oubliée
- [ ] Tableau « manuel / outil » + coût de fonctionnement

### Livrables
- [ ] **Prototype** : `init` + `demo`, `reset`, reprise démontrée, testé sur une autre machine
- [ ] **Code source** : dépôt accessible, tag de rendu, licences
- [ ] **README** : présentation, installation, lancement, comptes de test, scénario de démo, tests, limites
- [ ] **Rapport (3-5 pages)** : besoin, architecture, règles métier, garde-fous, tests et gains, limites et coûts
- [ ] **Fiche IA** : modèle, données envoyées, évaluation, seuils de revue, mode sans IA
- [ ] **Vidéo (2-3 min)** : problème → import et anomalies → priorisation → relance et validation humaine → coupure / reprise → chiffres et journal

---

## Priorités si le temps manque

1. Calculs et statuts exacts, import sans erreur
2. Priorisation expliquée, séquence de relances
3. Validation humaine, revalidation, idempotence, reprise
4. Journal d'audit et tests
5. Mesure des gains et tableau de bord
6. Livrables
7. IA de rédaction et classification
8. Bonus

## Checklist finale

- [ ] `init` + `test` + `demo` passent sur une machine neuve
- [ ] Le jeu piégé donne tous les résultats attendus
- [ ] Aucune facture payée relancée dans la démo
- [ ] Coupure / reprise réussie trois fois de suite
- [ ] Le journal explique chaque décision
- [ ] Le mode sans IA fonctionne
- [ ] Aucun secret, licences déclarées
- [ ] README, rapport, fiche IA, vidéo livrés
- [ ] Tag de version posé

## Décisions prises

| Sujet | Décision |
|---|---|
| Ordre | Back complet (phases 0 à 6) avant le front ; le contrat d'API est figé en fin de phase 5 |
| Interface | Identité visuelle distinctive mais sobre : pas de template générique, pas de landing page, micro-animations utiles seulement ; on arrive directement sur la file « Aujourd'hui » |
| Commandes | `python tasks.py init / demo / test / reset` (pas de `make`) |
| Gros montant | 1 000 000 FCFA (réglable dans `parametres`) |

## Questions ouvertes

- Fournisseur d'IA pour le bonus (API distante ou modèle local) : à trancher en phase 7
