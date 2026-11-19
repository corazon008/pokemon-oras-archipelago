# Rapport 021 — sauvegarde native instrumentée et état intermédiaire invalide

Date : 19 novembre 2026.

## Résultat

Une action SAVE native est déclenchée par boutons sur **nouvelle copie isolée**,
sans écriture directe de mémoire. 1 357 frames consécutives sont observées.
Le message « Corazon saved the game. » est visible. Le nouveau fichier possède
58 CRC valides et se recharge à froid avec deux lectures AP conformes.

**Résultat important : le fichier backing `main` expose un état intermédiaire
CRC-invalide**, avec des payloads modifiés et l'ancien footer. La validité
initiale/finale ne suffit donc pas pour présumer une écriture atomique.
Ce n'est pas un test de crash ni de perte d'alimentation.

La sauvegarde d'origine, la source seed et ses métadonnées restent inchangées.
Le contrôle clavier automatique a suffi ; aucune progression manuelle nécessaire.

## Préflight refusé et diagnostic du changement de date

Les deux premiers essais sur copies fraîches échouent **avant tout signal SAVE** :
le bloc EventWork complet diffère de la référence. Le premier boote dans le sac,
le second dans l'overworld. L'hypothèse initiale d'une différence liée seulement
au menu n'est donc pas retenue.

Un diagnostic conserve ensuite le bloc réel en privé et constate un seul octet :
`EventWork+0x490`, valeur sauvegardée 0, valeur observée 1. Le même résultat
apparaît dans un contrôle en lecture sur le profil existant.

`0x490` est le début de la **queue non documentée**, après les 3 328 flags
validés. Ce n'est **pas** un nouveau flag 3328. Aucun masque n'est ajouté, aucun
octet n'est réécrit et aucune sémantique de progression n'est attribuée à ce champ.

Le fichier de référence a un ResumeTime du 18 novembre, relevé dans le bloc 3
selon
[GameTime6.cs](https://github.com/kwsch/PKHeX/blob/6c9583883c7551ac74a4b74180cead249d4277b8/PKHeX.Core/Saves/Substructures/Gen6/GameTime6.cs) :
`2026-11-18T18:36:36`. Les contrôles réels ont lieu le 19 novembre.

Une copie fraîche est alors configurée explicitement avec :

```text
UseRealTime = false
InitialTime = 2026-11-18T18:36:36
```

Ces options sont recoupées avec
[Encore.ISettable.cs](https://github.com/TASEmulators/BizHawk/blob/bdddf4a58aa1a022afb11dc73294a81a5aa7bbd5/src/BizHawk.Emulation.Cores/Consoles/Nintendo/3DS/Encore.ISettable.cs).
**Seul le `config.ini` de la nouvelle copie est modifié**, pas l'horloge hôte
ni le réglage temps réel du profil original.

Sous ce contrôle, la comparaison complète EventWork passe de nouveau, avant
et après reconnexion. C'est une corrélation avec le contexte temporel, pas une
preuve de la signification du champ. Une référence byte-for-byte n'est pas
automatiquement stable entre dates ; le comportement live reste à définir.

## Instrumentation et portée

`--observe-native-save` exige une nouvelle copie `--seed-save`, refuse
`--session` et l'expérience Potion. Il implique les contrôles de code, inventaire,
EventWork, manager et record de fichier, puis deux connexions AP strictes.
Le fichier signal autorisant les boutons n'est créé qu'après ces contrôles.

La macro part maintenant de l'overworld validé, entre dans le sac, puis ouvre
le dialogue SAVE et confirme. L'observateur échantillonne à chaque frame :

- Racine du manager et table des 58 pointeurs, imposées stables.
- Métadonnées, inventaire, EventWork et objet réservé complet.
- Record `data:/main` de 36 octets.
- Fichier backing `main`, ouvert en lecture binaire uniquement.

Les références initiales et les tailles doivent correspondre. Pointeurs/dispatchs
sélectionnés restent gardés ; un changement inattendu, une lecture courte ou une
discontinuité de frames interrompt la validation. Plafond : 4 000 ticks.
Les buffers ne sont capturés qu'en cas de changement ; un TSV conserve chaque
frame et les versions actives.

La sonde ne fait aucun appel WRITE, aucune invocation directe de méthode ARM,
aucun hook, breakpoint ou patch. Les boutons font naturellement exécuter le
code de sauvegarde du jeu ; les PCs exacts de ses instructions ne sont pas tracés.

## Observation temporelle réelle

Copie durable :
`local/oras/profiles/oras-connector-fq_i14ny/`.
Sonde : `native-save/timeline.tsv`, 1 357 lignes, frames 4170 à 5526.
Sept plages par frame : **9 499 lectures mémoire**.

| Frame | Observation |
|---:|---|
| 4170 | Références initiales ; fichier seed, 58 CRC valides |
| 5429 | Métadonnées RAM mises à jour |
| 5430 | Nouveau contenu partiel visible dans `main` ; ancien footer ; CRC invalide |
| 5431 | Fichier final visible ; 58 CRC valides |
| 5526 | Dernier échantillon ; message de sauvegarde réussie visible |

Le fichier intermédiaire diffère du seed dans les blocs 3, 4, 6, 10, 11 et 17.
Son footer entier est encore celui du seed ; le validateur rejette le checksum
du bloc 3. Le fichier final diffère dans ces blocs et le bloc 44.

Les métadonnées RAM finales correspondent au footer final ; les payloads RAM
échantillonnés inventaire, EventWork et réservé correspondent au nouveau fichier.
Ce n'est pas une comparaison indépendante des 58 payloads RAM.
Racine/table du manager, inventaire, EventWork et objet réservé n'ont qu'une
version pendant la fenêtre observée. L'inventaire reste Potion ×1, le payload
réservé reste nul, Pokédex 2722 reste faux et work 130 reste 2.

SHA-256 :

- Source inchangée :
  `f7906a7ec9f61e3f9ce8e13510d35269b3b0cb99ff1fe909c6de066fa68e1887`.
- Fichier intermédiaire rejeté :
  `7cd9fa9c306da77da1f276a23432434eb65fabfa922983d8a8f5a93729eb63a5`.
- Nouveau fichier valide :
  `7bbd987cc202dfbea36585ca610729571284c65c23300f88524fbc62d80a1653`.

**Ne pas traiter les fichiers `native-save/file-*.bin` comme des backups.**
Ils peuvent être incomplets ou invalides ; seuls les snapshots publiés après
validation CRC et avec métadonnées d'archive sont des copies restaurables.

La lecture hôte peut voir le cache du filesystem ; elle ne prouve pas un état
durable après coupure. Le polling ajoute de la latence et peut manquer des
transitions intraframe. L'état invalide effectivement observé interdit néanmoins
de supposer une visibilité atomique du fichier backing.

## Cold reload et conservation des échecs

`connector-attempt-zo71abqw`, sous la nouvelle copie, relance le jeu sans SAVE :
préfixe, inventaire, EventWork, objet réservé, manager, CRC et reconnexion
concordent avec le nouveau fichier. Sa configuration de temps contrôlé est
conservée ; ce résultat n'est pas un test de redémarrage à une autre date.

| Essai | Statut | Action native SAVE |
|---|---|---|
| `oras-connector-awdbsl_1` | Échec de garde, sac initial | Non |
| `oras-connector-_ootf6g7` | Échec de garde, overworld initial | Non |
| `oras-connector-4wbg7sv8` | Diagnostic copie, queue `0x490` différente | Non |
| Original : `connector-attempt-3v2cgzan` | Même diagnostic en lecture | Non |
| `oras-connector-fq_i14ny` | Sauvegarde instrumentée réussie | Oui, sur copie |
| Copie : `connector-attempt-zo71abqw` | Cold reload réussi | Non |

Les échecs ne sont pas reclassés. Tous les processus sortent proprement, avec
zéro écriture mémoire soumise. Les douze snapshots pré/post sont vérifiés.
Le contrôle dans le profil original peut mettre à jour les caches et journaux
usuels d'Encore ; sa sauvegarde et ses métadonnées d'archive restent identiques.
Les [preuves structurées](../research/native-save-observation-results.json)
distinguent ces cas.

## Fichiers et tests

- Créés : observateur Lua, builder/analyseur Python, tests d'observation,
  rapport et résultats JSON.
- Modifiés : lanceur du connecteur, macro post-UI, diagnostics EventWork,
  tests de transport et documentation.
- **195 tests unitaires réussis** : signal d'autorisation, bornes de frames,
  lectures courtes, références stables, journaux, fichiers partiels, CRC,
  conservation des contrôles de progression et horloge explicite sur copie.
- Fixtures synthétiques uniquement ; tous les binaires et captures de jeu
  restent privés sous `local/oras/`.

## Limites et prochaine étape

Ce succès ne réserve aucun stockage AP. Un payload réservé resté nul ne prouve
pas la persistance de données AP non nulles ou l'absence de reset natif.
Aucun item n'est délivré, aucun index installé, aucune transaction item/index
ni reprise après crash démontrée.

La fenêtre backing CRC-invalide devra entrer dans les exigences de reprise :
ne jamais accuser réception d'une persistance sur la seule base d'un message UI
ou d'une copie RAM. Prochaine étape : définir une stratégie explicite de stockage
et de récupération, puis ses tests sur copies. Aucun besoin de faire progresser
manuellement le joueur pour cette recherche.
