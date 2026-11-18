# Rapport 020 — références de fichier et boucles de sérialisation

Date : 18 novembre 2026.

## Résultat

Le manager OR est relié en mémoire à un enregistrement contenant son pointeur,
la taille `0x76000` et le chemin UTF-16 `data:/main`. Une référence à ce record
est ensuite retrouvée ; son contexte contient un candidat typé
`gfl::fs::BackupSystem`.

Des boucles natives compatibles avec lecture/écriture des blocs sont
identifiées dans l'exécutable, ainsi que cinq callers directs. Leurs accès
count/index/data/size et le calcul d'alignement expliquent **les 58 offsets
réguliers**, le footer `0x75E00` et la taille complète `0x76000`.

**Zéro WRITE, aucun SAVE déclenché, sauvegarde et métadonnées inchangées.**
La présence du code et des structures ne prouve pas encore leur exécution lors
d'une sauvegarde, les garanties du filesystem, ni une transaction item/index.
La progression manuelle du joueur n'est pas nécessaire pour ces contrôles.

## Limite du debugger existant

Sources BizHawk figées à `bdddf4a58aa1a022afb11dc73294a81a5aa7bbd5` :
[Encore.cs](https://github.com/TASEmulators/BizHawk/blob/bdddf4a58aa1a022afb11dc73294a81a5aa7bbd5/src/BizHawk.Emulation.Cores/Consoles/Nintendo/3DS/Encore.cs)
et [LibEncore.cs](https://github.com/TASEmulators/BizHawk/blob/bdddf4a58aa1a022afb11dc73294a81a5aa7bbd5/src/BizHawk.Emulation.Cores/Consoles/Nintendo/3DS/LibEncore.cs).

Le bridge managé expose notamment frames, snapshots et pointeurs mémoire,
mais pas d'API de registres CPU ou de callbacks d'exécution mémoire. Aucun
breakpoint natif n'est donc prétendu validé via ce bridge. Cela n'exclut pas
un autre transport de debugging ; aucun changement d'émulateur ou de core
n'est engagé ici.

Les lectures mémoire et l'analyse statique restent possibles sans gameplay.
Elles ne doivent pas être renommées « trace d'exécution ».

## Graphe de pointeurs observé

Recherche bornée du mot non nul `0x08C6A9A8` dans le heap documenté :

| Référence | Observation dans le contexte relu |
|---|---|
| `0x08C6A770` | Pointeur vers le manager, puis plusieurs autres pointeurs |
| `0x08CEDA80` | Manager à `+0`, taille `0x76000` à `+8`, chemin à `+16` |

Le deuxième record est retenu par **taille et chemin exacts**, pas par simple
voisinage d'un objet supposé lié au save.
Une deuxième recherche de son adresse trouve `0x08CDCFC4`.
Le préfixe non typé à `0x08CDCFB8` contient :

- À `+0` : pointeur `0x08CDD008`.
- À `+0x0C` : pointeur du record `0x08CEDA80`.
- À `0x08CDD008` : dispatch `0x005DD3B4`, dont le nom statique décodé est
  `gfl::fs::BackupSystem`.

Un autre dispatch est visible à `0x08CEDA18` :
`0x005DD2F0`, nom `gfl::fs::BackupFile`.
**Il précède le record dans le heap ; cela ne démontre pas qu'ils appartiennent
à une même allocation.** Le scanner conserve des candidats de types, pas des
propriétaires déduits par proximité.

Les liens sont relus dans les contextes capturés. Les noms proviennent de
pointeurs de type résolus dans l'exécutable exact, et non d'appels aux méthodes
natives ou d'une lecture directe des chaînes RTTI en RAM.

## Boucles de fichier — preuve statique bornée

Dans le même exécutable OR vérifié :

| Boucle | Entrée | Callers directs A32 repérés |
|---|---|---|
| Lecture candidate | `0x0045DACC` | `0x00124D7C`, `0x0045D3D4` |
| Écriture candidate | `0x0045DC38` | `0x00124E50`, `0x00124F34`, `0x0045D23C` |

Des fragments sélectionnés sont décodés en privé avec LLVM. Le nouvel outil
`oras_save_serialization.py` contrôle huit séquences load/BLX de slots,
refuse les gaps non supportés ou qui écrasent le registre de méthode, et
cherche les branches directes dans le segment text seulement.
Ce contrôle syntaxique ne prouve pas à lui seul la provenance d'un registre
ou l'accessibilité d'un caller.

Les boucles présentent :

1. Count et alignement par slots `+0x08` et `+0x10` du manager.
2. Objet indexé via `+0x0C`, puis taille et données de l'objet.
3. Positionnement du backend puis transfert du payload courant.
4. Contrôle d'erreur/longueur ; avance par `(taille+alignement-1)&~(alignement-1)`.
5. Fermeture du backend après la boucle.

La branche d'écriture charge la méthode backend `+0x48` à `0x0045DD40`
et appelle à `0x0045DD4C`. Son argument `r3` vaut un pour la dernière entrée,
zéro sinon. **Sa signification exacte — flush, commit ou autre — n'est pas
établie ici.** Aucun drapeau final n'est transformé en garantie d'atomicité.

Le provider de métadonnées `0x004630C4` retourne 488, alignés sur 512.
Avec les tailles de blocs documentées, la récurrence reproduit tous les offsets :

| Entrée | Offset | Payload | Place alignée |
|---|---:|---:|---:|
| Inventaire 1 | `0x400` | 2 960 | 3 072 |
| Réservé 47 | `0x20600` | 2 000 | 2 048 |
| Métadonnées 58 | `0x75E00` | 488 | 512 |

Total : `0x76000`. Les tailles d'entrée du calcul viennent du layout connu ;
aucune méthode du jeu n'est invoquée pour les obtenir, notamment pas le provider
non pur du bloc 35. Les 57 providers purs et les descripteurs réels du rapport
019 apportent la corroboration indépendante disponible.

Le helper de calcul de taille voisin comporte aussi une branche spéciale
pour les IDs 56/57 selon un paramètre. Elle n'est pas appliquée au calcul de
layout complet ci-dessus ; on ne généralise pas ce résultat à tous ses modes.

## Trois essais conservés

Profil durable : `local/oras/profiles/oras-save-kkvwuxa5/`.

| Essai | Scope ajouté | Lectures Lua |
|---|---|---:|
| `connector-attempt-y1myc1dt` | Références directes du manager | 350 |
| `connector-attempt-e0q6fcp3` | Référence du record, contexte 320 octets | 479 |
| `connector-attempt-0btdata9` | Contexte parent 512 octets et inspection de types | 479 |

Les trois essais terminent correctement, retrouvent les mêmes références et
conservent le SHA-256 de `main` :
`f7906a7ec9f61e3f9ce8e13510d35269b3b0cb99ff1fe909c6de066fa68e1887`.
Les six snapshots pré/post et leurs métadonnées sont validés indépendamment.

Le dernier total comprend 30 références, 128 chunks de recherche d'objet, une
relecture de l'objet, 61 lectures manager, 128 chunks et deux contextes de
backrefs, puis 128 chunks et un contexte de referrer.
Chaque essai ajoute 10 READ AP dont deux sautés, quatre GUARD, et deux
relectures complètes de l'objet réservé avant/après reconnexion.
**Aucune écriture mémoire et aucune sauvegarde native déclenchée.**

Les captures de contextes restent sous `objects/`, privées et ignorées par Git.
Les [résultats structurés](../research/save-serialization-results.json)
ne contiennent que métadonnées, observations et limites.

## Fichiers et tests

- Créés : `tools/oras_save_references.py`, `tools/oras_save_serialization.py`,
  leurs tests, rapport et résultats JSON.
- Modifiés : sonde Lua, builder du plan, lanceur AP, tests d'objets et documentation.
- **186 tests unitaires réussis** : scans et contextes synthétiques, liens
  invalides, tailles/chemins, candidats RTTI, alignement, overflow, branches
  A32/BLX, slots et clobbers.
- Les fixtures ne contiennent aucun extrait de ROM ou sauvegarde réelle.

## Suite et intervention du joueur

Le code de transfert séquentiel n'est pas une preuve de transaction durable :
les garanties du backend et le chemin d'erreur doivent encore être établis.
La liaison temporelle à l'action SAVE reste non observée. Aucun enregistrement
exclusif AP, hook ou index de livraison n'est installé.

Prochaine observation utile : une **sauvegarde native instrumentée sur copie
isolée**, sans modification de mémoire, avec échantillons avant/pendant/après.
Les macros clavier existantes pourront probablement la déclencher. Une
progression vers un badge ou le Pokédex n'accélère pas ce blocage. Si une action
manuelle précise devient utile, la demander seulement après préparation
des captures et backups ; ne pas faire rejouer l'utilisateur à l'aveugle.
