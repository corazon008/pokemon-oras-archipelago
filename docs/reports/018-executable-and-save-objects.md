# Rapport 018 — exécutable et objets de sauvegarde

Date : 18 novembre 2026.

## Résultat

Sur le build OR vérifié, le candidat du bloc 47 est localisé en RAM :
objet `System Bus:0x08C88034`, payload `0x08C88038`, longueur `0x7D0`.
L'en-tête non nul lève l'ambiguïté d'une recherche de 2 000 octets nuls.
Un seul motif complet est trouvé sur le heap documenté, lors de **deux
démarrages à froid** du même profil durable.

Le second essai relit également les 2 004 octets via l'API AP avant/après
reconnexion. Les références de code, les dispatchs et les en-têtes connus
inventaire/EventWork concordent. **Aucun WRITE ; sauvegarde entière inchangée.**

Ce résultat identifie un objet candidat, **pas un espace appropriable par AP**.
Le nom statique est `savedata::ReservedSaveData`, et une callback présente un
chemin compatible avec une remise à zéro. Son calendrier d'exécution reste
inconnu. Aucun index n'est installé.

## Identité et décompression

ROM personnelle : SHA-256
`d76faafacd746fdcc5ec04a60b8b82ceb9678c3ad937b374234a506c50c417e4`,
Program ID `000400000011C400`.

`oras_code_research.py` décompresse BLZ en mémoire, avec bornes et rejet des
références invalides. Layout et mapping sont recoupés avec Encore
`49a332221e1c9dffcc2c52f85a1765b1951c222f`, fonctions de décompression de
`ncch_container.cpp` et `LoadExec` de `loader/ncch.cpp`.

- `.code` stocké : 3 039 008 octets ; développé : 5 439 488 octets.
- SHA-256 développé :
  `d587c98ac5c4dedacf9be4baf2d6b7d10169e6a63f8bc35b132002cc27bc1a37`.
- Mapping ExHeader, et non base plate présumée :

| Segment | Offset dans l'image | Adresse virtuelle |
|---|---:|---:|
| text | 0 | `0x00100000` |
| ro | 4 694 016 | `0x0057A000` |
| data | 5 160 960 | `0x005EC000` |

Aucun exécutable complet extrait sur disque ; aucune modification de ROM.
Le petit plan de références contient néanmoins des octets propriétaires :
il reste sous `local/oras/`, ignoré par Git, et ne doit pas être distribué.

## Ce que les recherches statiques établissent — et n'établissent pas

La recherche des 58 tailles à plusieurs strides ne trouve aucun tableau complet.
Un reconnaisseur A32 borné trouve des séquences retournant 51 des 52 longueurs
distinctes ; la longueur 760 du bloc 35 n'est pas reconnue. Ni tableau complet
de pointeurs de providers, ni tableau avec une entrée non reconnue n'est trouvé
aux strides examinés.

Cela **ne prouve pas l'absence de table native**. Le reconnaisseur accepte
seulement certaines constantes A32 et jusqu'à trois opérations suivies d'un
retour ; ni limites de fonctions, ni accessibilité, ni code Thumb ne sont prouvés.

Pour les blocs sélectionnés, une référence de provider en ro mène à six
pointeurs text alignés. Le slot `+0x0C` contient exactement un getter
`ADD r0,r0,#4 ; BX LR` ; le slot `+0x10` retourne la longueur attendue.
La sélection exige un candidat unique pour chacun :

| Bloc | Dispatch | Provider de taille | Getter de données |
|---|---|---|---|
| 1 — inventaire | `0x005E09C4` | `0x00463354` | `0x00463888` |
| 19 — EventWork | `0x005DF40C` | `0x00406B24` | `0x00406F30` |
| 47 — candidat réservé | `0x005E074C` | `0x0045E13C` | `0x0045E180` |

Les en-têtes prédits à payload moins quatre valent réellement ces dispatchs
pour l'inventaire (`0x08C6AC7C`) et EventWork (`0x08C7DAE8`).
Cette corroboration n'autorise pas à généraliser le layout à tous les objets.

### Noms et pistes de cycle natif — analyse statique seulement

Les pointeurs précédant les dispatchs mènent à des structures dont le deuxième
mot pointe vers des noms de types encodés. `c++filt -t` les décode :

| Objet | Structure référencée | Chaîne | Nom décodé |
|---|---|---|---|
| Inventaire | `0x005C4DFC` | `0x005D35D3` | `savedata::MYITEM` |
| EventWork | `0x005C42A8` | `0x005D19FA` | `field::EventWork` |
| Bloc 47 | `0x005C4CFC` | `0x005D33A7` | `savedata::ReservedSaveData` |

Ces chaînes sont relevées dans l'exécutable exact, pas relues en RAM.
Quelques fragments A32 privés ont aussi été décodés par `llvm-mc` :

- Callback du bloc 47 au slot `+0x14`, `0x0045E144` : appelle les getters
  de données et de taille, puis branche à `0x0015EBCC`.
- Cette cible met `r2` à zéro et comporte des stores nuls : piste de zero-fill.
- Slot `+0x08`, `0x0045E188` : fixe `r2=2000`, `r0=this+4`, puis branche
  à `0x00300B28`, où figurent lectures source et écritures destination.

On ne les appelle pas « initialisation », « chargement » ou « sérialisation
vérifiés » : aucun breakpoint ni historique d'exécution ne démontre encore
quand ces chemins sont utilisés. Aucun hook ou patch n'est ajouté.

## Protocole de recherche réel

Le plan privé est construit uniquement après validation des 58 CRC et du hash
ROM exact, puis :

1. Boot natif du profil durable existant, sans action de sauvegarde.
2. Vérification du domaine exact `System Bus` et de son comportement 4 Gio.
3. Comparaison de 13 plages : préfixe, tables, getters/providers, littéral de
   taille EventWork et deux en-têtes d'objets déjà connus.
4. Recherche de `dispatch47 little-endian + payload47 du fichier` :
   2 004 octets, dont l'en-tête non nul.
5. Lecture du heap Encore `[0x08000000, 0x10000000)` par chunks de 1 Mio
   avec recouvrement des frontières ; relecture complète de chaque match.
6. Exigence d'un match unique et aligné ; aucun résultat choisi arbitrairement.
7. Installation du shim strict, puis contrôles AP et reconnexion.
   Dans la version finale, relecture de l'objet complet sur chaque connexion.
8. Arrêt propre, comparaison du fichier entier et snapshots CRC-validés.

Une divergence de référence, lecture courte, absence de domaine ou ambiguïté
fait échouer la sonde. Le compteur Lua est distinct des requêtes réseau AP.
Le marqueur et le hash du plan sont requis avant les relectures AP.

## Deux essais conservés hors `/tmp`

Profil : `local/oras/profiles/oras-save-kkvwuxa5/`.

| Essai | Lectures Lua | READ AP soumis | Relectures objet AP | WRITE | Résultat |
|---|---:|---:|---:|---:|---|
| `connector-attempt-6ku_6_7e` | 142 | 8 | 0 | 0 | Match unique, sortie 0 |
| `connector-attempt-95bt79jr` | 142 | 10 | 2 | 0 | Même match à froid, reconnexion, sortie 0 |

Les 142 lectures Lua comprennent 13 références, 128 chunks et une relecture.
Chaque essai soumet quatre GUARD, dont deux gardes de domaine absent qui bloquent
deux READ ; les comptes READ incluent ces demandes sautées.
Les deux relectures AP de l'objet ont le SHA-256 :
`9d109ba46bdb2827bbd61ac7255a2c25d0c33d68d308666d2ea8bbe0dae1f688`.

Le SHA-256 de `main` reste
`f7906a7ec9f61e3f9ce8e13510d35269b3b0cb99ff1fe909c6de066fa68e1887`.
Backups avant/après de chaque essai et métadonnées Encore conservés ; leurs
chemins et résultats sont dans les
[preuves structurées](../research/save-object-results.json).
Les bundles AP figés restent intacts.

## Tests et fichiers

**161 tests unitaires réussis**, soit 33 supplémentaires depuis le rapport 017 :
BLZ synthétique, mapping inverse, constantes A32, tables complètes/partielles,
dispatchs incorrects/ambigus, plan privé, hash, domaine, référence incorrecte,
lecture courte, match à cheval sur une frontière et relectures AP incohérentes.
Ces fixtures ne contiennent aucun code de jeu.

- Créés : `tools/oras_code_research.py`, `tools/oras_save_objects.py`,
  `tools/bizhawk_save_object_probe.lua`, deux fichiers de tests, rapport et JSON.
- Modifiés : métadonnées ROM, wrapper et lanceur du connecteur, tests stricts,
  documentation et catalogue de candidats en lecture seule.

## Limites et suite

Une région CRC-couverte et nulle n'est pas un registre AP. La correspondance
actuelle ne prouve ni la persistance d'un contenu arbitraire non nul, ni l'absence
de remise à zéro ou d'autres utilisateurs. La liaison effective de cet objet
au bloc 47 lors de la sérialisation doit encore être tracée.

Aucune adresse AS n'est déduite de ces résultats OR. Pas de stockage réservé,
de contexte sûr d'écriture, de transaction item/index, de livraison live, ni
de boucle serveur. Aucune progression manuelle supplémentaire nécessaire ici.

Prochaine étape : suivre les appels natifs de création/reset et de sauvegarde,
puis déterminer si un enregistrement explicitement possédé par un patch est
nécessaire. **Ne rien écrire dans le candidat sur la seule base de ce rapport.**
