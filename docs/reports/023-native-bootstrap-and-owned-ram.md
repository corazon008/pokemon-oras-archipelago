# Rapport 023 — bootstrap natif et RAM explicitement ajoutée

Date : 19 novembre 2026.

## Résultat

**Premier petit hook A32 exécuté sur OR via le loader IPS d'Encore.** Il écrit
un marqueur dans une nouvelle page BSS puis reprend le démarrage original.
Deux copies avec hook et deux contrôles sans hook démarrent nativement ;
inventaire/EventWork conformes et reconnexion TCP validés.

Ce résultat débloque un mécanisme de patch natif, **pas le stockage persistant
AP**. La page est volatile, aucun compteur de livraison n'y est initialisé,
aucun item ni bloc de sauvegarde modifié. Le bloc 47 reste interdit.

**211 tests réussis.** ROM, sauvegarde originale et connecteur fourni par
l'utilisateur préservés. Aucun SAVE déclenché.

## Choix technique

Une région de sauvegarde remplie de zéros ne devient pas libre parce qu'AP y
écrit une signature. Au lieu de réaffecter le bloc 47, cette phase établit une
première allocation native indépendante et un chemin de déploiement réversible.

Les sources figées corroborent :

- [Encore NCCHContainer](https://github.com/CasualPokePlayer/encore/blob/49a332221e1c9dffcc2c52f85a1765b1951c222f/src/core/file_sys/ncch_container.cpp) :
  override `load/mods/<ProgramID>/exheader.bin` et patch `code.ips`.
- [Encore LoadExec](https://github.com/CasualPokePlayer/encore/blob/49a332221e1c9dffcc2c52f85a1765b1951c222f/src/core/loader/ncch.cpp) :
  segments par nombre de pages, BSS arrondie et ajoutée après les pages data ;
  IPS appliqué après décompression/allocation, avant création du processus.
- [Format ExHeader](https://github.com/CasualPokePlayer/encore/blob/49a332221e1c9dffcc2c52f85a1765b1951c222f/src/core/file_sys/ncch_container.h) :
  structure de `0x800` octets, dont taille text à `0x18` et BSS à `0x3C`.

Seul le build OR SHA-256
`d76faafacd746fdcc5ec04a60b8b82ceb9678c3ad937b374234a506c50c417e4`,
Program ID `000400000011C400`, est autorisé. Aucun port AS ou console réelle
n'est revendiqué. La validité des signatures d'ExHeader sur matériel réel
n'est pas étudiée ; Encore accepte ici l'override local.

## Allocation explicite et trampoline

| Élément | Original | Expérience |
|---|---|---|
| Taille text déclarée | `0x479604` | `0x479638` |
| Pages text | `0x47A` | inchangées |
| Code ajouté | absent | `0x00579610`, 40 octets |
| Taille BSS | `0x7EC2C` | `0x80000` |
| BSS arrondie du loader | `0x7F000` | `0x80000` |
| Page RW supplémentaire | absente | `[0x006AF000, 0x006B0000)` |

La page RW commence **après l'ancienne allocation BSS arrondie**, pas dans sa
fin inutilisée. La taille text est étendue explicitement pour inclure le code
ajouté, sans changer ses pages ni déplacer ro/data. Les octets remplacés dans
l'ancienne image sont l'appel d'entrée de quatre octets et la portion de queue
nouvellement déclarée. Le builder refuse une queue occupée, un mapping différent
ou un appel d'entrée inattendu. Les zéros seuls ne prouvent pas une propriété
exclusive globale ; l'expérience est bornée à ce bootstrap, pas à un writer.

L'appel d'entrée à `0x00100000` vise le trampoline plutôt que le helper initial
`0x00100024`. Le trampoline :

1. Sauvegarde `r0`, `r1`, `r2`, `lr`, sans changer les flags ; pile alignée à 8.
2. Écrit `APBT` suivi de la version 1 dans les huit premiers octets de la
   nouvelle page, par instruction native `STM`.
3. Restaure les registres puis branche au helper original avec `lr=0x00100004`.

Le helper initial reste exécuté et revient au deuxième appel d'origine.
Il n'y a ni appel filesystem, ni fonction d'inventaire, ni RPC de livraison.

Le contrôle `allocation-only` installe le même ExHeader mais un IPS vide :
appel d'entrée original, aucune écriture du marqueur. La lecture de zéros seule
ne prouve pas le mapping ; la preuve positive repose sur le code installé et
le marqueur non nul effectivement écrit, avec témoin sans hook.

## Essais réels

Seed commun : snapshot valide `local/oras/backups/before-connector-8ny3zimx`,
SHA-256 `f7906a7ec9f61e3f9ce8e13510d35269b3b0cb99ff1fe909c6de066fa68e1887`.
Horloge explicite sur copie : `2026-11-18T18:36:36`. Vitesse 400 %.

| Profil privé | Mode | Résultat |
|---|---|---|
| `oras-connector-fa8ekk9z` | allocation seule, premier contrôle | complet, marqueur zéro |
| `oras-connector-r_yglvy7` | premier hook | complet, `4150425401000000` |
| `oras-connector-fmxy4uz3` | répétition avec code final | complet, même marqueur |
| `oras-connector-gmjr4xvf` | répétition contrôle, après le hook | complet, zéro |

Chaque essai utilise une nouvelle copie et deux connexions AP :

- Avec hook : préfixe patché, 40 octets de trampoline et marqueur relus avant
  et après reconnexion ; 12 READ soumis au total.
- Sans hook : préfixe original et huit octets nuls relus ; 10 READ soumis.
- Chaque fois : quatre GUARD dont deux négatifs sautant leur READ ; inventaire
  et EventWork entiers conformes ; sortie propre 0.
- `main` inchangé, 58 CRC valides et snapshots pré/post vérifiés ; seed et
  métadonnées sources inchangés.
- Zéro requête WRITE du connecteur et aucune écriture Lua. **Avec hook, le CPU
  du jeu écrit bien huit octets de marqueur** ; le compteur transport zéro
  ne signifie donc pas « aucune écriture mémoire native ».

Les premiers essais étiquetaient le préfixe contrôle comme référence bootstrap
sans indiquer aussi sa concordance avec le préfixe ROM. Ce libellé est corrigé
dans le code final et le contrôle répété ; les anciens artefacts sont conservés.
Les hashes permettent de distinguer les préfixes original et patché.

Ce n'est pas un traceur instruction par instruction ni un test de crash.
Le marqueur corrobore le passage dans le hook, mais ne prouve aucun contexte
sûr pour livrer des objets après le démarrage.

## Garde-fous et fichiers privés

`--experimental-bootstrap hook|allocation-only` exige une nouvelle copie
`--seed-save`. Refus de `--session`, récupération, SAVE instrumenté, Potion,
scans d'objets/manager et macros personnalisées. Les lectures EventWork et les
gardes strictes sont activées. La réutilisation normale d'un profil bootstrap
est refusée afin de ne pas mélanger références originales et patchées.

La ROM reste ouverte en lecture seule. Le lanceur refuse les overlays adjacents
à la ROM et ne crée aucun mod dans l'installation source. Seuls deux fichiers
locaux sont écrits dans le profil expérimental :

- `code.ips` : 62 octets générés pour le hook, 8 pour le contrôle.
- `exheader.bin` : 2 048 octets dérivés de la ROM personnelle, **privés et non
  distribuables**, dont seuls les deux champs de taille sont modifiés.

Aucun `code.bin` complet écrit. Les artefacts restent sous `local/`, ignoré par
Git ; seuls builder, tests, documentation et résultats sans données propriétaires
sont commités.

## Validation et suite

Créés : `tools/oras_bootstrap_patch.py`, `tests/test_bootstrap_patch.py`,
présent rapport et [résultats structurés](../research/native-bootstrap-results.json).
Modifiés : lanceur connecteur, tests protocole, README et documentation outils.

Les 211 tests couvrent notamment branches/littéraux du trampoline, champs
ExHeader non concernés inchangés, limites IPS, faux mapping/queue occupée,
mauvaise ROM/overlays, modes incompatibles et refus d'un marqueur absent,
partiel ou changé après reconnexion.

**Étape 1 encore partielle :** un espace RAM et un hook explicitement ajoutés
sont maintenant démontrés, mais aucun enregistrement persistant AP possédé
par le patch n'existe. Prochaine tâche : concevoir/enregistrer ce stockage via
le chemin natif sans réaffecter silencieusement un bloc du jeu, puis vérifier
reset, sauvegarde et rechargement. Identité monde/slot, index durable, opération
item/index et récupération après interruption restent à prouver.
