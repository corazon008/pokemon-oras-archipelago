# Audit technique initial — priorité BizHawk

Date : 17 novembre 2026.

Ce document conserve les conclusions de la première recherche statique.
Les essais ultérieurs sont consignés dans le
[rapport 002](../reports/002-bizhawk-capabilities.md).

## 1. Portée et niveau de preuve

Cet audit couvre les mécanismes visibles dans les sources, pas une intégration
ORAS exécutée. Les commits et chemins examinés sont figés dans
[`sources.json`](sources.json). Une lecture ciblée ne constitue pas un audit
exhaustif de chaque dépôt.

Trois niveaux sont séparés :

- **Observé dans les sources** : comportement implémenté en amont.
- **Déduction à tester** : conséquence probable de ces sources.
- **Validé en jeu** : exige un résultat expérimental reproductible.

**Aucun résultat ORAS n'appartient encore au troisième niveau.** Aucun nombre
présent dans une source externe n'est promu en offset ou flag ORAS approuvé.

## 2. Archipelago : architecture et protocole

Sources : [`network protocol.md`][ap-protocol],
[`CommonClient.py`][ap-common], [`world api.md`][ap-world].

- Le World construit items, locations, régions, règles et conditions de victoire.
  Les données de génération et de patch sont distinctes du client d'exécution.
- Le client se connecte par WebSocket : `RoomInfo`, `Connect`, puis `Connected`
  ou `ConnectionRefused`. Les messages sont des listes JSON de commandes.
- Les checks utilisent `LocationChecks`. `Connected` et `RoomUpdate` exposent
  l'état des locations côté serveur.
- `ReceivedItems.index` est une position dans l'historique reçu, pas un identifiant
  d'objet. Deux exemplaires du même consommable doivent rester deux livraisons.
- Un paquet d'index zéro remplace l'historique réseau local ; il ne signifie pas
  « appliquer tous les objets à nouveau ».
- En cas de décalage d'index, `CommonClient` demande `Sync` et renvoie les checks
  locaux connus. La progression d'application dans le jeu reste à gérer.
- Le serveur ne confirme pas que l'objet a été sauvegardé par ORAS.

**Réutilisation technique retenue :** infrastructure `CommonClient` /
`BizHawkClientContext`, plutôt qu'une nouvelle implémentation WebSocket.
Vérifier les licences applicables avant toute copie de code.

## 3. Pokémon Émeraude officiel

Sources : [`World`][emerald-world], [`client.py`][emerald-client],
[`rom.py`][emerald-rom].

### Mécanismes utiles

- World modulaire avec options, catégories de locations, règles et validation
  de certaines combinaisons d'options.
- ROM patchée identifiée par un marqueur/version, pas seulement par son titre.
- Authentification du slot à partir de données de génération embarquées.
- Lecture des pointeurs de sauvegarde et gardes contrôlant leur stabilité et
  l'état du jeu.
- Détection par flags et données persistantes, pas seulement par carte.
- Boîte de réception dédiée : le client lit le compteur reçu et l'occupation
  de la file, puis écrit le prochain item avec son numéro de séquence.
- Patch procédural `.apemerald` : patch de base BSDiff, puis tokens de génération.

### Limites de transposition

Les blocs de sauvegarde, callbacks overworld, domaines GBA, symboles et offsets
ne s'appliquent pas à ORAS. Le client Émeraude suppose une ROM préalablement
modifiée avec un support Archipelago côté jeu. Une boîte de réception équivalente
n'existe pas automatiquement dans ORAS.

Le code Python observé ne suffit pas à prouver l'atomicité ni la durabilité de
l'application effectuée par le patch de jeu. Cette partie exige une étude
supplémentaire du code du patch et des essais.

**À reprendre :** séparation World/client/jeu, validation de compatibilité,
garde des pointeurs, file explicite et logique badge/CS séparée.
**À réimplémenter :** toute interaction avec le moteur Gen VI.

## 4. Pokémon Noir/Blanc communautaire

### Provenance réellement examinée

Projet identifié : [BlastSlimey/PokemonBWAP][bw-repo], release
[0.4.5][bw-release]. Le dépôt consulté contient seulement un README.
Le code étudié provient de `pokemon_bw.apworld`, archive ZIP de la release :

```text
SHA-256 8a400df90fbe2b2ca8a9e129f996b491de3b88f1c8ef146dc3a5dbe7c7bddfcd
```

L'empreinte téléchargée correspond à celle annoncée par l'API GitHub.
L'archive a été inspectée sans charger son World ni exécuter son Python.
Les chemins suivants sont internes à cette archive ; ils correspondent au
package qui serait installé sous `worlds/pokemon_bw/`.

### Connecteur et client

- `bizhawk_client.py` dérive de `BizHawkClient`, avec système `NDS`.
- Le client utilise `Main RAM`, vérifie le jeu/version patchée et récupère
  le nom de slot dans des données préparées par le patch.
- `client/setup.py` récupère la base des données de sauvegarde depuis un
  pointeur exposé par le jeu modifié.
- `client/locations.py` lit les flags en blocs et les associe aux locations
  manquantes. Les checks Pokédex utilisent des structures distinctes.
- `game_watcher` envoie les `LocationChecks`, applique les objets et vérifie
  l'objectif.

**Lua :** aucun fichier `.lua` dans l'archive 0.4.5 examinée. Le guide
`docs/setup_en.md` demande le **connecteur générique Archipelago**
`data/lua/connector_bizhawk_generic.lua`. Il ne faut donc pas inventer un
connecteur Lua spécifique à Noir/Blanc.

### Application et persistance des items

`client/items.py` :

1. Lit un compteur d'objets reçus dans les variables du jeu.
2. Parcourt la suite de `ctx.items_received`.
3. Résout les IDs Archipelago vers les IDs internes.
4. Modifie poches, badges ou flags selon la catégorie.
5. Écrit le compteur après les applications réussies.

Les slots de poche examinés contiennent un ID et une quantité sur quatre
octets. `guarded_write` protège une écriture contre une valeur devenue obsolète.
`reload_key_items` restaure certains objets importants sans en multiplier les
exemplaires.

**Limite à ne pas copier :** écriture de l'objet et écriture du compteur sont
séparées. Une rupture entre elles constitue une fenêtre de rejeu à examiner.
Une garde mémoire n'est ni une transaction disque ni un accusé de sauvegarde.
Ce mécanisme ne démontre donc pas à lui seul une livraison exactement une fois
face aux crashs et retours de sauvegarde.

### Patch ROM

`rom.py` et `patch/procedures/base_patch.py` montrent :

- Patchs `.apblack`, `.apwhite` et `.apbw`, avec manifeste/version et procédures.
- Chargement d'une ROM personnelle via `ndspy.NintendoDSRom`.
- Modification d'archives NARC, décompression/recompression ARM9 et overlays.
- Extension ARM7 et branches propres aux versions Noir/Blanc.
- Insertion du nom de joueur et de la version du patch dans l'en-tête.

`patch/procedures/write_scripts.py` désassemble et réassemble des scripts
Gen V, avec options et données de slot. Ni ce format de script, ni ces hooks,
ni ces adresses ne sont transférables à la 3DS.

### Roadblocks

`docs/roadblocks.md` associe des barrages physiques à des objets précis :
colis, objets clés, badges et CS. Les patchs changent effectivement scripts
et accès ; ils ne se limitent pas à des règles Python.

Conséquence ORAS : pour chaque barrage, documenter ensemble :
condition logique, condition native, modification éventuelle et test en jeu.
Modifier seulement la logique Archipelago laisserait des accès incohérents.

`docs/rom changes.md` annonce lui-même un état ancien (0.3.11) : ne pas le traiter
comme inventaire exhaustif et actuel de la release 0.4.5.

### Réutilisation

Les patterns sont utiles, mais aucune licence n'était déclarée par l'API du
dépôt. **Aucune copie de code Noir/Blanc engagée** sans clarification des droits.
Le transport générique peut être étudié directement dans Archipelago.

## 5. BizHawk / Encore : faisabilité statique

Référence de départ : **BizHawk 2.11.1**. Le README de cette release liste
la 3DS avec Encore. Cela ne prouve pas la compatibilité ORAS.

### Domaines et espace d'adressage

[`Encore.IMemoryDomains.cs`][bh-memory], lignes 19–77 :

- `FCRAM`, `VRAM`, `DSP RAM`.
- `N3DS Extra RAM` conditionnel au modèle émulé.
- `System Bus`, little-endian, espace virtuel de 32 bits, annoncé inscriptible.
- Les pages virtuelles sont résolues via `Encore_GetPagePointer`.

**Choix pour les futurs essais :** `System Bus` pour les adresses virtuelles du
processus, après identification et vérification de leur mapping. Ne pas convertir
une adresse de plugin en offset FCRAM par simple soustraction supposée.

### Pièges vérifiables dans les sources

1. **Pages non mappées :** les lectures du bus peuvent retourner zéro et les
   écritures être ignorées sans erreur explicite.
2. **Taille 4 Gio :** le domaine déclare `1L << 32`, mais
   [`MemoryApi.GetMemoryDomainSize`][bh-api] convertit sa taille en `uint`.
   Une taille Lua de zéro est donc attendue en conversion non vérifiée ;
   comportement effectif à mesurer. Ne pas conclure que le domaine est vide.
3. **Nom incorrect :** la documentation de l'API de taille prévoit un retour
   sur le domaine courant si le nom n'existe pas. Énumérer et vérifier les noms.
4. **Index Lua :** `getmemorydomainlist()` construit une table indexée depuis zéro,
   tandis que `read_bytes_as_array()` produit une table indexée depuis un.
   Un parcours `ipairs` seul ne convient pas à l'inventaire des domaines.
5. **Savestates :** [`Encore.IStatable.cs`][bh-state] recâble les pointeurs
   natifs des domaines après chargement. Les pointeurs et caches propres au
   client ORAS devront eux aussi être revalidés.

### Transport existant

[`connector_bizhawk_generic.lua`][ap-lua] fournit TCP local, JSON par ligne,
octets encodés en base64, `SYSTEM`, `READ`, `WRITE`, `GUARD`, `LOCK` et `UNLOCK`.
Le client Python fournit `read`, `guarded_read` et `guarded_write`.

Le connecteur sert sur `localhost`, ports 43055 à 43060 inclus dans la version
étudiée. Ce protocole local est distinct du WebSocket Archipelago.
Sa couche de requêtes ne contient pas de restriction explicite à la DS/GBA.

**Déduction :** le connecteur générique est un candidat sérieux pour Encore.
**Non validé :** fonctionnement effectif de LuaSocket, identification système,
mémoire ORAS, écritures, performances et persistance.

`WRITE_RESPONSE` confirme le traitement de la requête Lua, pas sa durabilité
dans la sauvegarde ; avec une page non mappée, il peut même manquer la
confirmation d'une modification RAM. Une relecture et une observation du jeu
restent obligatoires.

## 6. Gen6 CTRPluginFramework

Sources : [`README`][gen6-readme], [`Helpers.cpp`][gen6-helpers],
[`Main.cpp`][gen6-main], [`PKHeX.cpp`][gen6-items].

- Détection distincte de Rubis Oméga et Saphir Alpha.
- Helpers séparant choix de série XY/ORAS et choix entre deux éditions.
- `IsUpdateSupported` compare la version ORAS à la valeur interne **7820**.
  La correspondance avec une version commerciale et la région du jeu local
  reste à établir ; aucune équivalence n'est supposée.
- Dans `PatchProcess`, le retour de cette fonction est ignoré. Ne pas prendre
  cette vérification comme garantie que les écritures incompatibles sont bloquées.
- Les fonctions d'inventaire écrivent des entrées de quatre octets, avec ID
  et quantité. Plusieurs fonctions réécrivent toute une poche ou débloquent
  tous les objets : ce ne sont pas des primitives sûres de livraison Archipelago.
- Les commentaires de `Main.cpp` demandent encore des tests pour certaines
  combinaisons matériel/édition et signalent un support émulateur incomplet.

Les adresses sont des **pistes sourcées**, pas des résultats vérifiés sur le jeu
de l'utilisateur. Aucun offset n'est copié dans le projet.

Le dépôt annonce GPL-3.0 et une chaîne devkitPro/CTRPF/3gxtool.
La faisabilité TCP sur console et le comportement sur émulateur ne sont pas
démontrés par ces fonctions. Aucun prototype plugin n'est engagé.

## 7. pk3DS, Luma3DS et structures de sauvegarde

### pk3DS

[`GARCReference.cs`][pk3ds-garc] distingue les tables XY et AO, dont données
de rencontres, dresseurs et objets. [`Script.cs`][pk3ds-script] décrit
en-tête, pointeurs et instructions compressées des scripts 3DS.
Cela confirme la nécessité d'une chaîne de patch spécifique Gen VI.

L'outil ne constitue pas un connecteur d'exécution Archipelago. Le README
consulté exige .NET 10/C# 14 pour son interface Windows Forms ; ce n'est pas
une dépendance à installer d'office pour le futur client Python.

### Luma3DS

[`patcher.c`][luma-patcher] implémente LayeredFS sous
`/luma/titles/<title-id>/romfs` et traite des patchs de code.
LayeredFS est une redirection de fichiers, pas un transport d'items.

[`3gx.h`][luma-3gx] définit l'en-tête `3GX$0002`, segments, métadonnées,
cibles et compatibilité console/émulateur.
[`file_loader.c`][luma-loader] recherche des plugins propres au titre ou un
plugin par défaut. Un indicateur de compatibilité de format ne démontre pas
que le plugin ni Encore prennent en charge un scénario donné.

Ces mécanismes restent des références de secours. Le chargement de patchs
RomFS/code **dans Encore** doit être vérifié séparément avant d'en dépendre.

### PKHeX : corroboration du format sauvegarde

[`SAV6AO`][pkhex-sav] expose inventaire, badges et événements.
[`SaveBlockAccessor6AO`][pkhex-blocks] sépare blocs inventaire et EventWork.
[`EventWork6`][pkhex-events] distingue variables 16 bits et flags.

**Attention : ces structures décrivent un fichier de sauvegarde déchiffré.**
Elles ne donnent ni une base RAM, ni une correspondance des flags avec chaque
événement d'ORAS, ni un emplacement libre pour un compteur Archipelago.
Ne jamais réutiliser un bloc marqué « unused » sans preuve indépendante.

## 8. Matrice de transposition

| Sujet | Émeraude | Noir/Blanc | ORAS : décision |
|---|---|---|---|
| World Python | API officielle et logique Hoenn Gen III | World et options Gen V | API réutilisable, graphe ORAS à reconstruire |
| Transport émulateur | Connecteur BizHawk générique | Même connecteur, pas de Lua dédié dans la release | Privilégier ce connecteur avec Encore |
| Détection | Flags/pointeurs GBA, données du patch | Flags/Pokédex DS, pointeur préparé | Définir et tester chaque preuve Gen VI |
| Livraison | File dédiée et compteur dans les données du jeu | Écriture poches/badges puis compteur | Choisir un mécanisme transactionnel vérifiable |
| Patch | BSDiff de base et tokens GBA | NARC, overlays ARM9, extension ARM7 | GARC/scripts et code 3DS à étudier |
| Adresses | Symboles/mémoire GBA | `Main RAM` DS et offsets du patch | Adresses virtuelles Encore, jamais offsets DS |
| Roadblocks | Options/règles et patch spécifique | Scripts et objets modifiés | Règles et comportement en jeu doivent correspondre |
| Sauvegarde | Layout et support AP propres au patch | Variables Gen V utilisées par le patch | Layout Gen VI et support AP à identifier |
| Version double | Sans objet pour ce World | Adaptations Noir/Blanc explicites | Profils OR/AS distincts, même s'ils partagent du code |

Les ressemblances d'entrées d'inventaire ne rendent ni les moteurs, ni les
scripts, ni les offsets interchangeables entre générations V et VI.

## 9. Décisions et inconnues bloquantes

Architecture cible, sans implémentation prématurée :

```text
APWorld Python → données de seed / patch
Serveur Archipelago ↔ BizHawkClientContext ↔ GameInterface
                                             ↕
                                  adaptateur BizHawk Python
                                             ↕ TCP local
                                  connecteur Lua générique
                                             ↕
                                         Encore / ORAS
```

- Garder `GameInterface` indépendante des règles du World et des domaines
  mémoire. Réutiliser le client AP existant, pas écrire un protocole concurrent.
- Profils jeu explicites : édition, région, mise à jour et empreintes pertinentes.
  Profil inconnu : refus d'écriture.
- Distinguer historique réseau, application RAM et validation par sauvegarde.
- Un journal externe seul ne résout pas le retour à une sauvegarde plus ancienne.
  Un index de jeu doit correspondre à l'état effectivement sauvegardé ; son
  emplacement sûr et sa mise à jour ne sont pas encore identifiés.
- Pour les consommables, la présence dans l'inventaire ne prouve pas la
  livraison : l'objet peut avoir été utilisé. La déduplication doit suivre
  la livraison, pas seulement l'ID d'objet.
- Ne pas réserver d'IDs AP définitifs, choisir d'événement concret ou activer
  d'écriture tant que leurs preuves ne sont pas établies.

Restent à valider : lancement des deux éditions sur Encore, API en exécution,
structures RAM, événement précis, écriture sûre, persistance et support de patch
des récompenses natives. L'audit statique ne lève pas ces barrières.

[ap-protocol]: https://github.com/ArchipelagoMW/Archipelago/blob/cf08efe5b1c132bf966ae810c007b8268d47b7b0/docs/network%20protocol.md
[ap-common]: https://github.com/ArchipelagoMW/Archipelago/blob/cf08efe5b1c132bf966ae810c007b8268d47b7b0/CommonClient.py#L1034-L1098
[ap-world]: https://github.com/ArchipelagoMW/Archipelago/blob/cf08efe5b1c132bf966ae810c007b8268d47b7b0/docs/world%20api.md
[emerald-world]: https://github.com/ArchipelagoMW/Archipelago/blob/cf08efe5b1c132bf966ae810c007b8268d47b7b0/worlds/pokemon_emerald/__init__.py
[emerald-client]: https://github.com/ArchipelagoMW/Archipelago/blob/cf08efe5b1c132bf966ae810c007b8268d47b7b0/worlds/pokemon_emerald/client.py#L164-L279
[emerald-rom]: https://github.com/ArchipelagoMW/Archipelago/blob/cf08efe5b1c132bf966ae810c007b8268d47b7b0/worlds/pokemon_emerald/rom.py#L98-L114
[bw-repo]: https://github.com/BlastSlimey/PokemonBWAP/tree/885e7dbeb4a0dda3993107b10ef15b3700b06f7b
[bw-release]: https://github.com/BlastSlimey/PokemonBWAP/releases/tag/0.4.5
[bh-memory]: https://github.com/TASEmulators/BizHawk/blob/bdddf4a58aa1a022afb11dc73294a81a5aa7bbd5/src/BizHawk.Emulation.Cores/Consoles/Nintendo/3DS/Encore.IMemoryDomains.cs
[bh-api]: https://github.com/TASEmulators/BizHawk/blob/bdddf4a58aa1a022afb11dc73294a81a5aa7bbd5/src/BizHawk.Client.Common/Api/Classes/MemoryApi.cs#L192-L200
[bh-state]: https://github.com/TASEmulators/BizHawk/blob/bdddf4a58aa1a022afb11dc73294a81a5aa7bbd5/src/BizHawk.Emulation.Cores/Consoles/Nintendo/3DS/Encore.IStatable.cs#L49-L87
[ap-lua]: https://github.com/ArchipelagoMW/Archipelago/blob/cf08efe5b1c132bf966ae810c007b8268d47b7b0/data/lua/connector_bizhawk_generic.lua
[gen6-readme]: https://github.com/biometrix76/Gen6CTRPluginFramework/blob/25ca82746c23ad194c772a2b3266bf5042e3a370/README.md
[gen6-helpers]: https://github.com/biometrix76/Gen6CTRPluginFramework/blob/25ca82746c23ad194c772a2b3266bf5042e3a370/Sources/Helpers.cpp#L31-L71
[gen6-main]: https://github.com/biometrix76/Gen6CTRPluginFramework/blob/25ca82746c23ad194c772a2b3266bf5042e3a370/Sources/Main.cpp#L149-L160
[gen6-items]: https://github.com/biometrix76/Gen6CTRPluginFramework/blob/25ca82746c23ad194c772a2b3266bf5042e3a370/Sources/PKHeX.cpp#L182-L339
[pk3ds-garc]: https://github.com/kwsch/pk3DS/blob/6daaca934ca2284a73ab743bf89c848c57cd9de1/pk3DS.Core/Game/GARCReference.cs
[pk3ds-script]: https://github.com/kwsch/pk3DS/blob/6daaca934ca2284a73ab743bf89c848c57cd9de1/pk3DS.Core/Structures/Script.cs
[luma-patcher]: https://github.com/LumaTeam/Luma3DS/blob/1441535d222002353b79d290b6200ceab2e32cb0/sysmodules/loader/source/patcher.c
[luma-3gx]: https://github.com/LumaTeam/Luma3DS/blob/1441535d222002353b79d290b6200ceab2e32cb0/sysmodules/rosalina/include/plugin/3gx.h
[luma-loader]: https://github.com/LumaTeam/Luma3DS/blob/1441535d222002353b79d290b6200ceab2e32cb0/sysmodules/rosalina/source/plugin/file_loader.c
[pkhex-sav]: https://github.com/kwsch/PKHeX/blob/6c9583883c7551ac74a4b74180cead249d4277b8/PKHeX.Core/Saves/SAV6AO.cs
[pkhex-blocks]: https://github.com/kwsch/PKHeX/blob/6c9583883c7551ac74a4b74180cead249d4277b8/PKHeX.Core/Saves/Access/SaveBlockAccessor6AO.cs
[pkhex-events]: https://github.com/kwsch/PKHeX/blob/6c9583883c7551ac74a4b74180cead249d4277b8/PKHeX.Core/Saves/Substructures/Gen6/EventWork6.cs
