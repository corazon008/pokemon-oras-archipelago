# Rapport 013 — réception du Pokédex et persistance du flag

Date : 17 novembre 2026.

## Résultat

**Flag Pokédex décimal 2722 : faux avant, vrai après jeu natif, toujours vrai
après sauvegarde, démarrage à froid et reconnexion du pont AP.**

Les deux fichiers ont 58 CRC valides. Après rechargement, le menu ouvre un
Pokédex fonctionnel : 1 Pokémon capturé, 4 vus. Les blocs EventWork relus via
Lua et l'API Python AP correspondent entièrement au fichier sauvegardé.

**Aucune écriture mémoire directe, aucun check envoyé à un serveur.**
Cette preuve concerne le seul build OR identifié ; aucun résultat AS.

## Comparaison avec le témoin avant

Le [rapport 012](012-pokedex-before-checkpoint.md) conserve le checkpoint négatif :
partie sur Route 103, avant retour au laboratoire, flag faux dans le fichier
et via AP avant/après reconnexion.

L'essai manuel `/tmp/opencode/oras-save-ev5_8vq1/attempt-4pje26wu` reprend le même
profil clavier, sans copie d'émulateur ni réimport. Il se ferme proprement avec
une nouvelle sauvegarde. Une copie de `main` et de ses métadonnées est préservée
dans `checkpoints/after-pokedex-n7rbztpv`, sans toucher au checkpoint précédent.

```text
Avant :
3b4e66edc55fbc46e0cab2e10d287f40d9082232e0a67cc244efc96f650a2bff

Après :
deec5f94d522504fdad98c432fb7364ea874e5b63bf3746b70923ee2e6cbd8fa
```

Dans EventWork, l'octet relatif `0x444` passe de `0x00` à `0x04`.
Cela correspond exactement au flag 2722 selon le layout PKHeX, sans changement
des sept autres bits du même octet :

```text
offset des flags 0x2F0 + (2722 // 8) = 0x444
masque = 1 << (2722 % 8) = 0x04
bloc RAM vérifié 0x08C7DAEC + 0x444 = System Bus:0x08C7DF30
```

Cette adresse est une observation dérivée d'un **bloc complet vérifié**, pas
une autorisation d'écriture. Le catalogue garde `write_allowed: false`.

La session manuelle change aussi six mots et les flags 208, 601 et 619.
Ces différences sont consignées sans leur attribuer des noms inventés.
Ce n'est pas un essai où un seul bit du jeu entier a changé. Les actions
intermédiaires ne sont pas capturées ; le lien sémantique s'appuie sur le nom
PKHeX, le témoin avant, le nouveau fichier et l'interface Pokédex fonctionnelle.

## Démarrage à froid et API AP

Essai : `/tmp/opencode/oras-save-ev5_8vq1/connector-attempt-je4_owev`.

Le nouveau processus démarre sans savestate dans le laboratoire, avec Birch
et le rival visibles. Deux connexions successives vérifient chacune :

1. Version du connecteur, système et domaines.
2. Préfixe de code conforme à la ROM.
3. Inventaire conforme à la sauvegarde.
4. Bloc EventWork complet conforme, puis flag 2722 vrai.

Total : **6 READ, aucune écriture**, sortie 0. Le fichier sauvegardé conserve
son empreinte. Le connecteur/API AP restent au commit figé du rapport 008.
Cela valide le transport local Python ↔ Lua, pas un serveur WebSocket.

## Interface Pokédex et stabilité au menu

Un autre processus est lancé pour observer les menus :

- `attempt-8fjah_o0` : menu natif ouvert, entrée Pokédex visible.
- `attempt-gm5aztuu` : ouverture effective du Pokédex, capture `step-13.png`.

Chaque essai lit le bloc complet avant ouverture du menu puis à la fin.
Il reste identique au fichier CRC-valide, avec le bit vrai ; les deux
sauvegardes sur disque restent inchangées et les sorties sont nulles.
Changer de contexte UI ne produit donc pas la détection à lui seul.

La macro de l'ouverture effective est :

```text
1800:-,2:A,600:-,2:A,600:-,2:A,600:-,2:X,120:-,2:Right,60:-,2:A,180:-
```

Appliquée uniquement au checkpoint après événement, via
`run_bizhawk_save_probe.py --read-event-work --event-sample-steps 7 --speed 400`.

## Portée

BH-08 OR dispose maintenant d'un **flag d'acquisition documenté**, d'un témoin
négatif réel, d'une transition native observée entre sauvegardes, d'un témoin
positif après rechargement et de lectures concordantes avant/après reconnexion.
Cela évite le seuil inventé sur la variable de scénario du candidat horloge.

Limites maintenues :

- Aucun nouvel identifiant AP ou règle de location approuvée en production.
- Pas d'observation frame par frame de la remise du cadeau.
- Pas de test couvrant toute la suite du scénario ou des savestates.
- Pas de serveur, `LocationChecks`, `ReceivedItems`, dédoublonnage ou index
  persistant encore testés.
- Pas d'accès d'écriture nouveau et pas de livraison d'objet dans cette phase.

## Fichiers, tests et suite

Modifiés : observation d'événements AP et sa documentation, tests du bit positif
après reconnexion, catalogue de candidats, README et matrice de validation.
Créés : présent rapport et
[résultats structurés](../research/pokedex-after-results.json).
Les fichiers de jeu et captures restent privés.

**88 tests unitaires réussis.** Le test positif utilise des octets synthétiques ;
les essais en jeu ci-dessus constituent la preuve native distincte.

La source originale conserve
`7fe9813cf5ed377e67da4d9e279a69cd63efc697b1a07c3b6f9354a85896f465`.

Prochain jalon : séparer l'interface client `GameInterface`, préparer une
livraison avec persistance et dédoublonnage, puis une boucle serveur minimale
avec ce candidat de location et un consommable. La transition du flag ne
remplace pas ces garanties.
