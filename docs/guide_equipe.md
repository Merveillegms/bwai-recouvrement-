# Guide de test pour l'équipe

Objectif : vérifier que Recouvra s'installe et fonctionne sur une machine qui n'a jamais servi au développement.
Durée : environ 20 minutes (dont 5 à 10 minutes d'installation la première fois).

## 1. Prérequis à installer

| Logiciel | Version | Où le trouver | Vérifier avec |
|---|---|---|---|
| Git | récente | https://git-scm.com | `git --version` |
| Python | 3.10 ou plus | https://www.python.org (sous Windows, cocher « Add python.exe to PATH ») | `python --version` |
| Node.js | 20 ou plus (version LTS) | https://nodejs.org | `node --version` |

Sous macOS et Linux, remplacer `python` par `python3` dans toutes les commandes.

## 2. Installer et tester

Dans un terminal (PowerShell, Terminal ou le terminal de VS Code) :

```bash
git clone https://github.com/Merveillegms/bwai-recouvrement-.git
cd bwai-recouvrement-
python tasks.py init
python tasks.py test
```

**Résultat attendu** :
- `init` se termine sans erreur ; la dernière partie affiche la liste des pages construites (`/`, `/app`, `/connexion`…).
- `test` se termine par **`305 passed`** (2 à 4 minutes). Le test de coupure lance et arrête volontairement un
  programme d'envoi trois fois : c'est normal.

## 3. Lancer l'application

```bash
python tasks.py demo
```

Ouvrir **http://127.0.0.1:3000** dans le navigateur. Ctrl+C dans le terminal arrête tout.

Parcours à vérifier (5 minutes) :

1. La page d'accueil s'anime (la file se trie, un paiement annule une relance).
2. « Se connecter », puis « gestionnaire ».
3. « Charger le jeu de démonstration » : la file du jour affiche 73 factures à relancer.
4. Cliquer une ligne : le panneau de droite explique son rang.
5. « Préparer les relances du jour », puis aller sur Validation.
6. Se déconnecter (en bas de la barre latérale), entrer comme « validateur », approuver un message, puis
   « Envoyer les messages validés ».
7. Ouvrir Journal : le badge indique « Chaîne d'empreintes intacte ».

Sur téléphone ou en fenêtre étroite, vérifier aussi que rien ne déborde.

## 4. L'IA

Sans clé, la rédaction par l'IA est désactivée : c'est normal et tout le reste fonctionne. Ne pas partager de clé
par message. Pour tester la rédaction, chacun crée sa propre clé gratuite sur https://aistudio.google.com/apikey ,
copie `.env.exemple` en `.env` et colle la clé après `GEMINI_API_KEY=`. Le fichier `.env` n'est jamais envoyé sur
GitHub.

## 5. Problèmes fréquents

| Message | Solution |
|---|---|
| `python` n'est pas reconnu | Réinstaller Python en cochant « Add to PATH », ou utiliser `py tasks.py …` sous Windows |
| `Python 3.10 ou plus récent est requis` | Installer une version plus récente de Python |
| `Node.js (npm) est requis` | Installer Node.js LTS puis rouvrir le terminal |
| La page ne s'ouvre pas, port déjà utilisé | Fermer l'autre terminal où `demo` tourne déjà, ou redémarrer |
| `reset` : impossible de supprimer la base | Arrêter `demo` (Ctrl+C) avant `python tasks.py reset` |
| Installation très lente | Normal la première fois (antivirus, téléchargements) ; les lancements suivants sont rapides |

## 6. Que renvoyer

Dans le groupe de l'équipe :
- « OK » si les étapes 2 et 3 sont passées, avec le système (Windows, macOS, Linux) ;
- sinon : la commande lancée, le **message d'erreur complet** (copié, pas résumé), les résultats de
  `python --version` et `node --version`, et une capture d'écran si c'est un problème d'affichage.
