# Recouvra

Assistant de recouvrement des factures impayées pour une PME béninoise. Il importe les factures, rapproche les
paiements mobile money, priorise les relances avec une explication pour chaque rang, prépare des messages
courtois et fait valider les cas sensibles par un humain. Il ne relance jamais une facture payée, ne fait jamais
deux fois la même action et inscrit chaque décision dans un journal infalsifiable.

Hackathon BWAI, cas pratique 1. Prototype local, données fictives, licence MIT.

## Prérequis

- Python 3.10 ou plus récent
- Node.js 20 ou plus récent (interface)
- Aucune connexion internet nécessaire, sauf pour la rédaction des messages par l'IA (option)

## Installation et lancement

```bash
git clone https://github.com/Merveillegms/bwai-recouvrement-.git
cd bwai-recouvrement-
python tasks.py init     # environnement Python, base SQLite, jeu de démo, installation et construction de l'interface
python tasks.py demo     # interface http://127.0.0.1:3000 et API http://127.0.0.1:8000/docs (Ctrl+C pour arrêter)
```

| Commande | Effet |
|---|---|
| `python tasks.py test` | lance les 305 tests |
| `python tasks.py reset` | remet la base et les données de démo à zéro (application arrêtée) |
| `python tasks.py sauvegarder` | copie cohérente de la base dans `data/sauvegardes/` |
| `python tasks.py restaurer <fichier>` | vérifie puis restaure une copie (l'ancienne base est conservée) |
| `python tasks.py couverture` | tests et rapport de couverture (`docs/couverture.txt`) |
| `python tasks.py mesurer` | gains face à une référence, charge de 10 000 factures, évaluation de l'IA, licences |

## Configuration de l'IA (facultatif)

Copier `.env.exemple` en `.env` et renseigner une clé Google AI Studio (`GEMINI_API_KEY`) ou Hugging Face
(`HF_TOKEN`). Le fichier `.env` n'est jamais versionné. Sans clé, tout fonctionne avec les gabarits fixes ;
la classification des réponses clients, elle, est locale et n'a besoin d'aucune clé. L'IA s'active dans
Réglages (compte validateur).

## Comptes de test

| Identifiant | Mot de passe | Rôle |
|---|---|---|
| gestionnaire | demo-gestionnaire | importe, prépare et envoie les relances, saisit les réponses |
| validateur | demo-validateur | valide les cas sensibles, règle les poids, active l'IA, arrêt d'urgence |
| auditeur | demo-auditeur | consulte tout en lecture seule, téléphones masqués |

## Scénario de démonstration

1. Ouvrir http://127.0.0.1:3000, cliquer « Se connecter », puis « gestionnaire ».
2. Sur Aujourd'hui, « Charger le jeu de démonstration » : 138 lignes piégées au 15 décembre 2026.
3. Page Import : lignes rejetées avec leur motif, factures à vérifier, client inconnu à compléter.
4. Aujourd'hui : cliquer une ligne pour lire l'explication de son rang, puis « Préparer les relances du jour ».
5. Se reconnecter comme validateur. Réglages : « Activer l'IA ». Validation : « Faire rédiger par l'IA »,
   lire, approuver ou modifier, puis « Envoyer les messages validés » (messages écrits dans `data/sortants/`).
6. Réponses clients : coller « Je passe payer vendredi au bureau », confirmer la proposition.
7. Fiche d'une facture : « Simuler le paiement du client », puis lire la frise chronologique.
8. Réglages : « Avancer l'horloge » de 10 jours, puis Tableau de bord et Journal.

La coupure sans doublon se montre avec `python -m pytest tests/test_coupure.py -s` : un vrai processus d'envoi est
tué à trois instants, puis relancé.

## Documents

| Document | Contenu |
|---|---|
| [docs/rapport.md](docs/rapport.md) | rapport : besoin, architecture, règles, garde-fous, tests, résultats, limites, coûts |
| [docs/fiche_ia.md](docs/fiche_ia.md) | modèles, données envoyées, évaluation, erreurs, seuils de revue humaine |
| [docs/regles_metier.md](docs/regles_metier.md) | toutes les règles métier, codes d'anomalie, transitions de statut |
| [docs/mesure_gains.md](docs/mesure_gains.md) | comparatif chiffré avec une relance naïve ; [protocole de mesure réelle](docs/protocole_mesure.md) |
| [docs/video.md](docs/video.md) | scénario minuté de la vidéo |
| [docs/licences.md](docs/licences.md) | licences des dépendances |
| [ROADMAP.md](ROADMAP.md) | plan de travail et état d'avancement |

## Structure

```
app/            API FastAPI et cœur métier (import, calculs, priorisation, relances, garde-fous, journal)
app/ia/         rédaction (Gemini ou Hugging Face) et classification locale des réponses
app/migrations/ schéma SQLite versionné
frontend/       interface Next.js (page d'accueil et application)
data/demo/      jeu de test piégé et résultats attendus ligne par ligne
data/ia/        exemples étiquetés pour l'entraînement et l'évaluation du classifieur
tests/          305 tests (unitaires, intégration, bout en bout, coupure réelle, IA)
```

## Limites connues

- Envoi simulé : les messages sont écrits dans `data/sortants/` ; un vrai fournisseur demande un connecteur.
- Base SQLite non chiffrée.
- Jours fériés béninois et certaines règles à valider avec un professionnel.
- Les gains de temps sont estimés ; le protocole de chronométrage est fourni.

## Licence

MIT, voir [LICENSE](LICENSE). Licences des dépendances : [docs/licences.md](docs/licences.md).
