# Rapport 006 — sauvegarde native rechargée et inventaire en lecture

Date : 17 novembre 2026.

## Résultat

La sauvegarde fournie par la session interactive est reconnue comme ORAS :
**58 descripteurs de blocs et 58 CRC valides**. Une copie isolée se recharge
via « Continuer » jusqu'à une partie jouable, sans savestate.

La sauvegarde source reste à l'empreinte :

```text
7fe9813cf5ed377e67da4d9e279a69cd63efc697b1a07c3b6f9354a85896f465
```

L'inventaire RAM a ensuite été comparé aux **2 960 octets complets** du bloc
inventaire de cette sauvegarde, sur deux lancements terminés proprement.
L'écran du sac affiche bien **Potion ×1**, correspondant à l'ID interne 17
et à la quantité lue.

**Aucune écriture RAM directe. Aucune livraison Archipelago encore testée.**

## Validation du fichier

`tools/oras_save.py` vérifie en lecture seule :

- Taille `0x76000` et marqueur de fin.
- 58 couples offset/longueur ORAS issus de `SaveBlockAccessor6AO`.
- IDs et longueurs des descripteurs de métadonnées.
- CRC16-CCITT de chaque bloc, initialisé à `0xFFFF`.

Les sources PKHeX de référence sont au commit
`6c9583883c7551ac74a4b74180cead249d4277b8` :
`SaveBlockAccessor6AO.cs`, `BlockInfo3DS.cs`, `Checksums.cs` et `PlayerBag6AO.cs`.
Le calcul utilise `binascii.crc_hqx` de Python, avec vecteur de référence testé.

L'import de sauvegarde exige désormais cette validation complète des blocs,
en plus des vérifications d'intégrité de copie. Les offsets de fichier ne
sont jamais assimilés à des adresses RAM.

## Adresse rejetée et recherche

Le candidat `0x08C6EC70` provenant de Gen6 CTRPF **ne correspond pas** à cet
inventaire sur le build testé. Il est consigné comme rejeté, pas corrigé par
une soustraction ou un décalage supposé.

Alternative : recherche exacte du bloc inventaire dans le tas applicatif
d'Encore, délimité par `HEAP_VADDR` et `HEAP_SIZE` dans
[`memory.h`](https://github.com/CasualPokePlayer/encore/blob/49a332221e1c9dffcc2c52f85a1765b1951c222f/src/core/memory.h).

- Domaine : `System Bus`.
- Intervalle : `0x08000000` à `0x10000000`, borne haute exclue.
- Lectures de 1 Mio, chevauchement pour les motifs à cheval sur deux blocs.
- Référence non nulle, issue d'une sauvegarde dont les CRC sont valides.
- Comparaison complète après recherche d'une ancre courte.
- Refus des références nulles et des résultats trop ambigus.
- Aucun dump global de la mémoire sur disque.

Une seule correspondance : **`0x08C6AC80`**.
La recherche s'est terminée, mais ce processus a échoué à la fermeture dans SDL.
Ce résultat seul n'est donc pas classé comme un essai entièrement réussi.
Deux lectures ciblées ultérieures, avec sorties de processus nulles, ont
confirmé la comparaison complète et l'affichage du sac.

## Portée de la vérification mémoire

Les observations concernent uniquement :

- Rubis Oméga, Program ID `000400000011C400`.
- SHA-256 ROM `d76faafacd746fdcc5ec04a60b8b82ceb9678c3ad937b374234a506c50c417e4`.
- Profil isolé, sans mise à jour ou mod repris du profil d'origine.
- Inventaire statique au chargement et dans le menu du sac.

Le fichier `tools/oras_memory_candidates.json` conserve la provenance et
**`write_allowed: false`**. Une concordance statique ne valide pas encore la
réaction à une quantité modifiée nativement, les pointeurs après changements
de carte, ni une structure de livraison atomique.

La lecture utilise ici Lua directement, pas encore le pont Python/AP pour
une variable de progression. Aucun ID Archipelago n'est créé.

## Incident SDL de l'hôte

Plusieurs essais ont atteint leurs captures mais terminé avec :

```text
System.InvalidOperationException: Collection was modified
SDL2InputAdapter.ProcessHostGamepads
```

Les logs montrent une manette HID connectée, puis sa fermeture. Le code source
BizHawk énumère une collection partagée pendant sa destruction.
Ces sorties non nulles restent des échecs dans les rapports.

Le filtre expérimental `SDL_GAMECONTROLLER_IGNORE_DEVICES_EXCEPT` n'a pas
supprimé ce périphérique ; il n'est pas retenu comme solution.
Avec `SDL_JOYSTICK_HIDAPI=0`, les deux derniers essais n'énumèrent plus cette
manette et se terminent proprement.

Le lanceur applique désormais ce hint **uniquement aux processus automatisés**.
Les sessions interactives conservent les pilotes d'entrée de l'utilisateur.
Il s'agit d'un contournement observé sur cet hôte, pas d'une correction
universelle de BizHawk. Aucun pilote système ni binaire tiers modifié.

Référence :
[SDL_HINT_JOYSTICK_HIDAPI](https://wiki.libsdl.org/SDL2/SDL_HINT_JOYSTICK_HIDAPI).

## Fichiers et tests

Créés :

- `tools/oras_save.py`, `tools/oras_memory_candidates.json`.
- `tools/bizhawk_inventory_probe.lua`.
- `tools/inventory_search.lua`, `tools/bizhawk_inventory_search.lua`.
- `tests/save_fixtures.py`, `tests/test_oras_save.py`,
  `tests/test_inventory_search.py`.
- `docs/research/native-inventory-results.json` et présent rapport.

Modifiés : sondes UI/sauvegarde/connexion, préparation de l'environnement,
tests associés et documentation.

**49 tests unitaires réussis**, sur données synthétiques. Vérifications Lua,
CRC, motifs chevauchants, refus des références nulles et environnement enfant.
Les observations en jeu sont consignées séparément dans
[`native-inventory-results.json`](../research/native-inventory-results.json).

## Jalons

- BH-01 OR : partie jouable rechargée observée ; pas validation d'une partie complète.
- BH-02 OR : sauvegarde native de l'utilisateur puis rechargement à froid vérifiés.
- BH-04 OR : concordance statique sauvegarde/RAM/UI ; variation native à tester.
- AS : validations de menu, transport et code précédentes uniquement.
- Écriture distante, application d'items, événements et serveur AP : non validés.

Suite : observer une variation native de quantité dans la copie, puis son
rechargement. La sauvegarde source de l'utilisateur reste hors des écritures.
