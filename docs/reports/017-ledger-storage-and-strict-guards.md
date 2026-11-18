# Rapport 017 — stockage de l'index et gardes strictes

Date : 18 novembre 2026.

## Résultat

La recherche en lecture n'identifie **pas encore de stockage appropriable**
pour l'index AP. Un commentaire « Unused » et un bloc nul ne suffisent pas.
Aucune adresse de compteur n'est inventée et aucune donnée de jeu n'est écrite.

Un prérequis indépendant est renforcé : un shim GUARD ferme les chemins où
une erreur ou une lecture incomplète pourrait laisser exécuter la suite d'un
lot du connecteur. La validation réelle révèle également un fallback de domaine
silencieux de BizHawk, désormais rejeté explicitement dans ce shim.

**Deux connexions réelles vérifiées, aucun WRITE, sauvegarde inchangée.**

## Recherche de stockage : le bloc 47 n'est pas réservé

Sources PKHeX au commit `6c9583883c7551ac74a4b74180cead249d4277b8` :
`SaveBlockAccessor6AO.cs` et `SAV6AO.cs`.

Le bloc 47 du fichier ORAS est décrit à `0x20600`, longueur `0x7D0` (2 000
octets), avec le commentaire exact `Unused (lmao)`. Il possède un CRC dans le
layout déjà vérifié. Il n'a pas d'accesseur nommé dans cette classe d'éditeur.
Ce n'est pas une preuve que le jeu ne le lit ou ne l'écrase jamais.

Dans la nouvelle référence réelle `after-exit-72633fon`, les 2 000 octets sont
nuls. Une recherche de ce motif ne pourrait pas identifier une adresse unique ;
la sonde existante refuse justement les motifs nuls.

Conclusion :

- Offset de fichier documenté, pas adresse RAM.
- Aucune propriété exclusive AP démontrée.
- Aucun cycle natif d'initialisation/sérialisation ou comportement tardif prouvé.
- Aucun octet de ce bloc, d'un trou d'alignement ou d'un flag libre présumé réservé.
- `next_delivery_index` doit donc rester indisponible pour un adaptateur réel.

La possession du Pokédex ne se déduit pas non plus de `SAV6AO.HasPokeDex` :
cette propriété renvoie une constante `true` dans l'éditeur, pas le flag 2722
du fichier. Les sémantiques d'API d'éditeur ne remplacent pas les observations
natives des rapports 012/013.

## Défaut GUARD reproduit sans émulateur

Le dispatch amont `send_receive` répond `ERROR` si un handler lève, mais ne
supprime les commandes suivantes que pour `GUARD_RESPONSE` avec `value=false`.
La garde amont compare aussi les octets reçus sans exiger la longueur attendue.

`tests/strict_guard_dispatcher_fixture.lua` exécute le dispatcher amont figé,
non édité, avec de faux sockets et API mémoire. Un WRITE n'y fait qu'incrémenter
un compteur de test. Trois lots fautifs sont exercés :

1. Exception de lecture.
2. Lecture partielle dont le préfixe correspond.
3. Exception de décodage.

Sans shim : trois appels au faux WRITE. Avec shim : zéro. Ce test est facultatif
si aucun bundle vérifié n'est en cache ; il a été exécuté ici. Aucun octet du
jeu ni émulateur n'est utilisé dans ce contrôle.

## Shim strict et protocole de préparation

`tools/strict_bizhawk_guard.lua` fournit un handler où toutes les opérations
faillibles sont dans `pcall`. L'échec produit toujours une garde fausse, pas
un `ERROR` laissant passer la suite.

Il impose :

- Adresse entière et intervalle dans l'espace 32 bits.
- Longueur non nulle, au plus 64 Kio.
- Domaine existant **par nom exact**, avant toute lecture.
- Intervalle appartenant à ce domaine.
- Lecture de longueur exactement attendue et octets valides.
- Comparaison complète.

Le cas Encore `System Bus` à 4 Gio, tronqué à zéro par l'API uint32, reste
traité explicitement pour 3DS seulement. L'énumération utilise aussi l'entrée
zéro du tableau Lua.

Le wrapper installe ce handler après initialisation du module amont, puis écrit
un marqueur. Python attend ce marqueur avant toute connexion en mode strict.
L'absence d'installation ou la fin du processus échoue sans continuer.

**Les fichiers amont restent intacts**, SHA-256 vérifiés ; le comportement
du handler GUARD est intentionnellement remplacé dans le wrapper local.
Ce n'est donc pas un connecteur au comportement entièrement non modifié.

`--strict-guards` active cette option. L'expérience Potion explicite l'active
désormais obligatoirement ; son chemin d'écriture ne doit pas revenir aux
anciennes gardes. Aucune écriture Potion n'est réexécutée dans cette phase.
Les options de wrapper héritées de l'environnement sont nettoyées avant
préparation des options effectives.

## Échec réel découvert, puis correction

Premier essai : `connector-attempt-105mc67f`.
La garde de code connue passe. La garde demandant un domaine volontairement
absent ne bloque pas la lecture suivante. Le journal indique :

```text
Unable to find domain: ORAS_TEST_ABSENT_DOMAIN, falling back to current
```

La méthode `MemoryApi.NamedDomainOrCurrent` au commit BizHawk
`bdddf4a58aa1a022afb11dc73294a81a5aa7bbd5` confirme ce comportement.
Une adresse hors domaine peut aussi être complétée de zéros par `ReadByteRange`.
Se contenter de `pcall` et de la longueur n'aurait donc pas suffi.

L'essai est classé **échec**, malgré sortie de processus 0. Il n'a envoyé
aucune écriture. Le fichier et les backups sont restés valides.

Après ajout de la vérification nom exact + intervalle :
`connector-attempt-_yveml1n`.
Deux connexions passent les contrôles :

- Code, inventaire et EventWork conformes à la sauvegarde.
- Garde du code valide acceptée.
- Domaine absent rejeté avant accès à l'API de lecture.
- READ placé après la garde fausse non exécuté.
- **8 READ soumis, dont 2 sautés ; 4 GUARD ; 0 WRITE.**
- Sortie 0 et fichier entier inchangé.

Les deux essais se trouvent sous `local/oras/profiles/oras-save-kkvwuxa5/`.
Les backups pré/post de l'essai corrigé sont validés séparément. Le SHA-256 de
`main` reste `f7906a7ec9f61e3f9ce8e13510d35269b3b0cb99ff1fe909c6de066fa68e1887`.
Les [résultats structurés](../research/ledger-storage-and-guard-results.json)
séparent les contrôles factices, l'échec et la réussite réelle.

## Limites maintenues

- Les exceptions de mémoire et lectures courtes sont injectées **dans les
  fixtures**, pas dans le cœur réel. Le contrôle réel teste un domaine absent.
- Deux WRITE ne forment pas une transaction : le shim ne fournit aucun rollback
  si une écriture échoue après une modification partielle.
- L'appartenance au domaine ne prouve pas qu'une page 3DS est mappée ou appartient
  au jeu : des zéros peuvent encore venir d'une page non mappée.
- Pas de preuve de contexte sûr, de stockage AP réservé ou de sauvegarde atomique
  item + index. Pas de livraison live ni de serveur.
- Le mode non strict garde le comportement amont ; garder le service sur
  loopback et ne pas l'exposer à des clients non fiables.

## Tests et suite

**128 tests unitaires réussis**, dont 11 nouveaux : erreurs, lectures partielles,
décodage, domaines/ranges, octets invalides, attente d'installation et validation
des réponses. Les contrôles du dispatcher utilisent le bundle local vérifié,
sans téléchargement durant les tests.

Créés : shim, fixtures et tests stricts, présent rapport et résultats JSON.
Modifiés : wrapper, lanceur du connecteur et documentation.

Suite : analyser le chemin natif de chargement/sauvegarde et les propriétaires
du bloc 47, ou établir un enregistrement explicitement possédé par un patch.
Ne pas installer d'index tant que propriété, adresse et sérialisation ne sont
pas démontrées sur le build exact.
