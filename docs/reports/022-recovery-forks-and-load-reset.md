# Rapport 022 — forks de récupération et liaison load/reset

Date : 19 novembre 2026.

## Résultat

Le véritable échantillon CRC-invalide du rapport 021 est refusé comme seed
**avant lancement d'EmuHawk**, sans écriture mémoire ni backup publié.
Un snapshot valide antérieur est ensuite chargé dans **nouveau profil de
récupération**, avec rechargement natif et reconnexion AP conformes.

La liaison du record de 48 octets à son contrôleur est corroborée par instructions
et pointeurs capturés. Le chemin natif sait remettre à zéro le payload réservé,
puis le lecteur générique charge les données via son getter.
Cela ne réserve toujours pas le bloc 47 pour AP.

**202 tests réussis.** Aucun SAVE ni test de crash dans cette phase. Ni source
corrompue « réparée », ni sauvegarde originale remplacée, ni journal AP remis
à zéro. La récupération étudiée est un fork d'inspection, pas une autorisation
de rejouer des items.

## Contrôle négatif avec l'échantillon réel

Entrée : `oras-connector-fq_i14ny/native-save/file-0002.bin`, SHA-256
`7cd9fa9c306da77da1f276a23432434eb65fabfa922983d8a8f5a93729eb63a5`.

Le lancement normal en `--seed-save` refuse :

```text
ValueError: ORAS block checksum mismatch: 3
```

L'échec intervient pendant validation du fichier, avant import d'archive ou
création du processus. Aucun `stdout.txt` d'EmuHawk, aucune lecture mémoire,
aucune écriture, aucun snapshot déclaré restaurable. Le binaire d'entrée reste
identique. Le résultat de `oras-connector-p7c2q0k_` reste **failed** ;
c'est le résultat attendu du contrôle négatif, pas une réussite de boot.

Cette distinction évite de transformer les samples intermédiaires du polling
en sauvegardes utilisables.

## Fork de récupération explicite

`--recover-from-snapshot` :

1. Exige un snapshot publié avec manifeste `oras_save_snapshot`.
2. Vérifie hash ROM, Program ID, SHA-256 de `main`, métadonnées Encore et 58 CRC.
3. Crée un nouveau profil `local/oras/profiles/oras-recovery-*`.
4. Copie le save et l'archive via le mécanisme de seed existant, sans restaurer
   le chemin `source` du manifeste et sans remplacer un profil existant.
5. Relit code, inventaire, EventWork, objet réservé, manager et record `main`,
   puis répète les lectures AP après reconnexion.

Combinaisons `--session`, autre `--seed-save`, SAVE instrumenté, Potion et macro
`--steps` personnalisée
interdites. L'option n'est jamais déclenchée automatiquement à la découverte
d'un fichier invalide. Le réglage explicite d'horloge demeure limité à la copie.

Essai réel : `local/oras/profiles/oras-recovery-s39bw9g9/`, depuis
`local/oras/backups/before-connector-8ny3zimx`, dernier snapshot **avant**
la sauvegarde instrumentée du rapport 021.

- Hash du checkpoint et du fork :
  `f7906a7ec9f61e3f9ce8e13510d35269b3b0cb99ff1fe909c6de066fa68e1887`.
- Horloge de copie : `2026-11-18T18:36:36`, comme le contrôle du rapport 021.
- Cold boot, deux connexions, 10 READ soumis dont deux sautés, quatre GUARD.
- 479 lectures Lua de préflight ; zéro WRITE ; aucun SAVE déclenché.
- Inventaire/EventWork et objet réservé conformes, 58 CRC, sortie propre 0.
- Snapshots pré/post CRC-validés, source et métadonnées inchangées.

La copie native plus récente du rapport 021 reste également intacte, SHA-256
`7bbd987cc202dfbea36585ca610729571284c65c23300f88524fbc62d80a1653`.
Il s'agit d'un **retour volontaire au checkpoint antérieur dans un autre
profil**, pas d'une préservation prouvée de toute progression postérieure.

## Récupérer un fichier n'est pas réconcilier les livraisons

Le résultat de fork conserve explicitement :

```text
restore_in_place = false
ap_binding_proven = false
next_delivery_index = null
live_delivery_authorized = false
journal_reset_or_replay_authorized = false
```

Un hash de fichier change lors d'une sauvegarde normale et ne suffit pas à
identifier un monde/slot AP ou à déterminer quels items sont déjà reçus.
Un rollback peut réintroduire une ancienne quantité d'items : elle n'est pas
un index de livraison. Un snapshot valide peut aussi être trop ancien.

Ce mode ne fait aucun appel au coordinateur ou au journal SQLite. Le
`GameInterface` réel reste absent ; son contrat exige toujours un ledger
game-side vérifié avant soumission. Aucun statut `uncertain` n'est converti
en `pending`, aucun item n'est renvoyé, aucun reçu durable n'est produit.

## Liaison du contrôleur par le code et les captures

`oras_save_lifecycle.py` vérifie des signatures A32 du lookup `0x0045D664` :

- Compte des records à `controller+8`.
- Pointeur des records à `controller+12`.
- Index multiplié par trois, puis décalé de quatre : stride de 48 octets.

La capture du fork confirme :

| Élément | Valeur |
|---|---|
| Préfixe du contrôleur | `0x08CDCFB8` |
| Backend à `+0` | `0x08CDD008`, candidat typé `gfl::fs::BackupSystem` |
| Compte à `+8` | 1 |
| Records à `+12` | `0x08CEDA80` |
| Manager au début du record | `0x08C6A9A8` |
| Taille 64 bits à record `+8` | `0x76000` |
| Chemin UTF-16 à record `+16` | `data:/main` |

Ce n'est plus une attribution par simple proximité d'une classe dans le heap :
les liens explicites concordent avec les offsets lus par le lookup natif.
Cela reste une liaison structurelle ; aucun breakpoint ne démontre les
arguments utilisés à chaque appel pendant SAVE.

À `0x0045D244`, une instruction stocke l'octet de retour du helper I/O à
`controller+24`, soit `0x08CDCFD0`. Sa valeur capturée est zéro. **Elle n'est pas
un flag busy/idle validé et ne doit pas autoriser une écriture AP.**
Sa stabilité pendant toute sauvegarde n'a pas été mesurée.

## Bloc réservé : reset et chargement

Les signatures du build OR exact corroborent :

- Getter `0x0045E180` : payload à `this+4` ; provider `0x0045E13C` :
  longueur 2 000.
- Appel constructeur `0x00116864` et branche de callback reset `0x0045E17C`
  vers le helper de zero-fill `0x0015EBCC`.
- Callback : getters de données et de taille, puis transfert à ce helper.
- Lecteur générique : `r1` reçoit le résultat du getter de données, `r2` la
  taille, avant l'appel backend `0x0045DBD8`. Le payload est donc une
  destination du chemin de lecture, pas seulement une copie de menu.

Ces contrôles sont statiques et bornés. Le fichier n'est pas modifié pour y
injecter un marqueur, et aucune méthode ARM n'est invoquée par l'outil.
Un roundtrip de payload non nul n'a pas été essayé. L'existence d'un reset
natif et du sérialiseur ne confère pas une propriété exclusive à AP.

## Fichiers et validation

- Créés : `tools/oras_save_lifecycle.py`, tests de liaison et de recovery,
  présent rapport et résultats JSON.
- Modifiés : lanceur, documentation, README client.
- **202 tests unitaires réussis** : snapshot incorrect/corrompu, mauvais build,
  refus des modes d'écriture, immutabilité de source, liens/tailles/chemins,
  ambiguïté et refus d'inférer un contexte sûr depuis le résultat I/O.
- Essais réels négatif et positif séparés dans les
  [preuves structurées](../research/recovery-fork-and-lifecycle-results.json).
- ROM, sauvegardes et sources de l'application AP fournies par l'utilisateur
  préservées ; aucun binaire privé distribué.

## Suite

Les protections contre fichier partiel et rollback doivent précéder la
reconnexion d'un futur writer, mais elles ne remplacent pas un enregistrement
AP explicitement possédé, une identité stable et une opération item/index
atomique. Ces conditions restent non démontrées ; livraison live bloquée.
Ni crash réel, ni restauration en place, ni récupération automatique testés.
La progression manuelle ne résout pas ces verrous.
