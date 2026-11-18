# Rapport 019 — manager natif de sauvegarde

Date : 18 novembre 2026.

## Résultat

Le candidat du rapport 018 est corroboré comme **objet du slot natif 47** :
la table du manager, les tailles reconnues et les descripteurs du footer
concordent avec le layout de fichier PKHeX sur le build OR exact.

Le manager expose **59 entrées** : 58 blocs réguliers et une entrée spéciale
de métadonnées, index 58. La table régulière contient 58 pointeurs, pas 59.
Les boucles natives de reset et de construction des descripteurs sont
identifiées statiquement. Leur calendrier réel d'exécution n'est pas tracé.

**Trois démarrages en lecture seule, zéro WRITE, fichier inchangé et six
snapshots durables valides.** Un essai est classé échec : un contrôle ajouté
attendait à tort 58 entrées totales. Le dernier démarrage valide le modèle
corrigé, sans reclasser l'échec.

## Méthode statique bornée

Identités inchangées :

- ROM OR SHA-256 :
  `d76faafacd746fdcc5ec04a60b8b82ceb9678c3ad937b374234a506c50c417e4`.
- `.code` développé :
  `d587c98ac5c4dedacf9be4baf2d6b7d10169e6a63f8bc35b132002cc27bc1a37`.

Une référence littérale au dispatch réservé mène à un fragment qui place
l'en-tête de l'objet et appelle un chemin compatible avec du zero-fill.
Plus loin, le constructeur remplit une table de pointeurs.

`tools/oras_save_manager.py` analyse seulement le fragment droit
`[0x00116AC4, 0x00116EDC)`. Il propage des constantes et des offsets affines
relatifs à `r4`, base hypothétique du manager :

- ADD/SUB, MOV, ORR, certains shifts et transferts de mots.
- Littéraux PC résolus par les segments ExHeader.
- Chargements de pile ou de mémoire ordinaire laissés inconnus.
- Instructions conditionnelles, appels, writeback ou formes non supportées
  refusés ; aucune interprétation optimiste d'une instruction inconnue.

Il ne s'agit **pas d'un émulateur ARM**, ni d'une exécution des méthodes du jeu.
54 des 58 offsets de slots sont dérivés. Les slots 53, 55, 56 et 57 dépendent
de registres inconnus dans ce fragment ; aucune valeur n'est inventée.

Un accesseur indépendant, à `0x00465284`, confirme le calcul
`base + 0x722D0 + index*4`. Il traite l'index 58 à part via `[base+4]`.

## Structures corroborées en RAM

| Structure | Adresse/valeur observée |
|---|---|
| Base du manager | `0x08C6A9A8` |
| Dispatch du manager | `0x005E0B24` |
| Table de 58 pointeurs réguliers | `0x08CDCC78` |
| Objet de métadonnées | `0x08CDCD90` |
| Slot 1, offset `0x2D4` | `0x08C6AC7C`, inventaire |
| Slot 19, offset `0x13140` | `0x08C7DAE8`, EventWork |
| Slot 47, offset `0x1D68C` | `0x08C88034`, réservé |

La base calculée indépendamment depuis inventaire et EventWork est identique.
Tous les 54 pointeurs prédits concordent avec la table réellement lue.
Les 58 pointeurs sont alignés dans le heap et leurs en-têtes pointent vers des
dispatchs contenant des pointeurs de code dans les segments de l'exécutable.
57 providers correspondent au reconnaisseur de constantes et aux tailles du
fichier ; aucun provider reconnu ne retourne une autre taille.
Les méthodes sélectionnées sont comparées à la ROM dans les références Lua ;
ceci ne signifie pas que chaque instruction des 58 méthodes a été relue en RAM.

Les 488 octets à `metadata_object+8` correspondent exactement au début du
footer sauvegardé. Les 58 descripteurs longueur/ID/**CRC** concordent.
Ce résultat renforce la liaison structurelle du slot 47 au layout sauvegardé,
mais ne prouve pas encore le chemin d'écriture d'un contenu modifié.

### Exception importante : provider du bloc 35

`0x00460140` contient un prologue, deux appels aux helpers `0x001602B8` et
`0x00160380`, puis un retour terminal de la constante 760.
Le reconnaisseur strict ne le considère donc pas comme un simple getter pur.
Cette exclusion est intentionnelle ; on n'appelle aucune méthode native pour
obtenir sa taille. Les effets des helpers ne sont pas établis.

## Chemins de cycle natif identifiés — statique, pas temporel

Le dispatch du manager contient notamment :

| Slot du dispatch | Méthode | Observation |
|---|---|---|
| `+0x08` | `0x004EA998` | Retourne 59 |
| `+0x0C` | `0x00465284` | Accès indexé ; index 58 spécial |
| `+0x14` | `0x004654F4` | Boucle sur 58 objets, appelle leur slot `+0x14`, puis métadonnées |
| `+0x1C` | `0x004652D4` | Utilise tailles/données et remplit longueur, ID et checksum |

Le constructeur comporte une boucle comparable à `0x00116EE0`.
La callback du bloc 47 au slot `+0x14`, `0x0045E144`, obtient données et taille
et branche vers la routine compatible avec un zero-fill `0x0015EBCC`.

Le constructeur de descripteurs appelle `0x00173F84`, avec seed `0xFFFF`,
écrit les champs de huit octets par bloc et le marqueur `0x42454546`.
La concordance des CRC du fichier corrobore ce rôle. Aucun appel ni breakpoint
ne prouve encore à quelle étape d'une sauvegarde ou d'un reset cette méthode
est exécutée. Les callers virtuels et le chemin d'écriture du fichier restent
à tracer. Ne pas assimiler présence d'une routine de reset à preuve qu'elle
est exécutée à chaque chargement ou sauvegarde.

## Essais réels et erreur de modèle

Profil durable existant :
`local/oras/profiles/oras-save-kkvwuxa5/`.

| Essai | Références | Lectures Lua | READ AP soumis | Statut |
|---|---:|---:|---:|---|
| `connector-attempt-c0kvk0wy` | 28 | 218 | 10 | Réussite du contrôle initial |
| `connector-attempt-1azetwvs` | 30 | 220 | 10 | Échec : 58 entrées totales attendues à tort |
| `connector-attempt-hyhq63qw` | 30 | 220 | 10 | Réussite du modèle corrigé |

Chaque essai lit 128 chunks, relit le match du bloc 47, puis ajoute 61 lectures
bornées pour manager, table, 58 en-têtes et métadonnées.
Chaque essai effectue deux relectures AP de l'objet réservé, quatre GUARD et
deux READ sautés ; **zéro écriture mémoire et aucune action native SAVE**.

Le deuxième essai échoue dans l'analyse après arrêt propre : aucun problème
de jeu n'est inventé pour expliquer cette mauvaise hypothèse de recherche.
Les fixtures initiales partageaient cette hypothèse ; un nouveau test refuse
explicitement le faux total 58. Sa réanalyse hors ligne passe avec le modèle
corrigé, mais son statut runtime demeure **failed**.

Le dernier essai contrôle aussi le dispatch du manager, le provider 59 et
l'égalité du footer. Les trois tables ont le même SHA-256 :
`0aba09779ce1607b47377f09761adf67d26da6aa3fc47201cbf9d4fde74dfb22`.

Le fichier `main` reste
`f7906a7ec9f61e3f9ce8e13510d35269b3b0cb99ff1fe909c6de066fa68e1887`.
Les six snapshots pré/post contiennent aussi les métadonnées Encore inchangées.
Pour l'essai rejeté, cette conservation est vérifiée indépendamment ; le
champ `save_unchanged` du résultat initial est absent, pas réécrit après coup.
Voir les [résultats structurés](../research/save-manager-results.json).

## Fichiers et tests

- Créés : `tools/oras_save_manager.py`, `tests/test_save_manager.py`, rapport
  et preuves JSON.
- Modifiés : builder du plan, sonde Lua, lanceur du connecteur, tests d'objets,
  documentation et catalogue des candidats.
- **176 tests unitaires réussis** : propagation affine, littéraux, shifts,
  invalidation des registres, refus d'instructions non supportées, captures
  incomplètes, erreurs de tailles/offsets, footer CRC et distinction 58/59.
- Fixtures synthétiques uniquement. Les captures binaires réelles restent
  privées sous `local/oras/`, sans distribution ni exécutable complet extrait.

## Limites et suite

Le bloc réservé appartient à une structure native réinitialisable. Ni son nom,
ni son contenu nul, ni ses CRC ne confèrent une propriété exclusive à AP.
Aucune valeur AP n'y est écrite. Aucun reset artificiel, patch, hook ou appel
de méthode native n'est exécuté par la sonde.

Il reste à suivre le chemin générique de sérialisation et ses callers virtuels,
identifier les contextes sûrs, puis déterminer si un enregistrement possédé
explicitement par un patch est nécessaire. Persistance de données non nulles,
atomicité item/index, stockage AP et livraison live restent **non validés**.
Pas de déduction d'adresses AS, ni de progression manuelle requise ici.
