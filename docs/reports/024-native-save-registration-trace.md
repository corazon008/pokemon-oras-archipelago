# Rapport 024 — enregistrement natif des fichiers de sauvegarde

Date : 19 novembre 2026.

## Résultat

Les appels natifs au constructeur du contrôleur et à son enregistrement de
`main` sont maintenant **observés par hooks**, pas seulement inférés des
pointeurs après boot. Deux boots sur copies donnent les mêmes arguments :
capacité demandée **1**, compteur d'enregistrements **0 → 1**, record de
48 octets lié au manager et à `data:/main`.

**220 tests réussis.** Aucun second record, fichier AP ou SAVE créé.
Le stockage AP persistant reste non implémenté ; le bloc 47 n'est pas utilisé.

Un garde-fou supplémentaire refuse les archives multi-fichiers : le schéma
actuel de snapshot/import ne saurait préserver un futur sidecar AP.

## Distinction corrigée : compteur et capacité

Les captures du rapport 022 montraient un entier valant un à `controller+8`.
Le lookup y lit effectivement sa limite de parcours, mais le nouveau code et
les hooks précisent sa signification :

| Champ | Sens corroboré |
|---|---|
| `+0` | Backend natif |
| `+4` | Nombre de records enregistrés |
| `+8` | Capacité fournie au constructeur |
| `+12` | Pointeur vers l'allocation des records |

Dans les anciennes captures, compteur et capacité valaient tous deux un :
elles seules ne permettaient pas cette distinction. Le helper
`oras_save_lifecycle.py` utilise désormais les libellés `source_registered_count`
et `source_record_capacity`, sans modifier les anciens artefacts.

Le constructeur à `0x00115BF4` stocke son argument `r2` à `+8`, initialise
`+4` à zéro et calcule une allocation de `capacity × 48`. Le caller à
`0x00108E3C` fournit un. La routine à `0x00115A84` utilise `+4` comme index,
remplit manager/taille/chemin, puis incrémente `+4` à `0x00115BA8`.

**Ne pas enregistrer un second record dans cette allocation.** Le chemin
d'assertion visible autour de la comparaison compteur/capacité ne constitue
pas une garantie de refus exploitable par AP. Une extension doit réserver
la place avant toute écriture, pas seulement changer le compteur.

## Instrumentation native bornée

Le mode explicite `--experimental-bootstrap registration-trace` étend le
bootstrap du rapport 023 :

| Site hooké | Observation | Slot dans la nouvelle page |
|---|---|---|
| `0x00115BF4` | Entrée constructeur : `r0-r3`, `lr`, flags | `0x006AF040` |
| `0x00115A84` | Entrée register + quatre champs du contrôleur | `0x006AF080` |
| `0x00115BAC` | Avant retour register + mêmes champs | `0x006AF0C0` |

Chaque slot est borné à 64 octets, avec compteur d'appels. Les branches
d'interception sont des `B`, pas des `BL` : le `lr` d'origine est conservé.
Le logger sauvegarde/restaure registres et flags, conserve l'alignement de pile,
puis réexécute uniquement le PUSH/POP déplacé, vérifié par signature.
Le POP final original reprend le caller normal.

Les stores de log ciblent exclusivement la page RAM ajoutée ; les PUSH/POP
emploient aussi temporairement la pile. Aucun pointeur de sauvegarde n'est
remplacé. Aucun setter ni nouvel appel d'enregistrement n'est introduit.
Le parser exige exactement un passage à chacun des trois sites, les callers
attendus, des pointeurs alignés bornés et la transition `0/1 → 1/1`.

La partie ajoutée en text occupe 304 octets à `0x00579610`, bootstrap compris.
ExHeader text passe à `0x479740` ; allocation BSS identique au rapport 023.
IPS de 353 octets ; ExHeader privé de 2 048 octets. Pas de `code.bin` complet,
pas de ROM réécrite ni de données propriétaires distribuées.

## Deux boots et reconnexions réels

Build OR exact et seed du rapport 023 ; horloge de copie
`2026-11-18T18:36:36`, vitesse 400 %.

- Premier essai : `local/oras/profiles/oras-connector-oqa0xnn9`.
- Répétition avec captures brutes :
  `local/oras/profiles/oras-connector-yiejbj3i`.

Observations identiques :

| Élément | Valeur |
|---|---|
| Contrôleur | `0x08CDCFB8` |
| Heap passé au constructeur | `0x08803000` |
| Retour du caller constructeur | `0x00108E48` |
| Retour du caller register | `0x00108E58` |
| Nom UTF-16 `main` dans le code vérifié | `0x001091F4` |
| Manager argument puis stocké dans le record | `0x08C6A9A8` |
| Backend avant/après | `0x08CDD008` |
| Pointeur de record avant/après | `0x08CEDA80` |
| Taille/chemin relus dans le record | `0x76000`, `data:/main` |
| Compteur/capacité avant → après | `0/1 → 1/1` |

Chaque boot : deux connexions, 20 READ soumis dont deux sautés, quatre GUARD,
inventaire et EventWork entiers conformes, sortie propre 0.
Code ajouté, marqueur, slots et record relus après reconnexion ; captures
identiques. La répétition conserve sous `registration-trace/connection-*`
trois slots et un record bruts par connexion. Le premier essai conserve les
résultats décodés et hashes, pas ces captures brutes.

Les quatre snapshots pré/post, `main` et métadonnées sont vérifiés inchangés.
Hash de `main` :
`f7906a7ec9f61e3f9ce8e13510d35269b3b0cb99ff1fe909c6de066fa68e1887`.
Zéro WRITE AP/Lua signifie zéro requête transport : **les hooks écrivent leurs
logs RAM**, et le jeu effectue son initialisation normale.

Ce sont des observations de points d'exécution ciblés, pas une trace complète
d'instructions ni une preuve du contexte sûr d'une livraison.

## Archive existante et récupération

Les [sources Encore ArchiveFormatInfo](https://github.com/CasualPokePlayer/encore/blob/49a332221e1c9dffcc2c52f85a1765b1951c222f/src/core/file_sys/archive_backend.h)
définissent les champs des métadonnées. La source existante décrit notamment
un fichier et un répertoire. Modifier la seule capacité RAM n'établirait ni
la compatibilité de cet ancien format, ni le chargement d'un second fichier
absent. Aucun test à capacité deux n'a été exécuté.

Le [backend SD SaveData](https://github.com/CasualPokePlayer/encore/blob/49a332221e1c9dffcc2c52f85a1765b1951c222f/src/core/file_sys/archive_source_sd_savedata.cpp)
supprime le répertoire de sauvegarde lors de `Format`. **Ne pas utiliser ce
chemin comme migration en place.** Aucun formatage n'est invoqué ici.
Les quotas effectifs et garanties de commit ne sont pas déduits des champs.

Autre limite concrète : `snapshot_save` et `seed_archive` ne conservent que
`main` et les métadonnées. Ils refusent maintenant tout autre fichier ou
sous-répertoire dans l'archive, avant publication/import. La validation d'un
snapshot refuse aussi un sidecar non manifesté. Aucun fichier inattendu n'est
effacé. Il faudra un nouveau schéma complet avant de créer un ledger séparé.

## Fichiers, tests et suite

Créés : `tools/oras_save_registration.py`, tests synthétiques, présent rapport
et [résultats structurés](../research/native-save-registration-results.json).
Modifiés : bootstrap, lanceurs, analyse lifecycle, snapshots, tests et docs.

Les 220 tests couvrent les hooks/callers, slots incomplets ou altérés, transition
compteur/capacité, record invalide, captures conservées en cas d'échec, et refus
d'omettre un fichier AP supplémentaire. Les anciens modes bootstrap restent
inchangés et opt-in ; source ROM, profils originaux et connecteur fourni intacts.

Prochain travail concret : définir un schéma de snapshot/import multi-fichiers,
puis un objet AP natif et une migration d'archive non destructive sur copie.
Ensuite seulement, tester reset/load/SAVE d'un payload AP non nul. Deux fichiers
enregistrés ne constitueraient toujours pas une transaction atomique item/index ;
la récupération d'un fichier partiel reste à traiter. Livraison live bloquée.
