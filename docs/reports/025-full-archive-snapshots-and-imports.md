# Rapport 025 — snapshots et imports d'archive complète

Date : 19 novembre 2026.

## Résultat

Le snapshot **v2** conserve tous les fichiers de l'archive native, les
sous-répertoires, y compris vides, et les métadonnées Encore. Son inventaire
contient chemins, tailles et SHA-256. V1 mono-fichier reste compatible.

Un fork réel contenant **trois fichiers et deux répertoires** passe cold boot,
lectures/reconnexion et vérification complète après fermeture. Un clone
volontairement altéré est refusé **avant lancement d'EmuHawk**.

**231 tests réussis.** Aucun ledger AP natif créé ni enregistré. Les fichiers
supplémentaires sont des fixtures de transport inertes, pas des preuves
d'application ou de persistance d'items.

## Format et capture

V2 conserve les champs historiques (ROM/title, hash de `main`, métadonnées,
58 CRC) et ajoute `archive_tree.files`, `archive_tree.directories` et
`archive_tree_sha256`, empreinte JSON canonique de l'inventaire complet.
La validation compare cet inventaire à une nouvelle lecture ; elle n'utilise
pas les chemins du manifeste comme instructions d'accès au disque.
Ajout, suppression, modification, renommage ou répertoire vide manquant :
refus. Versions inconnues et inventaires mal formés également refusés.

V1 reste strictement mono-fichier ; aucun ancien snapshot n'est réécrit.
Un `.partial-*` ne peut pas autoriser un import. Seule la validation interne
avant publication peut inspecter une copie non publiée.

`oras_archive.py` ouvre les fichiers relativement aux descripteurs des
répertoires avec `O_NOFOLLOW`. Liens symboliques, hardlinks et fichiers spéciaux
refusés. Chemins ASCII sans traversée ni séparateur Windows. Limites :
128 fichiers, 64 répertoires, profondeur 8, 8 MiB par fichier, 16 MiB au total,
256 caractères par chemin et 128 par composant.

Deux captures de contenu/inventaire et deux lectures des métadonnées doivent
concorder. Type, taille et changements pendant lecture sont contrôlés.
Le backup ne peut pas être créé dans son archive source.
Fichiers privés `0600`, dossiers `0700`, synchronisation, revalidation puis
publication par renommage depuis `.partial-*`.

Ces contrôles supposent une archive au repos : ils ne verrouillent pas le jeu
et ne prouvent pas la cohérence sémantique de deux fichiers individuellement
valides. Le manifeste n'est ni une signature d'authenticité ni un reçu AP.

## Import et récupération

Un import multi-fichiers exige un snapshot v2 vérifié et les identités ROM/title
explicites du lanceur. Un seed brut non manifesté reste mono-fichier.
Archive/métadonnées existantes : refus sans écrasement. L'import revérifie tous
les octets copiés. Un échec peut laisser un **profil partiel**, jamais lancé
ni réparé automatiquement ; la source reste intacte.

Répertoire et métadonnées ne sont pas publiés en une seule opération atomique :
le lanceur attend la fin des vérifications avant de démarrer.
Les archives multi-fichiers ne peuvent booter qu'en **nouveau fork explicite
en lecture seule** `--recover-from-snapshot`. Modes d'écriture, lanceur natif
interactif et réutilisation normale restent bloqués pour ces archives.

L'archive source entière est revérifiée après l'expérience, et le fork compare
tous ses fichiers/répertoires et ses métadonnées après fermeture.
Patchs, configuration émulateur et journal SQLite ne font pas partie de ce
snapshot d'archive : ce n'est pas un backup complet du profil.
Identité AP/index de livraison inconnus ; aucun replay autorisé.

## Essais réels

Source historique préservée :
`local/oras/backups/before-connector-8ny3zimx`.
Une copie dans `local/oras/profiles/oras-archive-vy9ne9xi` reçoit :

- `main`, original CRC-valide inchangé.
- `sidecar.bin`, fixture binaire de 31 octets, sans ledger.
- `proof/transport.bin`, texte de 50 octets indiquant la même limite.
- Répertoires `proof` et `empty`.

Snapshot publié : `local/oras/backups/full-archive-20ee5ihs`.
Inventaire SHA-256 :
`c7531464625eef9bae99f1912a6dbecb8b4b8b517afcce489a16f9e9d4985027`.

Fork `local/oras/profiles/oras-recovery-6kaxvr6c` :

- Build OR exact, horloge de copie `2026-11-18T18:36:36`, vitesse 400 %.
- Cold boot, deux connexions ; 10 READ soumis dont deux sautés, quatre GUARD.
- Préflight Lua : 479 lectures ; aucune écriture mémoire de l'outil.
- Inventaire/EventWork, objets et manager conformes ; sortie propre 0.
- Trois fichiers et deux répertoires identiques après boot ; métadonnées
  inchangées et snapshots pré/post v2 valides.
- Aucun SAVE, formatage ou second record enregistré par le jeu.

Le jeu stock utilise toujours `main` et ignore ici les fixtures supplémentaires.
Cela ne valide pas les callbacks natifs d'un futur fichier AP.

Contrôle négatif : clone privé `corrupt-control-not-a-backup`, dont seul
`sidecar.bin` est altéré. Essai `oras-recovery-a322jk1x` : statut **failed**,
`ValueError: Snapshot archive inventory/integrity mismatch`, zéro READ/WRITE,
aucun processus ni snapshot pré/post. Le snapshot publié reste intact.

## Fichiers et suite

Créés : `tools/oras_archive.py`, `tests/test_archive_snapshots.py`, rapport et
[résultats structurés](../research/full-archive-results.json).
Modifiés : profils/snapshots, imports/lanceurs, tests et docs.
**231 tests** : compatibilité v1, aller-retour complet, changements/omissions,
identités, chemins, limites, liens/fichiers spéciaux, refus d'écrasement et
snapshots non publiés.
Les **52 snapshots publiés** sont revérifiés : 49 v1 et trois v2 valides.

La dépendance « préserver un sidecar sans l'omettre » est levée dans l'outillage.
Prochaine étape : objet/fichier AP réellement enregistré par le patch, migration
non destructive sur copie et comportement explicite si le fichier manque.
Reset, SAVE/reload non nul, identité monde/slot et atomicité item/index restent
à démontrer. Livraison live toujours bloquée.
