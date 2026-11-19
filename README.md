# Pokémon ORAS — Archipelago

Intégration en cours d'étude de Pokémon Rubis Oméga et Saphir Alpha.
Les exigences de référence sont dans [Guidelines.md](Guidelines.md).

## Cible prioritaire

**BizHawk / Encore**, avec le connecteur Lua générique d'Archipelago et un
client Python. Aucun développement 3GX ou spécifique à Azahar n'est engagé.
Ces transports restent des alternatives uniquement en cas de blocage démontré.

## État réel

**18 novembre 2026 : incident de stockage.** Les profils et checkpoints sous
`/tmp/opencode` ont disparu au reboot ; aucune copie durable du Pokédex n'avait
été créée. Code et rapports conservés ; une nouvelle partie de début de jeu
a depuis été créée et sauvegardée durablement (rapport 015).
Les nouveaux profils et snapshots sont stockés sous `local/oras/` (ignoré par Git).
Voir le [rapport 014](docs/reports/014-reboot-loss-and-durable-profiles.md).

Résultats historiques du 17 novembre :

- Première analyse statique d'Archipelago, Émeraude, Noir/Blanc et Gen6 CTRPF réalisée.
- Domaines mémoire et API Lua d'Encore identifiés dans les sources de BizHawk 2.11.1.
- Les deux jeux atteignent le menu de langue ; inventaire Lua des domaines validé.
- TCP Python ↔ connecteur AP et une reconnexion validés sur les deux jeux,
  en métadonnées ; inventaire également validé sur OR.
- Title IDs et empreintes ROM relevés ; lecture d'un préfixe de code vérifiée
  sur les deux jeux, avant et après reconnexion.
- OR : sauvegarde native rechargée en jeu, 58 CRC vérifiés, inventaire RAM
  concordant avec la sauvegarde et Potion ×1 affichée dans le sac.
- OR : variation native Potion 1 → 0 et persistance après sauvegarde/redémarrage
  validées dans la copie.
- OR : lecture d'inventaire via API AP, écriture expérimentale gardée Potion
  1 → 2, reconnexion et persistance native vérifiées sur copie isolée.
- OR : bloc EventWork retrouvé ; candidat horloge/conversation à l'étage
  observé avec témoins négatifs, sauvegarde et rechargement. Suite manuelle
  3 → 4 et lecture API AP après reconnexion validées, pas sa permanence globale.
- OR : checkpoint avant Pokédex préservé ; candidat 2722 faux dans le fichier
  et via le pont AP, puis vrai après réception native, sauvegarde et redémarrage.
  Interface Pokédex fonctionnelle et relecture AP après reconnexion vérifiées.
- Aucun flag de location, ID Archipelago ou patch ORAS approuvé.
- Aucun APWorld ni client ORAS fonctionnel à ce stade.
- Sauvegarde OR jouable précédemment reçue ; copies temporaires perdues au reboot.

Avancées du 18 novembre :

- Nouvelle sauvegarde OR à Potion ×1 : 58 CRC, backups hors `/tmp`, rechargement
  jouable et deux lectures API AP conformes ; aucun octet écrit.
- Fondations [client hors ligne](oras_client/README.md) : `GameInterface`,
  journal SQLite et suspension des livraisons incertaines, testés sur faux backend.
- Aucun compteur atomique item/index vérifié dans ORAS : livraison live bloquée.
- Shim GUARD strict : erreurs et domaines invalides refusés ; contrôle réel
  sans écriture après reconnexion. Le bloc 47 « Unused » n'est pas réservé à AP.
- Objets inventaire/EventWork corroborés par le code ; candidat du bloc 47
  localisé par en-tête non nul, retrouvé à froid et relu après reconnexion.
  Aucun stockage AP ni cycle de sérialisation approuvé.
- Manager natif OR corroboré : 58 blocs réguliers + métadonnées, 54 offsets
  prédits concordants, footer et CRC identiques. Reset/CRC repérés statiquement,
  pas leur calendrier d'exécution ni une transaction item/index.
- Record `data:/main` relié au manager, candidats BackupFile/BackupSystem et
  boucles de transfert repérés ; layout complet reproduit statiquement.
  Aucun SAVE déclenché dans cette phase, aucune atomicité démontrée.
- 19 novembre : SAVE natif instrumenté sur copie, 1 357 frames, rechargement
  à froid réussi. Un état backing CRC-invalide est observé avant le fichier final.
  Source préservée ; horloge contrôlée explicitement sur copie, pas de byte masqué.
- Échantillon CRC-invalide refusé avant boot ; fork de récupération depuis snapshot
  vérifié rechargé sans remplacer de profil ni réinitialiser le journal AP.
  Liaison contrôleur/record et chemins reset/load corroborés, sans autorisation d'écriture.
- Bootstrap natif OR exécuté via IPS : nouvelle page RAM explicitement ajoutée,
  marqueur relu après reconnexion et témoins sans hook conformes. Sauvegardes
  inchangées ; ce mécanisme ne fournit pas encore de stockage AP persistant.
- Appels natifs constructeur/register observés : capacité un, compteur `0 → 1`,
  record `main` conforme. Snapshots/imports refusent désormais d'omettre un sidecar
  supplémentaire ; aucune allocation persistante AP ni migration d'archive réalisée.

## Documents

- [Audit comparatif initial](docs/research/audit-initial.md).
- [Protocole de validation BizHawk](docs/research/bizhawk-validation.md).
- [Références figées et empreinte de l'APWorld Noir/Blanc](docs/research/sources.json).
- [Rapport de recherche 001](docs/reports/001-research.md).
- [Premiers essais BizHawk — rapport 002](docs/reports/002-bizhawk-capabilities.md).
- [Connecteur TCP — rapport 003](docs/reports/003-bizhawk-tcp.md).
- [Identité ROM et lecture mémoire — rapport 004](docs/reports/004-rom-identity-and-read.md).
- [Profil privé de sauvegarde — rapport 005](docs/reports/005-private-save-profile.md).
- [Rechargement et lecture d'inventaire — rapport 006](docs/reports/006-native-reload-and-inventory.md).
- [Variation native et persistance — rapport 007](docs/reports/007-native-quantity-and-persistence.md).
- [Inventaire via AP et première écriture — rapport 008](docs/reports/008-connector-inventory-and-write.md).
- [Candidat d'événement natif — rapport 009](docs/reports/009-native-clock-event-candidate.md).
- [Contournement clavier d'une entrée bloquée — rapport 010](docs/reports/010-keyboard-input-workaround.md).
- [Suite manuelle et lecture d'événement via AP — rapport 011](docs/reports/011-clock-event-follow-up-and-ap-read.md).
- [Témoin avant réception du Pokédex — rapport 012](docs/reports/012-pokedex-before-checkpoint.md).
- [Réception du Pokédex et persistance — rapport 013](docs/reports/013-pokedex-event-and-persistence.md).
- [Perte au reboot et profils durables — rapport 014](docs/reports/014-reboot-loss-and-durable-profiles.md).
- [Nouvelle sauvegarde durable — rapport 015](docs/reports/015-new-durable-save-verification.md).
- [Fondations du client hors ligne — rapport 016](docs/reports/016-offline-delivery-foundations.md).
- [Recherche de stockage et gardes strictes — rapport 017](docs/reports/017-ledger-storage-and-strict-guards.md).
- [Exécutable et objets de sauvegarde — rapport 018](docs/reports/018-executable-and-save-objects.md).
- [Manager natif de sauvegarde — rapport 019](docs/reports/019-native-save-manager.md).
- [Records de fichier et sérialisation — rapport 020](docs/reports/020-save-records-and-serialization.md).
- [Sauvegarde native instrumentée — rapport 021](docs/reports/021-native-save-observation.md).
- [Forks de récupération et reset/load — rapport 022](docs/reports/022-recovery-forks-and-load-reset.md).
- [Bootstrap natif et RAM ajoutée — rapport 023](docs/reports/023-native-bootstrap-and-owned-ram.md).
- [Trace native de l'enregistrement des fichiers — rapport 024](docs/reports/024-native-save-registration-trace.md).
- [Sonde reproductible et lancement isolé](tools/README.md).

## Prochain jalon

Vérifier une méthode d'application atomique item + index, puis leur persistance
commune, avant de brancher l'interface client sur des écritures réelles.
La boucle serveur et la livraison idempotente restent à développer ; l'essai
de quantité ne les remplace pas.

Les ROMs, sauvegardes, dumps mémoire et fichiers extraits ne doivent pas être
commités ou distribués. `.gitignore` fournit une protection de base, pas une
vérification du contenu des futurs patchs.
