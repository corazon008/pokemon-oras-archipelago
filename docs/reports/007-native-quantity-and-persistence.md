# Rapport 007 — quantité native et persistance

Date : 17 novembre 2026.

## Résultat

Sur la copie OR de travail :

1. Lecture du bloc inventaire avant l'action : identique à la sauvegarde
   validée, Potion ×1.
2. Action native **Discard** dans le sac.
3. Lecture après l'action : Potion ×0, autres objets et octets hors poche
   Médecine inchangés.
4. Sauvegarde par le menu natif, fermeture puis redémarrage complet.
5. Poche Médecine toujours vide à l'écran ; 58 CRC du fichier sauvegardé valides.

**La sauvegarde source fournie par l'utilisateur conserve Potion ×1 et son
SHA-256 initial. Aucune écriture RAM directe.**

## Champ observé

Pour le seul build OR identifié par
`d76faafacd746fdcc5ec04a60b8b82ceb9678c3ad937b374234a506c50c417e4` :

- Inventaire : `System Bus`, `0x08C6AC80`.
- Poche Médecine : offset `0x970` dans ce bloc, d'après le layout PKHeX.
- Premier slot : ID interne 17 (Potion), puis quantité `uint16` little-endian.
- Champ quantité : **`0x08C6B5F2`**, obtenu par addition des offsets
  documentés puis vérifié par les lectures avant/après.

Ce n'est ni un ID Archipelago, ni une adresse approuvée pour AS ou une autre
révision. Le profil garde `write_allowed: false`.

## Pourquoi le zéro observé est significatif

Une lecture nulle isolée pourrait provenir d'une page non mappée. Le diagnostic
exige donc, dans le même processus :

- Une lecture initiale de l'inventaire complet, non nul, conforme au fichier
  dont les CRC ont été vérifiés.
- Une seconde lecture après l'action native.
- Une quantité cible réellement différente.
- Des objets non ciblés inchangés et des octets hors Médecine inchangés.
- Des captures montrant l'action de rejet et la poche vide.

La commande `--expect-medicine 17:0` est une **comparaison attendue côté Python**.
Elle n'envoie ni quantité ni commande de modification à la mémoire du jeu.
Les deux opérations mémoire sont des lectures Lua.

## Sauvegarde et rechargement

Le premier essai de macro de sauvegarde n'a pas sauvegardé : X a fermé le menu
parent après la sortie du sac. Le diagnostic de variation RAM a réussi,
mais le SHA-256 de `main` est resté identique. Cet essai n'est pas retenu
comme preuve de persistance.

Après correction de la séquence native, l'écran affiche le message de
sauvegarde réussie. Le fichier de travail devient :

```text
839cd0baa0cb631ecc07174841081769b1140cca352e24f7fb0c39250b60e8f7
```

Ses 58 CRC sont valides et son inventaire ne contient plus la Potion.
Un nouveau processus recharge ensuite cette partie, sans savestate, et
affiche la poche Médecine vide. Son fichier reste à la même empreinte.

La source reste :

```text
7fe9813cf5ed377e67da4d9e279a69cd63efc697b1a07c3b6f9354a85896f465
```

Les [résultats structurés](../research/native-quantity-results.json) renvoient
aux captures et fichiers privés. Aucun octet propriétaire brut n'est distribué.

## Outillage modifié

- `tools/bizhawk_ui_probe.lua` : callback de lecture après une étape précise.
- `tools/bizhawk_inventory_probe.lua` : journal et deux captures de l'inventaire.
- `tools/run_bizhawk_save_probe.py` : `--sample-step` et `--expect-medicine`.
- `tools/oras_save.py` : comparaison sémantique de la variation, sans générer
  de données à écrire dans le jeu.
- Tests et documentation associés.
- Nouveau `docs/research/native-quantity-results.json` et présent rapport.

Dans le résultat différentiel, `matches_validated_save: false` concerne le
bloc **après** action comparé au fichier **avant lancement**. C'est attendu
ici : la validation pertinente est `differential.passed`, qui exige notamment
`before_matches_validated_save: true`.

`complete: true` pour cette sonde ne valide pas implicitement une sauvegarde :
le message natif, le nouveau fichier, ses CRC et un redémarrage ont été
contrôlés séparément.

## Tests et portée

**56 tests unitaires réussis**, dont :

- Baseline fausse ne pouvant pas faire passer une quantité zéro.
- Quantité inchangée refusée comme preuve différentielle.
- Modification d'un autre objet ou d'une autre poche refusée.
- Lecture avant/après sans appel d'écriture mémoire.

BH-04 OR dispose désormais d'une variable observée et d'une variation native
reproductible. BH-02 OR comprend une modification native persistante.
Il ne s'agit pas de la persistance d'un item reçu depuis AP.

À valider ensuite : lecture de cette variable via le pont Python/AP, première
écriture contrôlée dans une copie, événement permanent réel et boucle serveur.
Aucune livraison, idempotence de commandes ou logique complète n'est simulée.
