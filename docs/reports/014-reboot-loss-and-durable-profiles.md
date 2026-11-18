# Rapport 014 — perte après redémarrage et stockage durable

Date : 18 novembre 2026.

## Incident et responsabilité

Après le redémarrage signalé par l'utilisateur, `/tmp/opencode` est vide.
Les profils jouables, checkpoints avant/après Pokédex, captures et lectures
binaires des essais précédents se trouvaient tous sous ce répertoire.
**Aucune sauvegarde indépendante du redémarrage n'avait été créée.**
Les annonces précédentes de checkpoints « préservés » ne garantissaient donc
pas leur conservation après reboot. C'est une erreur du workflow de l'agent.

Le code, tests et rapports committés existent encore. Les hashes consignés
ne permettent pas de reconstruire les sauvegardes.

Recherche effectuée dans les emplacements connus du projet : aucun `local/`
existant ; le répertoire de l'émulateur original contient un `main` de
483 328 octets et ses métadonnées de 16 octets, mais ce fichier ne possède
pas le marqueur ORAS attendu et est refusé :

```text
SHA-256 : b2f8d434dad6acddac0ab8f4224b96e1a13397fc37615c2a0c8331ab724d590a
Erreur : Save lacks the ORAS footer marker
```

Ce fichier est laissé intact. L'utilisateur confirme ne pas avoir d'autre
copie. Aucun sauvetage ou rechargement de la partie Pokédex n'est donc prétendu.
Les résultats des rapports 002–013 restent des observations historiques ;
leurs fichiers privés référencés dans `/tmp` ne sont plus disponibles.

## Correction

Les lanceurs de sauvegarde et du connecteur placent désormais les nouveaux
profils dans :

```text
local/oras/profiles/
```

Les sauvegardes ORAS existantes et valides font l'objet de snapshots séparés :

```text
local/oras/backups/<before-launch-ou-after-exit>-<identifiant>/
  00000001/main
  00000001.metadata
  snapshot.json
```

Le connecteur utilise les labels `before-connector` / `after-connector`.
Les snapshots sont créés avant le lancement, puis après l'arrêt du processus,
y compris après échec du diagnostic. Pas de suppression des anciennes copies.
Un profil sans `main` n'est pas présenté comme sauvegardé ; un fichier présent
mais invalide bloque le lancement ou fait échouer la sauvegarde de sortie.

Chaque snapshot :

- Vérifie les 58 CRC, le layout et le marqueur avant copie.
- Exige les métadonnées Encore de 16 octets.
- Compare des lectures successives pour rejeter un fichier en cours de mutation.
- Copie uniquement le fichier de sauvegarde et ses métadonnées.
- Enregistre SHA-256, identité ROM, Program ID, provenance et date UTC.
- Relit et revalide la copie avant publication.
- Utilise un répertoire provisoire `.partial-*`, puis un renommage ; une copie
  incomplète n'est pas publiée comme snapshot normal.
- Synchronise fichiers et répertoires ; permissions privées 0700/0600.
- N'écrase pas un snapshot antérieur.

Les profils persistants et les anciens profils `/tmp` encore présents sont
acceptés pour reprise. Les racines elles-mêmes et les chemins extérieurs sont
refusés. La reprise ne réimporte jamais une sauvegarde sur une progression.

`local/` est déjà ignoré par Git ; des protections supplémentaires couvrent les
archives exportées `00000001/main` et `00000001.metadata`. Ignorer dans Git ne
désactive pas Nextcloud : ces données privées peuvent suivre la synchronisation
du dossier de l'utilisateur. Elles ne doivent pas être partagées publiquement.

## Vérification et restauration

```sh
python3 tools/oras_profiles.py local/oras/backups/IDENTIFIANT
```

Vérifie marqueur, CRC, empreintes et identité dans le manifeste. Il s'agit
d'intégrité, pas de signature cryptographique ou d'authenticité indépendante.

Pour restaurer, importer `00000001/main` avec `--seed-save` dans un **nouveau**
profil ; garder `00000001.metadata` à côté du répertoire. Aucun remplacement
automatique de la sauvegarde courante. Le manifeste lie la référence à une ROM,
mais l'utilisateur doit sélectionner le bon build pour l'import.

Une fermeture de fenêtre ne remplace pas SAVE dans le jeu. Ces snapshots
conservent le dernier fichier réellement écrit, pas la RAM non sauvegardée.
Ils protègent contre la purge habituelle de `/tmp`, pas contre la perte du
disque, une suppression de `local/` ou un crash pendant une écriture du jeu.
Une copie sur un support indépendant reste nécessaire pour une vraie sauvegarde
contre la perte du stockage.

## Fichiers et tests

- Nouveau `tools/oras_profiles.py` : chemins persistants, snapshots et vérification.
- Lanceurs native/connector : réutilisation de ces chemins et backups pré/post.
- Nouveau `tests/test_oras_profiles.py`.
- `.gitignore`, README et documentation mis à jour.

**100 tests unitaires réussis**, dont 12 nouveaux :

- Copie toujours vérifiable après suppression du répertoire temporaire source.
- Snapshots distincts, sans écrasement.
- CRC, métadonnées ou identité incorrects refusés.
- Publication interrompue restant sous `.partial-*`.
- Permissions privées et chemins de reprise bornés.
- Lanceur natif testé avec processus factice : snapshot antérieur présent
  avant le lancement, puis second snapshot contenant le nouveau fichier.

Toutes ces données sont synthétiques et confinées aux dossiers des tests.
**Aucun nouveau résultat en jeu ni véritable reboot de validation n'est revendiqué.**

## Suite

Les essais live nécessitent de recréer ou fournir une sauvegarde jouable.
Avant tout nouveau test en RAM, vérifier qu'un snapshot réel est publié dans
`local/oras/backups/`. Le travail client/AP peut être préparé hors ligne, mais
aucun résultat synthétique ne doit être présenté comme la récupération de la
partie perdue ou comme une livraison en jeu réussie.
