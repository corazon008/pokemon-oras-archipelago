# Rapport 001 — recherche initiale

Date : 17 novembre 2026.

## Résultat

La piste **BizHawk/Encore + connecteur générique Archipelago** reste prioritaire.
Les sources de BizHawk 2.11.1 exposent les API nécessaires à des essais mémoire.
Cela justifie des tests, **pas une déclaration de compatibilité ORAS**.

## Fichiers créés

- `.gitignore` : exclusions des copies personnelles et données locales.
- `README.md` : état réel et accès aux documents.
- `docs/research/sources.json` : commits de référence et empreinte de l'APWorld BW.
- `docs/research/audit-initial.md` : comparaison et limites techniques.
- `docs/research/bizhawk-validation.md` : protocole expérimental et critères de passage.
- `docs/reports/001-research.md` : présent rapport.

`Guidelines.md` et `ROMs/` laissés intacts. Aucun dépôt Git initialisé.

## Vérifications effectuées

| Vérification | Résultat |
|---|---|
| Lecture du cahier des charges local | Effectuée |
| Accès aux sources GitHub et identification des commits | Effectués |
| Identification du projet Noir/Blanc automatisé | BlastSlimey/PokemonBWAP, release 0.4.5 |
| SHA-256 de `pokemon_bw.apworld` | Conforme à l'empreinte de release |
| Manifeste `sources.json` | JSON valide, IDs uniques, formats commits/empreintes vérifiés |
| Liens Markdown locaux et références | Vérifiés ; blocs de code équilibrés |
| Liens amont de l'audit | 24 liens accessibles |
| Inspection du code Python BW | Statique uniquement, aucun chargement/exécution |
| Recherche de scripts Lua dans cette archive BW | Aucun ; documentation renvoie au connecteur AP générique |
| Domaines Encore/API Lua | Présents dans les sources de BizHawk 2.11.1 |
| Recherche des outils dans le `PATH` | Python, Git et Mono trouvés ; BizHawk non trouvé |
| Import disponible de `websockets` dans le Python courant | Non trouvé |
| Lancement ORAS, lecture/écriture RAM, sauvegarde | Non exécutés |
| Tests unitaires / serveur AP / end-to-end | Non exécutés : aucun code ORAS implémenté |

La recherche Web intégrée n'a pas abouti ; les sources ont été obtenues par
l'API GitHub et les fichiers bruts. Les téléchargements de recherche sont
temporaires sous `/tmp/opencode/oras-research/`, pas des dépendances du projet.
Les références durables sont les URLs, commits et empreintes documentés.

## Problèmes identifiés

1. `System Bus` peut masquer un accès non mappé par des zéros ou une écriture
   ignorée ; un accusé du connecteur ne démontre pas une modification du jeu.
2. L'API de taille mémoire utilise un entier 32 bits face à un domaine de 4 Gio.
3. Certains accès API retombent sur le domaine courant ; noms à vérifier explicitement.
4. Le mécanisme de livraison BW sépare écriture d'objet et compteur : robustesse
   crash à concevoir, pas à supposer.
5. Le plugin Gen6 ignore le booléen de vérification de version dans `PatchProcess`.
6. Les offsets de sauvegarde déchiffrée PKHeX ne sont pas des adresses RAM.
7. Les droits de copie du code BW ne sont pas établis par le dépôt consulté.
8. Chemin d'installation BizHawk et versions exactes des jeux locaux inconnus.

## Fonctionnalités effectivement validées

Aucune fonctionnalité ORAS/Archipelago en exécution. Seules provenance des
sources, intégrité de l'archive BW et observations statiques sont établies.

## Suite immédiate

Localiser ou préparer une installation BizHawk 2.11.1 isolée ; identifier édition,
région et mise à jour des copies de test, sans modifier les originaux.
Exécuter BH-01 à BH-05 du protocole avant toute écriture.

Le développement 3GX/Azahar reste différé. Le randomizer complet reste bloqué
par les preuves mémoire et le prototype end-to-end requis.
