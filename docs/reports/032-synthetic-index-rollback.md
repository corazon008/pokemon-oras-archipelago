# Rapport 032 — compteur synthétique et rollback cohérent

**Le SAVE natif fait passer le compteur de test de 0 à 1.** La paire à
l'index 1 redémarre dans un nouveau processus sans writer. La paire à
l'index 0, issue du même essai, est également cohérente et valide en
elle-même ; l'ancre post-SAVE épinglée la refuse **avant lancement**
comme rollback.

Ce compteur n'est pas un index d'item AP. Aucun item ni EventWork modifié,
aucun replay, et toujours aucune autorisation de livraison live.

## Format et vérification

Variante distincte de `aptest` sur la ROM OR et le checkpoint du
[rapport 031](031-native-footer-sidecar-binding.md), à 512 octets :

| Octets | Donnée |
| --- | --- |
| 0–7 | Signature `ORASIDX1` |
| 8–15 | Identifiant aléatoire non nul de l'essai, inchangé au SAVE |
| 16–19 | Compteur synthétique little-endian, limité à 0 ou 1 |
| 20–507 | Footer de `main`, 488 octets |
| 508–511 | Tag fixe `TIDX` |

L'hôte crée uniquement le seed à l'index 0 sur la copie. Après le retour
zéro du writer de `main`, le wrapper natif copie le footer et remplace
le mot à l'offset 16 par 1, puis écrit `aptest`. Il n'y a pas de deuxième
incrément prévu. Le retour du writer, la transition, l'identifiant et les
octets entiers de RAM/disque sont recoupés. Les metadata d'archive,
l'inventaire et EventWork restent inchangés.

`sidecar-index-reload` exige un snapshot v2 exact OR choisi explicitement
comme ancre, à l'index 1. Le seed et l'ancre sont vérifiés séparément
(`main`, CRC, footer, sidecar, archive). Une paire d'un autre essai est
refusée ; une paire au même index peut également être refusée si ses
empreintes diffèrent. La vérification a lieu avant le lancement, sur
la copie, puis après fermeture. L'ancre reste un **snapshot de confiance
choisi par l'opérateur**, pas une identification automatique du dernier
SAVE ni une signature d'authenticité.

## Essais

| Profil privé | Résultat |
| --- | --- |
| `oras-connector-euh_g34k` | SAVE natif `0 → 1`, 39 READ, zéro WRITE du connecteur, 58 CRC valides. |
| `oras-connector-7t3uuszb` | Seed pré-SAVE/ancien cohérent, même identifiant, refus avant EmuHawk, zéro READ/WRITE. |
| `oras-connector-0gcqfqcw` | Cold reload épinglé à l'index 1, writer absent, 28 READ et deux connexions identiques ; archive inchangée. |

Snapshots source de la comparaison : `before-connector-tvms_pl7`,
`after-connector-vyoxg3v7`. Snapshots du cold reload :
`before-connector-ozfwvrak`, `after-connector-vww7_gpd`.
Les quatre sont complets et CRC-valides. ROM et sauvegarde d'origine
inchangées. [Preuves structurées](../research/synthetic-index-results.json).

Contrôle complémentaire : dans un journal SQLite temporaire, une preuve
AP **factice** épingle les empreintes de la paire à l'index 1. Présenter
la vraie paire pré-SAVE, même en fournissant un index courant fabriqué
pour correspondre à la file, bloque l'application suivante avant tout
appel d'écriture. Le snapshot local utilisé par le lanceur n'est pas un
adaptateur du journal ; ce contrôle SQLite est indépendant et hors ligne.

**268 tests réussis.** Couverture : mélange, vieux checkpoint cohérent,
même index mais archives différentes, autre identifiant, corruption, ancre
absente/invalide, writer borné à l'index synthétique.

## Limites

Un rollback simultané de la référence de confiance **et** du jeu peut
encore passer. Le footer ne prouve pas l'identité d'un joueur, la causalité
du SAVE ou l'atomicité entre fichiers. Aucun nouvel essai de coupure dans
cette phase. Le prochain verrou est de produire une preuve conjointe d'une
mutation d'inventaire et de son index, avec reprise sûre si la paire
n'est pas publiée entièrement.
