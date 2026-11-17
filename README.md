# Pokémon ORAS — Archipelago

Intégration en cours d'étude de Pokémon Rubis Oméga et Saphir Alpha.
Les exigences de référence sont dans [Guidelines.md](Guidelines.md).

## Cible prioritaire

**BizHawk / Encore**, avec le connecteur Lua générique d'Archipelago et un
client Python. Aucun développement 3GX ou spécifique à Azahar n'est engagé.
Ces transports restent des alternatives uniquement en cas de blocage démontré.

## État réel

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
- Aucun flag de location, ID Archipelago ou patch ORAS approuvé.
- Aucun APWorld ni client ORAS fonctionnel à ce stade.
- Profil interactif isolé disponible ; sauvegarde OR jouable reçue et préservée.

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
- [Sonde reproductible et lancement isolé](tools/README.md).

## Prochain jalon

Identifier un événement permanent réel avec témoins négatifs et rechargement.
La boucle serveur et la livraison idempotente restent à développer ; l'essai
de quantité ne les remplace pas.

Les ROMs, sauvegardes, dumps mémoire et fichiers extraits ne doivent pas être
commités ou distribués. `.gitignore` fournit une protection de base, pas une
vérification du contenu des futurs patchs.
