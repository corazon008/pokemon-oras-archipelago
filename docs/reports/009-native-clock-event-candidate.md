# Rapport 009 — candidat d'événement natif : horloge et dialogue à l'étage

Date : 17 novembre 2026.

## Résultat et limite

Le bloc **EventWork** d'OR a été retrouvé par recherche exacte, puis observé
avant, pendant et après une séquence native : interaction avec l'horloge de la
chambre et première conversation avec maman à l'étage.

Le mot **`work[130]` passe de 2 à 3 à la fin de cette séquence**. Il reste à 2
lors de plusieurs témoins négatifs. La valeur 3 est sauvegardée nativement,
validée sur 58 CRC, puis relue après démarrage d'un nouveau processus sans
savestate.

Il s'agit d'un **candidat de progression persistant dans ce scénario**, pas
encore d'une location Archipelago approuvée. Sa permanence lors de la suite du
scénario reste à vérifier : aucune règle `>= 3`, aucun bit « horloge réglée »
ni aucune sémantique pour des valeurs non observées ne sont inventés.

**Aucune écriture mémoire. Source utilisateur conservée.**

## Structure : fichier et mémoire distingués

Sources PKHeX au commit `6c9583883c7551ac74a4b74180cead249d4277b8` :

- `SaveBlockAccessor6AO.cs` : bloc 19, fichier offset `0x14A00`, longueur `0x504`.
- `EventWork6.cs` : 376 mots uint16 little-endian, puis 3 328 flags.
- `FlagUtil.cs` : numérotation des bits du poids faible au poids fort.
- Fin des flags à `0x490` ; les 116 derniers octets du bloc restent sans
  sémantique attribuée par cet outillage.

Les ressources `flags_oras_en.txt` et `const_oras_en.txt` ont été consultées.
Elles n'apportent pas de nom pour ce mot 130 : l'interprétation locale vient
des observations, pas d'une constante présentée comme documentée en amont.

La recherche RAM utilise le bloc complet d'une sauvegarde dont les 58 CRC sont
valides, dans le tas Encore documenté `[0x08000000, 0x10000000)`.
128 lectures de 1 Mio, avec chevauchement ; une seule correspondance :

```text
System Bus:0x08C7DAEC — 1 284 octets
```

Ce résultat n'est **pas** obtenu en ajoutant une distance à l'inventaire.
Le champ observé est ensuite calculé depuis le début du bloc retrouvé :

```text
index décimal 130 × 2 = offset 0x104
System Bus:0x08C7DBF0 — uint16 little-endian
```

Le SHA-256 ROM et le Program ID sont les mêmes que dans le rapport 008 ;
aucun résultat n'est transposé à AS ou à un autre build.

## Témoins négatifs et transition

Essai `/tmp/opencode/oras-save-pmlcj2zw/attempt-178wch3s` :

| Étape native observée | work[130] | Interprétation bornée |
|---|---:|---|
| Partie chargée, avant escalier | 2 | Référence complète concordante |
| Chambre atteinte, sans interaction horloge | 2 | Changer de carte ne suffit pas |
| Près de l'horloge, avant A | 2 | Approcher l'objet ne suffit pas |
| Horloge/dialogue avec maman encore en cours | 2 | Lancement de la scène ne suffit pas |
| Séquence terminée, contrôle rendu | 3 | Transition candidate |
| Appuis A supplémentaires | 3 | Pas de nouvelle transition observée |

Les autres variations sont conservées dans les résultats mais **non promues** :

- Flag 102 déjà modifié à l'entrée de la chambre.
- Mot 17 déjà modifié près de l'horloge avant interaction.
- Flag 610 modifié pendant la conversation puis revenu à sa valeur initiale.

Ce candidat ne repose donc pas uniquement sur la carte, l'affichage d'un menu
ou le lancement d'un dialogue. Les captures montrent notamment « The clock on
the wall isn't moving... », puis la conversation avec maman, puis le retour
au contrôle du joueur.

Les premiers essais de navigation ou d'avancement du texte n'atteignaient pas
la fin de la séquence. Leur lecture pouvait être techniquement terminée sans
que l'événement soit réalisé. `complete: true` signifie ici que la sonde et ses
lectures ont terminé, **pas que le candidat est devenu vrai**.

## Sauvegarde et rechargement

Le message de sauvegarde native est observé dans `step-58.png`. Le fichier de
travail a 58 CRC valides :

```text
main SHA-256 :
1c933f1cf0be502bda4748135bf4ec1301e6deb0c9670acafb59bcef0312434a

EventWork SHA-256 :
5fa7ebd0d52f0e6eb0f72084be6b576a050a2968e805f682d55e56cedb094947
```

Une nouvelle copie est créée depuis ce fichier et son archive Encore.
L'essai `/tmp/opencode/oras-save-ev5_8vq1/attempt-wwboxv66` recharge la chambre
dans un nouveau processus. Deux lectures du bloc complet sont identiques à
la sauvegarde, avec `work[130] = 3`. Aucun savestate, aucune écriture RAM.

Le profil utilisateur original conserve :
`7fe9813cf5ed377e67da4d9e279a69cd63efc697b1a07c3b6f9354a85896f465`.
La copie à l'état 3 est conservée séparément pour comparer avec une extension
de jeu manuelle : descendre, terminer la scène TV, sauvegarder et fermer.
Cette extension n'est pas encore comptée comme un résultat dans ce rapport.

## Outillage et reproduction

Créés :

- `tools/oras_events.py` : extraction CRC-validée, lecture bornée des mots et
  flags, comparaison séparant la fin inconnue du bloc.
- `tools/bizhawk_event_probe.lua` : recherche ou lectures après étapes UI,
  sans API d'écriture.
- `tests/test_oras_events.py`.
- [Plan natif reproductible](../research/clock-event-plan.json).
- [Résultats structurés](../research/clock-event-results.json) et présent rapport.

Modifiés : lanceur de sauvegarde, tests Lua, catalogue de candidats, références
de sources et documentation.

Recherche depuis une copie de la sauvegarde initiale :

```sh
python3 tools/run_bizhawk_save_probe.py \
  --rom "/chemin/vers/OR-verifie.3ds" --session /tmp/opencode/oras-save-COPIE \
  --scan-event-work --speed 400 --timeout 180 \
  --steps '1800:-,2:A,600:-,2:A,600:-,2:A,600:-'
```

Observation : `--read-event-work --event-sample-steps 7,12,16,30,44,48`,
avec les étapes assemblées depuis le plan JSON. Ne pas appliquer ce plan à
une position différente ou à une partie ayant déjà avancé.

Comparaison de deux sauvegardes sans émulateur :

```sh
python3 tools/oras_events.py /copie/avant/main /copie/apres/main
```

Les indices de mots et de flags sont décimaux et distincts. Le JSON de
comparaison exprime chaque variation relativement au fichier validé **avant
le lancement**, pas relativement à l'échantillon précédent. Les données RAM
brutes et captures restent privées.

## Tests et suite

**74 tests unitaires réussis** : CRC, index/bornes, séparation mots/flags,
ordre des bits, remise à zéro, fin inconnue du bloc, lectures aux étapes,
journal avant lecture, rejet d'une lecture tronquée et absence d'écriture.
Les tests synthétiques ne valident pas les sémantiques du jeu.

BH-08 dispose désormais d'un candidat avec témoins négatifs et rechargement.
Il reste à vérifier la suite du scénario, puis à relire ce signal par l'API AP
avant d'approuver une règle de location. Pas de `LocationChecks`, serveur,
index persistant, livraison idempotente ni APWorld dans cette phase.
