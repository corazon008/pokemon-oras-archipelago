# Rapport 005 — profil de sauvegarde isolé

Date : 17 novembre 2026.

## Résultat et limite

Un profil privé permet désormais de rejouer des boutons natifs et de reprendre
le même répertoire utilisateur d'Encore. Les fichiers source restent intacts.

**La sauvegarde candidate ne permet pas encore de valider une partie jouable.**
Le fichier `main` trouvé a la taille ORAS attendue, mais ne contient pas le
marqueur de format reconnu par PKHeX. Une copie affiche le choix de langue,
puis sa confirmation, pas un écran « Continuer ».

Cela ne permet pas de conclure que le fichier original est corrompu : il peut
notamment être non initialisé ou ne pas représenter une sauvegarde déchiffrée
reconnue. Il n'est pas interprété comme un état de progression valide.

## Essais réellement exécutés

1. Copie de `main` seul dans un profil neuf : choix de langue.
2. Essai de boutons natifs : confirmation de langue et animation d'introduction.
3. Nouvelle copie incluant les métadonnées d'archive Encore : choix de langue
   et confirmation, toujours sans preuve d'une partie chargée.
4. Contrôle des empreintes des sources après exécution : inchangées.
5. Ajout d'un contrôle de format à l'import : les nouveaux imports de ce
   candidat sont refusés avant lancement.

Les premiers essais précèdent ce renforcement. Ils ne sont donc pas présentés
comme des imports ayant passé le contrôle final.

Les [résultats structurés](../research/save-profile-results.json) renvoient
au dernier essai conservé. Captures, sauvegardes et logs restent privés sous
`/tmp/opencode/` ; aucune donnée de jeu brute n'est ajoutée au dépôt.

La création ou modification d'un fichier `main` pendant l'initialisation du jeu
**ne compte pas** comme un cycle de sauvegarde/rechargement d'une partie.
BH-01 reste partiel ; BH-02 n'est pas validé.

## Formats et chemins sourcés

- PKHeX, commit `6c9583883c7551ac74a4b74180cead249d4277b8`,
  [`SaveUtil.cs`](https://github.com/kwsch/PKHeX/blob/6c9583883c7551ac74a4b74180cead249d4277b8/PKHeX.Core/Saves/Util/SaveUtil.cs) :
  taille ORAS `0x76000`, identification par marqueur à `taille - 0x1F0`.
- Encore, commit `49a332221e1c9dffcc2c52f85a1765b1951c222f`,
  [`archive_source_sd_savedata.cpp`](https://github.com/CasualPokePlayer/encore/blob/49a332221e1c9dffcc2c52f85a1765b1951c222f/src/core/file_sys/archive_source_sd_savedata.cpp) :
  arborescence SD et fichier `00000001.metadata`.
- BizHawk 2.11.1, `Encore.IInputPollable.cs` et `JoypadLuaLibrary.cs` :
  noms des boutons et API d'injection native.

Le contrôle taille/marqueur n'est **pas** une validation des CRC de tous les
blocs. Le champ `seed_validation` le précise ; aucune compatibilité de
progression n'est déduite de ce seul contrôle.

## Outils

Créés :

- `tools/run_bizhawk_save_probe.py`.
- `tools/bizhawk_ui_probe.lua`.
- `tests/test_bizhawk_save_probe.py`.
- `docs/research/save-profile-results.json`.
- Présent rapport.

Modifiés : README principal, documentation des outils, protocole et sources.

Le lanceur crée ou réutilise uniquement un profil privé de test :

- Identification de la ROM et association du profil à son SHA-256.
- Copie initiale de l'émulateur, sans son répertoire utilisateur d'origine.
- Import facultatif d'un `main` reconnu et de ses métadonnées d'archive.
- Ouverture exclusive des destinations : aucun écrasement d'une copie existante.
- Macros bornées, boutons ordinaires uniquement ; aucune API mémoire appelée.
- Captures et journal de chaque tentative séparés.
- Mode interactif sans macro ni limite de temps automatique.
- Contrôle des empreintes des sources après fermeture.

La séquence de boutons n'est pas un détecteur de locations. Les changements
d'écran ne constituent pas des checks Archipelago.

## Tests

- **35 tests unitaires réussis** sur l'ensemble des outils.
- Tests des plans de boutons, limites, refus d'import incorrect et absence
  d'écrasement des fichiers.
- Deux tests Lua avec API mémoire interdite : séquence native correcte et
  refus d'un bouton non autorisé.
- Syntaxe Lua vérifiée.
- Essais OR réels et arrêt propre ; le mode interactif manuel n'a pas encore
  été exécuté.

## Pré-requis restant

Créer une partie et une sauvegarde native réellement jouable, dans le profil
isolé, puis fermer proprement l'émulateur. Le mode interactif documenté dans
`tools/README.md` évite toute manipulation des sauvegardes originales.

Après cette étape : vérifier le rechargement, valider le format de `main` puis
identifier une variable d'inventaire observable. Aucune écriture RAM directe
avant validation du build et des structures concernées.
