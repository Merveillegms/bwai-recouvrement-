# Déploiement en ligne : Render (API) et Vercel (interface)

Le prototype tourne en local (`python tasks.py demo`). Cette version en ligne est un bonus pour que le jury teste
sans rien installer. Durée : environ 20 minutes, une seule fois. Les deux plateformes sont gratuites et se
connectent au dépôt GitHub : chaque `git push` redéploie automatiquement.

```
Navigateur ──> Vercel (interface Next.js) ──/api──> Render (API FastAPI + SQLite)
```

Le navigateur ne voit qu'une adresse (celle de Vercel) : Vercel relaie `/api` vers Render.

## 1. API sur Render

1. Créer un compte sur https://render.com avec « Sign in with GitHub ».
2. **New** > **Blueprint**, choisir le dépôt `bwai-recouvrement-`, branche `main`.
3. Render lit le fichier `render.yaml` du dépôt et propose le service **recouvra-api** : cliquer **Apply**.
4. Attendre la fin de la construction (3 à 5 minutes), puis copier l'adresse du service, de la forme
   `https://recouvra-api.onrender.com` (le nom peut varier s'il est déjà pris).
5. Vérifier : ouvrir `https://<adresse-render>/api/sante`, la page doit afficher `{"statut":"ok",...}`.

## 2. Interface sur Vercel

1. Créer un compte sur https://vercel.com avec « Continue with GitHub ».
2. **Add New** > **Project**, importer le dépôt `bwai-recouvrement-`.
3. **Root Directory** : choisir `frontend` (indispensable). Le framework Next.js est détecté tout seul.
4. **Environment Variables** : ajouter `RECOUVREMENT_API` avec l'adresse Render de l'étape 1.4 (sans `/` final).
5. **Deploy**. L'adresse publique ressemble à `https://bwai-recouvrement.vercel.app`.

Sans la variable `RECOUVREMENT_API`, la construction échoue volontairement avec un message explicite. Si
l'adresse Render change, modifier la variable puis **Redeploy**.

## 3. Vérifier

1. Ouvrir l'adresse Vercel : la page d'accueil s'anime, et en haut à droite « Réveil du serveur… » devient
   « Serveur prêt ».
2. « Se connecter », « gestionnaire », puis « Charger le jeu de démonstration ».

## Ce qu'il faut savoir sur la version gratuite

| Comportement | Conséquence | Que faire |
|---|---|---|
| L'API s'endort après 15 minutes sans visite | Le premier accès prend environ une minute | Ouvrir la page d'accueil une minute avant la démonstration : elle réveille le serveur |
| Le disque de Render est effacé à chaque réveil ou redéploiement | Les données repartent à zéro | Cliquer « Charger le jeu de démonstration » ; c'est aussi un moyen simple de remettre la démo à zéro |
| Les comptes de démonstration sont publics | N'importe qui peut modifier les données | Sans gravité (données fictives) ; redémarrer le service sur Render remet tout à zéro |
| Pas de clé d'IA en ligne (`RECOUVREMENT_IA_FOURNISSEUR=aucun`) | La rédaction par Gemini n'est pas proposée ; la classification des réponses, locale, fonctionne | Montrer la rédaction par l'IA en local, dans la vidéo |

Pour activer la rédaction en ligne le temps d'une présentation : sur Render, **Environment**, mettre
`RECOUVREMENT_IA_FOURNISSEUR=gemini` et ajouter `GEMINI_API_KEY` (une clé neuve), puis les retirer ensuite.
Ne jamais écrire la clé dans le dépôt.
