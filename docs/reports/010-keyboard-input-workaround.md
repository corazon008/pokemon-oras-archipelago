# Rapport 010 — contournement clavier d'une entrée bloquée

Date : 17 novembre 2026.

## Incident constaté

L'utilisateur signale une poussée constante vers le haut-gauche dans la
session interactive destinée à prolonger l'essai d'événement du rapport 009.

Le profil de test contient des bindings Xbox pour le Circle Pad, le C-Stick
et les boutons. Le journal de l'essai
`/tmp/opencode/oras-save-ev5_8vq1/attempt-oa_rb5_v/stdout.txt` montre une
connexion, puis une déconnexion de « Xbox Wireless Controller ».

C'est une piste, **pas une preuve de cause racine** : aucune capture des
valeurs d'axes au moment du problème n'a été faite. Cet essai interactif ne
charge aucun script Lua et aucune macro. Il se termine proprement, et le
fichier `main` conserve l'empreinte :

```text
1c933f1cf0be502bda4748135bf4ec1301e6deb0c9670acafb59bcef0312434a
```

La poussée signalée ne constitue pas une nouvelle preuve de progression.

## Contournement demandé

L'utilisateur accepte le clavier seul et précise qu'il n'a pas besoin d'une
nouvelle copie pour jouer. Le même profil de test est réutilisé, sans réimport
ni duplication supplémentaire.

Nouvelle option explicite : `--interactive --keyboard-only`.

- Remplace uniquement les bindings 3DS par ceux du clavier.
- Retire les bindings hôte des quatre axes Circle Pad/C-Stick et l'autofire 3DS.
- Conserve le tactile à la souris.
- Désactive HIDAPI uniquement dans le processus enfant.
- Ne touche ni aux ROMs, ni aux bindings du profil d'origine ou des autres systèmes.
- Aucun changement du comportement interactif par défaut.

Flèches : déplacement ; X : confirmer ; Z : retour ; S : menu du jeu.
Les valeurs neutres des sticks sont 0 d'après la définition du contrôleur
Encore 2.11.1 ; aucune valeur d'axe ni mémoire du jeu n'est forcée par Lua.

Le lancement clavier est effectué sur `/tmp/opencode/oras-save-ev5_8vq1`.
La disparition du problème reste à confirmer par l'utilisateur ; ce rapport
ne prétend pas corriger le pilote SDL ou valider une manette.

L'essai clavier `/tmp/opencode/oras-save-ev5_8vq1/attempt-z2tn_bf_` s'est
ensuite terminé proprement. Aucun gamepad connecté n'est annoncé dans son
journal. Le fichier `main` a changé, avec 58 CRC valides :
`99c19458cf96f097f15f0e63c1d0fe72d689f06d76cc3bebe48dc0224d548356`.
La progression de ce fichier sera étudiée séparément ; un nouveau fichier
ne prouve pas à lui seul la scène jouée ou la disparition complète de la dérive.

## Fichiers et tests

- `tools/run_bizhawk_save_probe.py` : option et transformation isolée du profil.
- `tools/run_bizhawk_probe.py` : précision du commentaire sur le hint enfant.
- `tests/test_bizhawk_save_probe.py` : contrôles et absence de mutation du profil
  fourni, conservation des autres systèmes et du tactile.
- `tools/README.md` et présent rapport.

**76 tests unitaires réussis.** Aucun nouveau résultat d'événement ou de
livraison AP n'est déduit de ces tests d'entrée.
