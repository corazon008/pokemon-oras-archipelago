# Rapport 004 — identité ROM et première lecture mémoire vérifiée

Date : 17 novembre 2026.

## Résultat

Les deux ROMs ont été identifiées par leurs **en-têtes et SHA-256**, sans se
fier aux noms de fichiers. Une lecture de 64 octets de code via le bus virtuel
d'Encore correspond exactement à la référence dérivée de chaque ROM.
Cette comparaison réussit avant et après reconnexion sur les deux éditions.

**Aucune écriture mémoire. Aucune variable de progression encore validée.**

## Structures sourcées

Référence : Encore
[`49a332221e1c9dffcc2c52f85a1765b1951c222f`](https://github.com/CasualPokePlayer/encore/tree/49a332221e1c9dffcc2c52f85a1765b1951c222f),
également référencé par le sous-module de BizHawk 2.11.1 :

- [`ncch_container.h`](https://github.com/CasualPokePlayer/encore/blob/49a332221e1c9dffcc2c52f85a1765b1951c222f/src/core/file_sys/ncch_container.h) :
  NCSD, NCCH, ExHeader et ExeFS.
- [`ncch_container.cpp`](https://github.com/CasualPokePlayer/encore/blob/49a332221e1c9dffcc2c52f85a1765b1951c222f/src/core/file_sys/ncch_container.cpp) :
  unités de 512 octets, compression LZSS arrière et chargement de `.code`.
- [`loader/ncch.cpp`](https://github.com/CasualPokePlayer/encore/blob/49a332221e1c9dffcc2c52f85a1765b1951c222f/src/core/loader/ncch.cpp#L117-L127) :
  placement du segment texte à l'adresse de l'ExHeader.

`tools/rom_identity.py` implémente une lecture limitée de ces formats avec
contrôles de bornes, sans déchiffrement ni extraction de code sur disque.
Les données de référence restent en mémoire du processus ; les résultats ne
contiennent que métadonnées et empreintes.

## Identités observées

| Champ | Rubis Oméga | Saphir Alpha |
|---|---|---|
| Program ID | `000400000011C400` | `000400000011C500` |
| Product code | `CTR-P-ECRA` | `CTR-P-ECLA` |
| Format NCCH | 2 | 2 |
| Remaster version ExHeader | 3 | 3 |
| Taille du segment texte | 4 691 460 | 4 691 452 |
| Taille stockée de `.code` | 3 039 008 | 3 039 088 |

Les [résultats structurés](../research/rom-build-results.json) consignent
également les SHA-256 complets et les références aux sorties locales.

**Attention :** le format NCCH 2 n'est pas « version du jeu 2 ». Le champ
`remaster_version = 3` n'est pas une preuve de correspondance avec une mise à
jour commerciale. La région et le numéro commercial restent non vérifiés.
Les mises à jour du profil original ne sont pas importées dans les essais.

## Preuve de lecture, sans offset supposé

1. L'ExHeader donne l'adresse virtuelle du segment texte : `0x00100000`.
2. Les deux sections `.code` sont compressées, mais leur pied LZSS indique
   un préfixe de **72 octets non compressés**.
3. Le diagnostic prend 64 octets dans ce préfixe. Aucun décompresseur complet
   ni offset de triche n'est nécessaire.
4. Python demande ces 64 octets dans `System Bus`, via l'API AP amont.
5. Le résultat est comparé octet pour octet, puis résumé par SHA-256.

Empreinte observée :

```text
92a5b3013f2d27923be3975e2046cc5e52b110822436fd5c9a9077cfb8061659
```

Cette référence est non nulle : une page non mappée renvoyant des zéros ne
pourrait pas satisfaire la comparaison.

Le préfixe est identique entre OR et AS. **Il ne distingue donc pas les éditions,
et ne prouve pas à lui seul l'identité de tout le code exécuté.** Les empreintes
ROM et en-têtes restent nécessaires ; les éventuelles mises à jour et surcharges
de code doivent être contrôlées séparément.

## Outillage et garde-fous

- Nouveau `tools/rom_identity.py`.
- Option explicite `--read-code` dans le diagnostic TCP ; le mode par défaut
  reste limité aux métadonnées.
- Adresse dérivée de la ROM, aucune option permettant une adresse arbitraire.
- Refus des références nulles, chiffrées, hors bornes ou recouvertes par la
  partie compressée.
- Refus d'un résultat RAM différent, sans tentative de correction par écriture.
- Compteur de lectures incrémenté avant envoi, y compris si la lecture échoue.
- Tests de formats basés exclusivement sur des fixtures synthétiques.

## Fichiers et tests

Créés : `tools/rom_identity.py`, `tests/test_rom_identity.py`,
`docs/research/rom-build-results.json`, présent rapport.

Modifiés : diagnostic TCP et tests associés, README principal, documentation
des outils, protocole de validation et registre des sources.

- **26 tests unitaires réussis**.
- Deux essais réels avec deux lectures chacun, séparées par une reconnexion.
- Arrêt propre de chaque instance.
- Aucun octet propriétaire brut ajouté au dépôt.

La recherche a également repéré une sauvegarde OR dans le profil fourni.
Elle n'a pas été modifiée ni importée dans ces essais.

## Suite et limites

L'accès RAM en lecture est désormais démontré sur une portion de code connue,
pas sur l'inventaire ou les flags. **BH-04 et BH-05 restent incomplets.**

Prochaine étape : préparer un profil de test isolé avec une copie de sauvegarde,
valider son chargement en jeu puis choisir une variable observable. Aucune
adresse de progression issue du plugin Gen6 n'est approuvée par ce résultat.
