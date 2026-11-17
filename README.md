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
  en métadonnées seulement.
- Title IDs et empreintes ROM relevés ; lecture d'un préfixe de code vérifiée
  sur les deux jeux, avant et après reconnexion.
- Partie jouable, sauvegarde et lecture/écriture d'une variable encore non validées.
- Aucun offset de progression, flag de location, item ou patch ORAS approuvé.
- Aucun APWorld ni client ORAS fonctionnel à ce stade.

## Documents

- [Audit comparatif initial](docs/research/audit-initial.md).
- [Protocole de validation BizHawk](docs/research/bizhawk-validation.md).
- [Références figées et empreinte de l'APWorld Noir/Blanc](docs/research/sources.json).
- [Rapport de recherche 001](docs/reports/001-research.md).
- [Premiers essais BizHawk — rapport 002](docs/reports/002-bizhawk-capabilities.md).
- [Connecteur TCP — rapport 003](docs/reports/003-bizhawk-tcp.md).
- [Identité ROM et lecture mémoire — rapport 004](docs/reports/004-rom-identity-and-read.md).
- [Sonde reproductible et lancement isolé](tools/README.md).

## Prochain jalon

Identifier les builds exacts, préparer une sauvegarde de test jouable et
vérifier la lecture d'une variable identifiée. Écriture
contrôlée et persistance viendront ensuite. Le développement du prototype
Archipelago vient après ces preuves, pas à leur place.

Les ROMs, sauvegardes, dumps mémoire et fichiers extraits ne doivent pas être
commités ou distribués. `.gitignore` fournit une protection de base, pas une
vérification du contenu des futurs patchs.
