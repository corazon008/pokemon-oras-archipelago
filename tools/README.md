# Sondes BizHawk / Encore

Ces outils inventorient les capacités de Lua et testent le transport AP.
Ils lisent aussi des variables ORAS documentées, mais ne constituent pas
encore un client de jeu fonctionnel.

## Sauvegardes persistantes — depuis le 18 novembre 2026

**Les anciens profils `/tmp/opencode` ont été perdus au reboot.** Leurs hashes
dans les rapports ne sont pas des backups et ne permettent pas une restauration.

`run_bizhawk_save_probe.py` et `run_bizhawk_connector_probe.py` créent désormais
leurs profils sous `local/oras/profiles/`. Les exemples `/tmp` ci-dessous et les
anciens rapports décrivent le workflow historique : pour `--session`, utiliser
maintenant le chemin persistant affiché au lancement.

Les deux lanceurs publient automatiquement des copies CRC-validées avant le
lancement et après fermeture sous `local/oras/backups/`. Chaque copie contient
`00000001/` complet, les métadonnées Encore et `snapshot.json` (v2 : inventaire
de tous les fichiers/répertoires ; v1 mono-fichier reste compatible). Les `.partial-*`
ne sont pas des backups publiés. En cas d'échec de backup, ne pas poursuivre
les expériences avant d'avoir conservé le dernier fichier valide.

```sh
python3 tools/oras_profiles.py local/oras/backups/IDENTIFIANT
```

Les sauvegardes de jeu restent privées et ignorées par Git. Nextcloud peut les
synchroniser : Git ignore n'est pas une protection contre une publication ou
une suppression dans le cloud.

Pour créer une nouvelle partie avec contrôles clavier :

```sh
python3 tools/run_bizhawk_save_probe.py --interactive --keyboard-only \
  --rom "ROMs/Pokemon Omega Ruby (USA) (En,Ja,Fr,De,Es,It,Ko) (Rev 2).3ds"
```

Sauvegarder via le menu natif, fermer, puis vérifier le chemin
`backup_after_exit` dans le résultat. Reprendre avec `--session` et le chemin
`local/oras/profiles/oras-save-...` affiché ; **ne pas recréer un nouveau profil
à chaque reprise**.

Restaurer une copie vérifiée vers un nouveau profil avec
`--seed-save local/oras/backups/IDENTIFIANT/00000001/main`. Ne pas remplacer
manuellement la sauvegarde d'un profil courant. Les snapshots ne conservent
pas les changements restés uniquement en RAM et ne remplacent pas une copie
sur un stockage indépendant. Voir le
[rapport 014](../docs/reports/014-reboot-loss-and-durable-profiles.md).

## Exécution isolée

Depuis la racine du projet :

```sh
python3 tools/run_bizhawk_probe.py \
  --rom "ROMs/Pokemon Omega Ruby (USA) (En,Ja,Fr,De,Es,It,Ko) (Rev 2).3ds"
```

Changer `--rom` pour tester Saphir Alpha.
`--bizhawk` accepte une autre installation ; celle fournie dans `bin/` est
utilisée par défaut. Mono et un affichage graphique accessible sont requis.

Le lanceur :

1. Copie l'installation dans un nouveau dossier `/tmp/opencode/oras-bizhawk-*`.
2. Exclut le répertoire `3DS/` existant et prépare une configuration privée.
3. Désactive les chargements récents, le son et le plugin loader dans cette copie.
4. Lance le jeu avec `bizhawk_probe.lua`, avance 180 frames, prend une capture
   privée et ferme uniquement cette instance.
5. Écrit `run.json`, `capabilities.json`, `stdout.txt` et `stderr.txt`.

`--frames` accepte 0 à 3600 ; `--timeout` borne la durée du processus.
Un inventaire incomplet, une erreur de processus ou un système autre que `3DS`
produit un code de sortie non nul.

Le dossier temporaire reste disponible pour inspection ; aucune suppression
automatique d'un profil n'est effectuée.

## Limites importantes

- Aucun appel de lecture/écriture de mémoire de jeu, aucune touche injectée,
  aucune sauvegarde déclenchée par la sonde.
- L'émulateur peut écrire ses propres fichiers dans le profil temporaire.
- Les données utilisateur, sauvegardes et mises à jour installées dans le
  répertoire `3DS/` fourni **ne sont pas reprises**. Cet essai n'identifie donc
  pas la version utilisée dans une partie existante.
- La présence de l'API d'écriture est relevée sans l'appeler. Ce n'est pas une
  preuve que les écritures mémoire fonctionnent.
- Les compteurs de frames et une capture du menu ne démontrent pas qu'une partie
  complète est jouable ou que sa sauvegarde est correcte.
- `lua_socket_loadable = false` peut simplement signaler l'absence des
  dépendances du connecteur AP dans cette configuration vierge.
- Les sorties peuvent contenir des chemins locaux ; les captures représentent
  le jeu. Ne pas distribuer ces fichiers bruts.

Les fonctions CLR exposées par NLua ne sont pas nécessairement de type Lua
`function` ; la sonde utilise des appels protégés pour les observations et
ne teste pas la présence des API avec cette seule comparaison de type.

## Tests de l'outillage

```sh
python3 -m unittest discover -s tests -v
luac5.4 -p tools/bizhawk_probe.lua
```

Les tests Lua utilisent des API factices dont toute lecture/écriture mémoire
lève une erreur. Ils vérifient l'outillage uniquement ; les essais Encore réels
sont documentés séparément dans le rapport 002.

## Connecteur TCP amont

```sh
python3 tools/run_bizhawk_connector_probe.py \
  --rom "ROMs/Pokemon Omega Ruby (USA) (En,Ja,Fr,De,Es,It,Ko) (Rev 2).3ds"
```

Ce diagnostic :

- Télécharge les dépendances AP depuis un commit figé, dont LuaSocket Linux.
- Vérifie chaque SHA-256 du fichier `ap_connector.lock.json` avant chargement.
- Utilise le connecteur et l'API Python amont sans les modifier.
- Sans option mémoire, envoie seulement `VERSION`, `PING`, `SYSTEM` et deux
  requêtes `MEMORY_SIZE`.
- Vérifie une déconnexion/reconnexion et ferme sa propre instance via un signal
  fichier traité par le wrapper Lua.
- Produit `result.json`, `stdout.txt` et `stderr.txt` sous
  `local/oras/profiles/oras-connector-*`.

Connexion Internet nécessaire pour ces téléchargements. Aucun paquet système
ni dépendance Python externe n'est installé. Plateforme ciblée : Linux x86_64.
`--timeout` borne les essais réseau ; la fermeture dispose d'un délai distinct.
Les logs permettent de distinguer une fermeture propre d'un arrêt forcé.

Fermer les autres connecteurs avant l'essai : l'outil refuse de démarrer si leur
plage de ports est occupée. Ne pas lancer plusieurs diagnostics simultanément.
Les deux modules Python partagent la préparation du profil isolé.

Attention : le connecteur amont expose aussi des commandes d'écriture mémoire.
Le mode par défaut ne les envoie pas, mais ce service doit rester sur loopback,
sans redirection de port et sur une machine de confiance.

Ces échanges ne sont pas le protocole WebSocket du serveur Archipelago.
Voir le [rapport 003](../docs/reports/003-bizhawk-tcp.md).

### Gardes strictes

Ajouter `--strict-guards` avec `--read-code` ou un profil validé pour tester
des gardes en lecture seule. Le wrapper remplace volontairement le handler
GUARD, sans éditer les fichiers amont téléchargés.

Il exige le domaine exact, un intervalle valide et 1..65 536 octets complets ;
exception ou échec devient une garde fausse qui bloque la suite du lot.
Python attend son marqueur d'installation avant connexion. Les tests réels
ajoutent une garde valide et une garde de domaine absent suivie d'un READ sauté,
sur chaque connexion. Les compteurs READ incluent les demandes sautées, indiquées
séparément. Aucun WRITE n'est nécessaire pour ce test.

L'option d'écriture Potion active obligatoirement ce shim. Celui-ci ne réserve
pas d'espace AP, ne garantit pas le mapping des pages et ne rend pas plusieurs
écritures transactionnelles. Ne pas le confondre avec un protocole de livraison.
Voir le [rapport 017](../docs/reports/017-ledger-storage-and-strict-guards.md).

## Analyse d'exécutable et recherche d'objets

```sh
python3 tools/oras_code_research.py \
  "ROMs/Pokemon Omega Ruby (USA) (En,Ja,Fr,De,Es,It,Ko) (Rev 2).3ds"

python3 tools/run_bizhawk_connector_probe.py \
  --rom "ROMs/Pokemon Omega Ruby (USA) (En,Ja,Fr,De,Es,It,Ko) (Rev 2).3ds" \
  --session local/oras/profiles/oras-save-kkvwuxa5 \
  --scan-save-objects --speed 400 --timeout 240
```

La première commande décompresse `.code` en mémoire et publie seulement des
métadonnées : mapping ExHeader, hash, candidats de tableaux et providers A32
bornés. Elle n'extrait pas l'exécutable complet et ne prouve pas les limites
de fonctions ou l'absence de tables sous d'autres formes.

`--scan-save-objects` exige un profil validé et le build OR exact. Elle implique
EventWork et les gardes strictes, et refuse l'expérience d'écriture Potion.
Le plan privé impose un dispatch statique unique pour chaque bloc sélectionné,
vérifie les références et en-têtes connus, puis recherche l'objet candidat du
bloc 47 dans le heap documenté. Une correspondance unique est relue, puis
contrôlée via AP avant/après reconnexion. Zéro commande d'écriture.

`objects/references.bin` contient des références ROM et le payload de sauvegarde :
**privé, ignoré par Git, non distribuable**. `read-requests.txt` journalise les
lectures Lua séparément des requêtes AP. Les adresses sont des candidats en
lecture seule, pas du stockage approuvé pour AP.
Voir le [rapport 018](../docs/reports/018-executable-and-save-objects.md).

### Manager natif — capture en lecture seule

```sh
python3 tools/oras_save_manager.py \
  "ROMs/Pokemon Omega Ruby (USA) (En,Ja,Fr,De,Es,It,Ko) (Rev 2).3ds"

python3 tools/run_bizhawk_connector_probe.py \
  --rom "ROMs/Pokemon Omega Ruby (USA) (En,Ja,Fr,De,Es,It,Ko) (Rev 2).3ds" \
  --session local/oras/profiles/oras-save-kkvwuxa5 \
  --trace-save-manager --speed 400 --timeout 240
```

Le premier outil suit un fragment A32 droit et borné en mémoire : constantes
et offsets affines, sans exécution des instructions. Il laisse quatre offsets
de slots inconnus et refuse les formes non prises en charge.

`--trace-save-manager` implique `--scan-save-objects`, EventWork et gardes
strictes. Le nom signifie recherche de structures : **pas de trace d'exécution,
breakpoint, hook ou appel de méthode native**. Les références de code et trois
slots connus sont comparés avant lecture de la table régulière et de ses
58 en-têtes. 61 lectures supplémentaires capturent manager et métadonnées.

Le manager rapporte 59 entrées : 58 blocs et un index 58 spécial. Les tailles
reconnues, les offsets prédits et les descripteurs/footer sont comparés à la
référence ; une divergence échoue. Un provider contenant des appels reste
non reconnu plutôt qu'exécuté. Les captures `objects/manager-*.bin` sont privées.
Voir le [rapport 019](../docs/reports/019-native-save-manager.md).

### Références du fichier et sérialisation

```sh
python3 tools/run_bizhawk_connector_probe.py \
  --rom "ROMs/Pokemon Omega Ruby (USA) (En,Ja,Fr,De,Es,It,Ko) (Rev 2).3ds" \
  --session local/oras/profiles/oras-save-kkvwuxa5 \
  --scan-save-references --speed 400 --timeout 240

python3 tools/oras_save_serialization.py \
  "ROMs/Pokemon Omega Ruby (USA) (En,Ja,Fr,De,Es,It,Ko) (Rev 2).3ds"
```

Le scan implique le contrôle du manager et les gardes strictes. Il recherche
les références du manager dans le heap, relit des contextes de 320 octets,
sélectionne le record à taille/chemin exacts, puis recherche ses referrers
avec contextes de 512 octets. Les pointeurs doivent encore correspondre lors
de la capture. Ambiguïté excessive, référence ou longueur invalide : échec.

Les types trouvés dans les contextes restent des candidats : proximité n'est
pas propriété. Les binaires `manager-backref-*` et `save-record-referrer-*`
sont privés, non distribuables. Leur journal de lectures est compté séparément
des requêtes AP.

Le second outil analyse seulement l'exécutable en mémoire : syntaxe de huit
appels indirects, branches vers les boucles et reconstruction du layout aligné.
Ni SAVE, ni méthode native, ni callback d'exécution n'est déclenché par ces
outils. Voir le [rapport 020](../docs/reports/020-save-records-and-serialization.md).

### Observer une sauvegarde native sur copie

```sh
python3 tools/run_bizhawk_connector_probe.py \
  --rom "ROMs/Pokemon Omega Ruby (USA) (En,Ja,Fr,De,Es,It,Ko) (Rev 2).3ds" \
  --seed-save local/oras/backups/after-connector-oo15gvip/00000001/main \
  --observe-native-save --initial-time 2026-11-18T18:36:36 \
  --speed 400 --timeout 300
```

Cet exemple reproduit **ce checkpoint précis** et son contexte de temps.
`--observe-native-save` exige une copie fraîche, interdit `--session` et
l'expérience Potion, et garde les contrôles complets avant signal des boutons.
La macro entre dans le sac depuis l'overworld validé, puis confirme SAVE.
Aucune écriture mémoire n'est envoyée.

`--initial-time` est optionnel et réservé aux copies `--seed-save` :
il fixe l'horloge **émulée** dans leur configuration seulement, entre 2000 et
2099, sans timezone. Ne pas appliquer arbitrairement cette date à un autre save.
Le contrôle du rapport 021 l'utilise parce que la comparaison stricte d'une
queue EventWork inconnue diverge au changement de contexte temporel ; aucun
octet n'est masqué. L'horloge hôte et le réglage RTC du profil original ne sont pas changés.

Après les contrôles AP, sept plages RAM et le fichier backing sont lus à chaque
frame, au maximum 4 000 ticks. Les versions de buffers, `timeline.tsv`,
`reads.tsv` et la configuration sont conservées sous `native-save/`, en privé.
Une référence initiale incorrecte, une lecture courte ou des frames manquantes
font échouer la validation. Le polling peut perturber les timings.

**Les `file-*.bin` observés peuvent être CRC-invalides : ce ne sont pas des
backups.** Utiliser seulement les snapshots CRC-validés de `local/oras/backups/`.
Le résultat final exige fichier changé, 58 CRC valides, concordance des plages
RAM échantillonnées/footer et contrôles de progression inchangés. Cela ne prouve
pas une transaction item/index ni une sauvegarde résistante aux crashs.
Voir le [rapport 021](../docs/reports/021-native-save-observation.md).

### Fork de récupération — jamais en place

```sh
python3 tools/run_bizhawk_connector_probe.py \
  --rom "ROMs/Pokemon Omega Ruby (USA) (En,Ja,Fr,De,Es,It,Ko) (Rev 2).3ds" \
  --recover-from-snapshot local/oras/backups/before-connector-8ny3zimx \
  --initial-time 2026-11-18T18:36:36 --speed 400 --timeout 240
```

Ce checkpoint historique est vérifié par manifeste, ROM/Program ID, hashes et
58 CRC, puis importé dans **nouveau** `oras-recovery-*`. La commande ne remplace
aucun fichier de profil existant et interdit `--session`, un autre `--seed-save`,
SAVE, Potion et les macros `--steps` personnalisées. Elle vérifie cold boot/reconnexion sans écriture mémoire.
L'horloge de cet exemple est celle du checkpoint ; ne pas la généraliser.

Le fork peut revenir à une progression plus ancienne. Il ne déduit aucun index
de livraison, ne réinitialise pas le journal et n'autorise aucun replay AP.
Un fichier observé CRC-invalide n'est pas un snapshot récupérable.

Pour inspecter statiquement la liaison contrôleur/record et le chemin reset/load :

```sh
python3 tools/oras_save_lifecycle.py \
  "ROMs/Pokemon Omega Ruby (USA) (En,Ja,Fr,De,Es,It,Ko) (Rev 2).3ds" \
  --probe-result local/oras/profiles/oras-recovery-s39bw9g9/result.json
```

L'outil vérifie des signatures du build exact et des pointeurs capturés.
Il n'invoque pas de méthode native ; l'octet de retour I/O n'est pas promu
flag d'autorisation d'écriture. Voir le
[rapport 022](../docs/reports/022-recovery-forks-and-load-reset.md).

### Bootstrap natif expérimental — RAM volatile uniquement

```sh
python3 tools/run_bizhawk_connector_probe.py \
  --rom "ROMs/Pokemon Omega Ruby (USA) (En,Ja,Fr,De,Es,It,Ko) (Rev 2).3ds" \
  --seed-save local/oras/backups/before-connector-8ny3zimx/00000001/main \
  --experimental-bootstrap hook \
  --initial-time 2026-11-18T18:36:36 --speed 400 --timeout 240
```

Remplacer `hook` par `allocation-only` pour le témoin sans écriture du marqueur.
Build OR exact uniquement ; profil neuf obligatoire. Réutilisation, recovery,
SAVE, Potion, scans et macros personnalisées refusés. L'horloge correspond ici
au seed historique, pas à une règle générale.

L'expérience crée dans le profil privé un petit `code.ips` et un
`exheader.bin` dérivé de la ROM personnelle : **ne pas distribuer ce dernier**.
La taille text est étendue explicitement ; une page BSS supplémentaire est
allouée après les pages originales. Le hook y écrit un marqueur de huit octets
puis reprend le démarrage natif. Aucun `code.bin` complet ni ROM modifiée.

Les lectures vérifient code/marqueur, inventaire et EventWork avant/après
reconnexion. `memory_write_requests = 0` compte les requêtes du connecteur :
**le hook effectue une écriture native de huit octets**, pas un WRITE Lua/AP.
Ce n'est ni un ledger persistant ni une autorisation de livraison ; le bloc 47
reste interdit. Voir le [rapport 023](../docs/reports/023-native-bootstrap-and-owned-ram.md).

Le mode `--experimental-bootstrap registration-trace` intercepte en plus
constructeur, entrée et retour de l'enregistrement natif de `main`. Les logs
restent dans la page RAM ajoutée et sont relus avant/après reconnexion ;
captures privées sous `registration-trace/connection-*`. Il ne crée pas de
second record ni de fichier AP. Voir le
[rapport 024](../docs/reports/024-native-save-registration-trace.md).

**Snapshots v2 : archive complète.** Tous les fichiers, dossiers vides et
métadonnées sont conservés et hashés. Liens/fichiers spéciaux, chemins dangereux,
limites dépassées ou contenu altéré : refus. Les imports multi-fichiers exigent
un snapshot v2 vérifié et un nouveau fork en lecture seule
(`--recover-from-snapshot` ou test `sidecar-reload`). Un seed brut/v1 reste
mono-fichier ; aucune restauration en place.
Voir le [rapport 025](../docs/reports/025-full-archive-snapshots-and-imports.md).

Préserver les octets d'un sidecar ne valide ni son index AP ni sa cohérence avec
`main`. Le formatage natif Encore supprime le répertoire de sauvegarde : ne pas
l'utiliser comme migration en place.

### Sidecar natif expérimental — enregistrement et lecture

```sh
python3 tools/run_bizhawk_connector_probe.py \
  --rom "ROMs/Pokemon Omega Ruby (USA) (En,Ja,Fr,De,Es,It,Ko) (Rev 2).3ds" \
  --seed-save local/oras/backups/before-connector-8ny3zimx/00000001/main \
  --experimental-bootstrap sidecar-load \
  --initial-time 2026-11-18T18:36:36 --speed 400 --timeout 120
```

Ce mode prend un snapshot mono-fichier vérifié et prépare `aptest` sur une
nouvelle copie uniquement. Il enregistre le fichier de test et vérifie ses
512 octets chargés par le lecteur natif, ainsi que les deux records et les
retours du lecteur avant/après reconnexion. Le contenu est préparé par l'hôte ;
aucun SAVE, aucun index ni livraison AP. Ne pas réutiliser le profil patché
pour jouer. Voir le [rapport 026](../docs/reports/026-native-sidecar-load.md).

Pour tester une écriture native du marqueur, reprendre cette commande avec
`--experimental-bootstrap sidecar-save`. Le lanceur vérifie la copie et ses
lectures/reconnexions avant d'envoyer les boutons SAVE. Le code invité écrit
seulement le marqueur de test dans la RAM ajoutée, puis appelle le writer natif
du sidecar après celui de `main`. La sonde vérifie les octets après SAVE en RAM
et sur disque, ainsi que les CRC et l'inventaire/EventWork de `main`.

Pour le cold reload, reprendre la commande avec
`--seed-save <backup_after_exit>/00000001/main` et
`--experimental-bootstrap sidecar-reload`. Cette variante n'installe pas le hook
SAVE et ne recrée pas la fixture. Le marqueur et l'archive complète doivent
déjà être valides avant boot. Ce test ne prouve ni durabilité après panne ni
atomicité inter-fichiers, et n'autorise aucun replay AP.
Voir le [rapport 027](../docs/reports/027-native-sidecar-save-reload.md).

## Identité ROM et preuve de lecture

```sh
python3 tools/rom_identity.py \
  "ROMs/Pokemon Omega Ruby (USA) (En,Ja,Fr,De,Es,It,Ko) (Rev 2).3ds"

python3 tools/run_bizhawk_connector_probe.py --read-code \
  --rom "ROMs/Pokemon Omega Ruby (USA) (En,Ja,Fr,De,Es,It,Ko) (Rev 2).3ds"
```

La première commande lit les en-têtes et calcule le SHA-256 complet sans modifier
la ROM. Elle n'associe pas de numéro commercial à `remaster_version`.

La seconde ajoute **deux lectures de 64 octets**, avant et après reconnexion,
à l'adresse virtuelle du texte dérivée de l'ExHeader. La référence est prise
dans le préfixe non compressé de `.code`, sans extraction sur disque.
La comparaison échoue si la référence est indisponible ou si la mémoire diffère.
Les octets ne sont pas enregistrés dans les résultats JSON.

Cette option ne lit aucune variable de progression et n'envoie aucune écriture.
Le mode sans `--read-code` ni `--seed-save` reste limité aux métadonnées.
Voir le [rapport 004](../docs/reports/004-rom-identity-and-read.md).

## Inventaire via le connecteur AP

```sh
python3 tools/run_bizhawk_connector_probe.py \
  --rom "/chemin/vers/OR-verifie.3ds" \
  --seed-save "/chemin/prive/00000001/main" --speed 400 --timeout 150
```

Importe uniquement `main` et son archive `00000001.metadata` de 16 octets.
Les 58 CRC sont obligatoires. La ROM doit avoir un profil mémoire documenté
pour son SHA-256 exact ; AS n'est pas accepté pour cet essai.

Le wrapper ouvre la partie et la poche Médecine par boutons natifs avant
de lancer le connecteur amont intact. Deux connexions lisent chacune le
préfixe de code ROM et l'inventaire complet via l'API Python AP.
`--seed-save` implique ces lectures, sans nécessiter `--read-code`.
`--steps` remplace la macro de démarrage ; inspecter les captures `boot/`.

### Écriture expérimentale : une Potion seulement

**Cette option modifie uniquement une nouvelle copie privée. Elle ne doit pas être
utilisée comme mécanisme de livraison Archipelago ni sur une sauvegarde principale.**

Ajouter `--experimental-potion-1-to-2` à la commande précédente :

- ROM OR, adresse, domaine et préfixe de code strictement autorisés par l'essai.
- Potion déjà présente dans le slot 0 Médecine, quantité exactement 1.
- Une soumission `guarded_write` : gardes sur code et bloc inventaire complet,
  puis écriture de **2 octets** à `0x08C6B5F2`, quantité 2.
- Relecture complète immédiate, puis nouvelle connexion avec mêmes contrôles.
- Aucun autre octet d'inventaire ne peut différer de la référence attendue.
- Macro native SAVE déclenchée seulement après ces comparaisons.
- Arrêt sans réessai si garde rejetée, réponse perdue ou valeur incohérente.
- Vérification du fichier résultant et de ses 58 CRC après fermeture.

`write_allowed: false` reste inchangé dans le catalogue de recherche : aucun
accès générique en écriture n'est autorisé. L'exception est codée séparément et
n'accepte aucune adresse, quantité ou valeur de remplacement libre.
La macro suppose le contexte UI connu ; aucun détecteur général combat/menu
n'existe. Le rechargement à froid reste une vérification distincte.

Le dossier de réussite contient un `profile.json` compatible avec
`run_bizhawk_save_probe.py --session local/oras/profiles/oras-connector-IDENTIFIANT`.
Pour revoir Médecine après redémarrage, utiliser les étapes de démarrage
documentées dans le [rapport 008](../docs/reports/008-connector-inventory-and-write.md).
Le JSON distingue soumission d'écriture, accusé réseau, relecture RAM et fichier
sauvegardé. Les gardes sont comptées séparément des requêtes `READ`.
Une erreur de handler Lua dans le connecteur amont ne garantit pas l'annulation
du reste du lot : résultat alors inconnu, sans nouvelle écriture ni SAVE
déclenché. Voir les limites du rapport ; ce n'est pas une transaction générale.

## Créer une sauvegarde jouable dans un profil privé

```sh
python3 tools/run_bizhawk_save_probe.py --interactive \
  --rom "ROMs/Pokemon Omega Ruby (USA) (En,Ja,Fr,De,Es,It,Ko) (Rev 2).3ds"
```

Cette commande ouvre une **nouvelle copie isolée** de BizHawk. Créer une partie,
atteindre un état jouable, sauvegarder depuis le menu natif et fermer proprement
l'émulateur. Ne pas remplacer un fichier du répertoire `bin/` ou la ROM originale.

Le terminal indique le dossier `local/oras/profiles/oras-save-*`. Le conserver pour
les essais suivants : il contient le profil et sa sauvegarde de test.
Le mode interactif n'a ni macro, ni fermeture automatique après délai.
Une fermeture réussie de la fenêtre ne prouve pas à elle seule qu'une sauvegarde
a été effectuée ; ce point devra être vérifié au rechargement.

### Entrée bloquée ou dérive de manette

Si le personnage se déplace seul, fermer l'émulateur sans sauvegarder puis
relancer **le même profil**, sans réimporter :

```sh
python3 tools/run_bizhawk_save_probe.py --interactive --keyboard-only \
  --session local/oras/profiles/oras-save-IDENTIFIANT \
  --rom "/chemin/vers/OR-verifie.3ds"
```

Cette option change uniquement les contrôles 3DS du profil de test :

- Flèches : déplacement ; **X** : confirmer/A ; **Z** : retour/B.
- **S** : bouton X/menu ; **A** : bouton Y ; Entrée/Space : Start/Select.
- Bindings de manette, axes Circle Pad/C-Stick et autofire 3DS retirés.
- Souris conservée pour le tactile.
- `SDL_JOYSTICK_HIDAPI=0` limité à ce processus, pas au système.
- Aucun script Lua de contrôle ni macro en mode interactif.

Les contrôles des autres systèmes et du profil `bin/` restent inchangés.
Le mode interactif ordinaire ne change pas ses pilotes d'entrée.
Une reconnexion ou dérive de manette n'est pas diagnostiquée avec certitude
par cette option : elle fournit un contournement clavier explicite.

Pour reprendre ce même profil :

```sh
python3 tools/run_bizhawk_save_probe.py --interactive \
  --session local/oras/profiles/oras-save-IDENTIFIANT \
  --rom "ROMs/Pokemon Omega Ruby (USA) (En,Ja,Fr,De,Es,It,Ko) (Rev 2).3ds"
```

Les anciens profils `/tmp` étaient temporaires ; ils ne sont plus le défaut
pour les sauvegardes. Conserver profils persistants et snapshots privés.

Le mode automatisé, sans `--interactive`, accepte par exemple :

```text
--steps "180:-,2:A,120:-"
```

Cela signifie attendre 180 frames, appuyer sur A pendant deux frames, puis
attendre 120 frames. Chaque étape produit une capture privée. Seuls les boutons
ordinaires sont autorisés ; pas de Reset, toucher ou code Lua arbitraire.

`--seed-save` peut importer une copie d'un `main` validé par taille, marqueur,
descripteurs et CRC ORAS. Son fichier Encore `00000001.metadata` de 16 octets doit être présent à
côté du dossier `00000001/`. Aucun déchiffrement ou conversion n'est tenté.
Ce contrôle ne remplace pas un chargement effectif par le jeu.
`--seed-save` et `--session` sont incompatibles pour éviter
de réinitialiser une sauvegarde de travail.

Le candidat trouvé lors de la recherche initiale n'avait pas le marqueur attendu.
Une nouvelle sauvegarde native a depuis été fournie et rechargée. Voir le
[rapport 005](../docs/reports/005-private-save-profile.md).

## Vérifier une sauvegarde et observer son inventaire

```sh
python3 tools/oras_save.py /chemin/prive/00000001/main
```

Cette inspection vérifie désormais les **58 CRC et descripteurs ORAS**, puis
affiche les objets et quantités sans lire les noms du joueur ou ses identifiants.
Le contrôle est aussi obligatoire avant un nouvel import.

Après création d'une copie de travail, les options de recherche sont :

- `--read-inventory` : une lecture bornée à l'adresse documentée pour le SHA-256
  de cette ROM, comparée au bloc de sauvegarde validé.
- `--scan-inventory` : recherche exacte dans le tas applicatif documenté d'Encore ;
  aucune adresse d'inventaire n'est supposée.
- Ces modes sont exclusifs et interdits en mode interactif.
- La référence doit contenir des données non nulles. Zéro ou plusieurs résultats
  ne sont pas automatiquement promus en adresse utilisable.
- `--speed 400` accélère les pas natifs automatisés ; le profil est remis à
  100 % à la prochaine préparation.

Les lectures sont faites après les `--steps` de démarrage/chargement et de menu.
Leur durée dépend du jeu : une macro terminée ne prouve pas que le bon écran a
été atteint. Inspecter les captures privées.

Les modes mémoire sont **strictement en lecture**. L'adresse retenue pour OR
est restreinte au build identifié ; elle n'autorise pas d'écriture et n'est
pas transposée à AS. Le candidat du plugin Gen6 a échoué sur ce build.

Le lanceur désactive HIDAPI dans les processus automatisés et le mode clavier explicite, pour
contourner une exception SDL observée à la fermeture. Les entrées physiques
des sessions interactives ne sont pas modifiées.
Voir le [rapport 006](../docs/reports/006-native-reload-and-inventory.md).

## Observer une variation native

Avec `--read-inventory`, `--sample-step N` ajoute une lecture après l'étape N,
puis une seconde à la fin. La première doit correspondre au fichier validé.
La comparaison `--expect-medicine 17:0` vérifie ensuite une quantité de Potion
devenue nulle par **action native**. Elle n'écrit rien dans le jeu.

Cette option exige une étape intermédiaire et refuse une variation d'autres
objets ou d'autres poches. Les journaux comptent les lectures même si elles
échouent. Captures binaires d'inventaire et captures d'écran restent privées.

Les macros sont dépendantes du contexte UI. Une macro terminée ou une
variation RAM réussie ne prouve pas une sauvegarde : vérifier le message natif,
le fichier, ses CRC puis un redémarrage. Les preuves observées sont dans le
[rapport 007](../docs/reports/007-native-quantity-and-persistence.md).

## Rechercher et observer EventWork

- `--scan-event-work` cherche le bloc 19 complet d'une sauvegarde CRC-valide
  dans le tas documenté d'Encore, sans supposer une adresse relative au sac.
- `--read-event-work` utilise seulement un candidat documenté pour le SHA-256
  ROM exact. Le catalogue maintient les écritures interdites.
- `--event-sample-steps 7,12,16` lit après ces étapes natives, puis à la fin.
  Les indices doivent être distincts et appartenir au plan UI.
- Avec des échantillons intermédiaires, le premier dans l'ordre chronologique
  doit correspondre au fichier validé avant lancement, sinon l'essai échoue.
- Ces modes sont exclusifs entre eux, avec les modes inventaire et avec
  l'interactif. Aucun octet mémoire n'est modifié.

Les différences séparent mots uint16, flags et fin du bloc sans sémantique
connue. Une lecture terminée ne prouve pas une fin d'événement. Voir le
[rapport 009](../docs/reports/009-native-clock-event-candidate.md) et son plan natif.

Pour comparer deux fichiers, sans émulateur ni modification :

```sh
python3 tools/oras_events.py /copie/avant/main /copie/apres/main
```

### EventWork via l'API Archipelago, sans nouvelle copie

```sh
python3 tools/run_bizhawk_connector_probe.py \
  --rom "/chemin/vers/OR-verifie.3ds" \
  --session local/oras/profiles/oras-save-IDENTIFIANT \
  --read-event-work --speed 400 --timeout 150
```

Fermer tout émulateur utilisant ce profil avant lancement. Le manifeste doit
correspondre au SHA-256 ROM exact. Les résultats sont dans un
`connector-attempt-*`, le runtime et la sauvegarde ne sont pas réimportés.
Les bindings clavier sont conservés.

Code, inventaire et EventWork sont relus avant/après reconnexion. Ce diagnostic
exige encore un inventaire non nul. Le fichier `main` entier doit rester inchangé.
Les états du candidat horloge non observés sont **inconnus**, jamais déduits d'un seuil.
Ce n'est pas un check de location ni un client AP.

La réponse `event_read.pokedex` expose aussi le flag décimal 2722, après
comparaison du bloc complet à la sauvegarde CRC-valide. Sa transition native
faux → vrai, son rechargement et l'interface fonctionnelle sont documentés dans
le [rapport 013](../docs/reports/013-pokedex-event-and-persistence.md).
`production_location_approved` reste faux : aucun check n'est envoyé.

`--session` et `--seed-save` sont exclusifs. L'écriture expérimentale exige
toujours une nouvelle copie depuis `--seed-save`, sans `--read-event-work`.
Voir le [rapport 011](../docs/reports/011-clock-event-follow-up-and-ap-read.md).
