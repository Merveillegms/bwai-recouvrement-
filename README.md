# Recouvrement BWAI

Assistant de recouvrement des factures impayées : il importe les factures, calcule les retards,
priorise, prépare des relances graduées et fait valider les cas sensibles par un humain.
Il ne relance jamais une facture payée, ne fait jamais deux fois la même action et journalise
chacune de ses décisions.

> Projet en cours — voir [ROADMAP.md](ROADMAP.md). Ce README sera complété en phase 9.

## Prérequis

- Python 3.10 ou plus récent
- Node.js 20+ (pour l'interface, à venir)

## Démarrage

```bash
python tasks.py init    # environnement, base SQLite, jeu de données de démo
python tasks.py test    # tests
python tasks.py demo    # API sur http://127.0.0.1:8000 (docs : /docs)
python tasks.py reset   # remet base et données à zéro
```

## Comptes de test

Connexion : `POST /api/auth/connexion` puis en-tête `Authorization: Bearer <jeton>`.

| Identifiant | Mot de passe | Rôle |
|---|---|---|
| gestionnaire | demo-gestionnaire | prépare les relances |
| validateur | demo-validateur | approuve les cas sensibles |
| auditeur | demo-auditeur | lecture seule |

## Jeu de données

`data/demo/` contient un jeu fictif, généré avec une graine fixe (`python -m app.cli generer`),
volontairement piégé : doublons, champs invalides, encodages différents, paiements ambigus…
`attendus.json` décrit le résultat attendu pour chaque ligne. Règles : [docs/regles_metier.md](docs/regles_metier.md).

## Licence

MIT — voir [LICENSE](LICENSE).
