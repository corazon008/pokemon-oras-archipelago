# Rapport 012 — témoin avant réception du Pokédex

Date : 17 novembre 2026.

## Résultat

L'utilisateur indique avoir obtenu le starter et vaincu son rival. Il sauvegarde
avant de retourner au laboratoire de Seko/Birch. Le rechargement observé montre
le personnage sur la Route 103 ; l'issue du combat n'est pas validée séparément.

**58 CRC valides. Le candidat « Pokédex obtenu », flag décimal 2722, est faux
dans la sauvegarde et dans les deux lectures API AP avant/après reconnexion.**

Le fichier n'est pas modifié par la sonde. Aucun WRITE envoyé, aucun check
de location ni item Archipelago.

## Checkpoint préservé

Pas de nouveau profil ni de copie d'émulateur. Après vérification qu'aucun
EmuHawk de ce profil ne tournait, seuls `main` et son archive Encore de
16 octets sont copiés, avec refus d'écrasement et vérification des empreintes :

```text
/tmp/opencode/oras-save-ev5_8vq1/checkpoints/before-pokedex-koagt8zq/
  00000001/main
  00000001.metadata
  checkpoint.json
```

Empreintes :

```text
main :
3b4e66edc55fbc46e0cab2e10d287f40d9082232e0a67cc244efc96f650a2bff

EventWork :
906d1070714746c9563861e6d7999f021e4be72aaa7667f3d62ead63d4604c5d
```

L'import utilise `seed_archive` existant : validation des 58 CRC, copie exclusive
et contrôle de `main` et de ses métadonnées. Le checkpoint brut reste privé.
Le profil de jeu peut maintenant évoluer sans perdre la référence avant événement.

## Candidat, pas encore une preuve de transition

Source : `flags_oras_en.txt` de PKHeX au commit
`6c9583883c7551ac74a4b74180cead249d4277b8`, entrée `2722`, « Pokédex Obtained ».
Le layout de `EventWork6` et l'ordre des bits de `FlagUtil` sont déjà documentés.

La sonde lit le **bloc EventWork complet**, à l'adresse vérifiée pour le build
OR exact, et le compare à la sauvegarde CRC-valide avant d'en décoder ce bit.
Elle n'invente pas une nouvelle adresse à partir d'une autre édition.
La simple observation du bit faux ne prouve pas encore sa sémantique dans ce
build : il faut l'action native, le témoin après et un redémarrage.

Le résultat contient `production_location_approved: false`.

## Essai API AP

Preuve : `/tmp/opencode/oras-save-ev5_8vq1/connector-attempt-a63bs3x1`.

- Même profil existant, sans réimport.
- Démarrage natif, pas de savestate.
- Deux connexions, chacune avec lectures du code, de l'inventaire et d'EventWork.
- Bloc complet identique à la sauvegarde sur les deux connexions.
- Flag 2722 : faux, faux.
- 6 READ, aucune écriture, sortie 0, sauvegarde inchangée.
- L'inventaire contient Potion ×11 ; cette quantité est seulement observée,
  pas attribuée au pont AP.

Le profil original initial conserve son SHA-256
`7fe9813cf5ed377e67da4d9e279a69cd63efc697b1a07c3b6f9354a85896f465`.

## Fichiers et tests

- `tools/oras_connector_events.py` : observation en lecture du candidat Pokédex.
- `tests/test_connector_events.py` : bit exact, témoin voisin, mauvais build,
  longueur incorrecte et absence d'approbation de location.
- [Résultats structurés](../research/pokedex-before-results.json), présent rapport,
  catalogue de recherche et documentation.

**87 tests unitaires réussis.** Les tests synthétiques ne prouvent pas l'événement
natif ; le flag positif et sa persistance restent non validés.

## Suite manuelle

Le même profil est rouvert à vitesse normale, clavier seul.
Retour vers Oldale, Route 101, Bourg-en-Vol/Littleroot, puis laboratoire.
Recevoir le **Pokédex de Birch**, sauvegarder dans le menu du jeu et fermer.
Ne pas confondre ce cadeau avec le DexNav donné par le rival.

Après fermeture : préserver le nouveau fichier, comparer au checkpoint, vérifier
la transition du bit et ses voisins, puis relire le bloc après redémarrage et
reconnexion AP. Aucun envoi de location avant cette validation.
