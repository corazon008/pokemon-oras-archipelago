# Projet : Pokémon ORAS Archipelago Integration

## Mission

Développer une intégration complète de Pokémon Rubis Oméga et Pokémon Saphir Alpha dans Archipelago Multiworld.

L'objectif est de permettre à un joueur de jouer à une version modifiée d'ORAS, dans laquelle les objets, les badges, les CS, les Pokémon et les événements de progression peuvent être randomisés et synchronisés avec d'autres jeux via un serveur Archipelago.

Les deux versions doivent être supportées.

## 1. Recherche préalable obligatoire

Avant toute implémentation :

1. Étudier le fonctionnement interne d'Archipelago.
2. Étudier le World Pokémon Émeraude dans le dépôt officiel Archipelago.
3. Étudier le protocole réseau Archipelago.
4. Étudier pk3DS.
5. Analyser le code source de Gen6 CTRPluginFramework.
6. Étudier Luma3DS, LayeredFS et le format des plugins 3GX.
7. Identifier les mécanismes internes de progression de Pokémon ORAS.

Ne pas inventer d'adresses mémoire, de game flags ou de structures internes. Toute adresse doit être identifiée, documentée et vérifiée sur une version précise du jeu.

## 2. Architecture obligatoire

Séparer le projet en trois composants.

### A. Archipelago World

Développement Python dans `worlds/pokemon_oras/`.

Responsabilités :

- Définition des items.
- Définition des locations.
- Définition des régions.
- Définition des règles d'accessibilité.
- Génération du pool d'items.
- Gestion des options YAML.
- Définition de la condition de victoire.
- Génération des données nécessaires au patch.

S'inspirer de Pokémon Émeraude sans copier aveuglément ses mécanismes spécifiques à la GBA.

### B. Game Client

Développement Python.

Responsabilités :

- Connexion au serveur Archipelago par WebSocket.
- Gestion du protocole Archipelago.
- Réception des items.
- Transmission des locations.
- Gestion des reconnexions.
- Persistance des index d'items.
- Synchronisation des données.
- Communication avec le plugin du jeu.

Utiliser une architecture modulaire avec une interface abstraite `GameInterface`.

### C. Plugin Pokémon ORAS

Développement C/C++ avec devkitPro et CTRPluginFramework.

Responsabilités :

- Hooks sur les événements du jeu.
- Détection des locations.
- Lecture des flags de progression.
- Modification de l'inventaire.
- Application des items reçus.
- Modification des flags.
- Communication bidirectionnelle avec le client externe.
- Gestion des erreurs et des confirmations d'exécution.

Étudier la faisabilité d'un transport TCP sur console réelle et d'une interface mémoire ou IPC sur émulateur.

## 3. Système d'items

Prévoir au minimum :

- Les 8 badges.
- Les CS.
- Les objets clés.
- Les vélos.
- Les Pokémon de départ.
- Les Pokémon cadeaux.
- Les Pokémon légendaires.
- Les CT.
- Les objets consommables.

Les items doivent disposer d'identifiants uniques et stables.

Prévoir les classifications progression, useful et filler.

L'application d'un item doit être idempotente et résister aux reconnexions.

## 4. Système de locations

Prévoir :

- Les objets au sol.
- Les objets cachés.
- Les récompenses de PNJ.
- Les combats d'arène.
- Les événements scénaristiques.
- Les rencontres légendaires.
- Les Pokémon cadeaux.
- Les récompenses de la Ligue.
- Les objectifs secondaires.

Chaque location doit avoir un identifiant unique et une condition de validation précise.

Ne pas utiliser uniquement les changements de carte pour détecter les locations.

## 5. Logique de progression

Créer un graphe de régions représentant la progression réelle dans Hoenn.

Les règles doivent tenir compte :

- Des badges.
- Des CS.
- Des objets clés.
- Des événements scénaristiques.
- Des accès géographiques.
- Des combats obligatoires.

Distinguer la possession d'une CS de son autorisation d'utilisation par un badge.

Prévoir plusieurs objectifs de victoire configurables.

## 6. Compatibilité Rubis Oméga / Saphir Alpha

Créer une architecture commune et des adaptateurs propres à chaque version.

Vérifier les différences :

- De scripts.
- De progression.
- De Pokémon légendaires.
- De rencontres.
- D'objets exclusifs.
- De versions régionales.

Ne pas supposer que les offsets mémoire sont identiques entre les versions.

## 7. Fiabilité

Implémenter :

- Une persistance des items reçus.
- Une protection contre les duplications.
- Une file d'attente des commandes.
- Des accusés de réception.
- Une resynchronisation après reconnexion.
- Une protection contre les sauvegardes corrompues.
- Des logs détaillés.
- Des tests unitaires.

## 8. Ordre de développement

Ne pas commencer par le randomizer complet.

Ordre obligatoire :

1. Analyse du jeu et identification des structures.
2. Prototype du plugin 3GX.
3. Démonstration de lecture et écriture d'un item.
4. Détection d'un événement de progression.
5. Communication bidirectionnelle entre Python et le plugin.
6. Client Archipelago fonctionnel.
7. APWorld minimal.
8. Test end-to-end sur un serveur local.
9. Extension des items et locations.
10. Implémentation complète de la logique.
11. Compatibilité avec les deux versions.
12. Tests de régression et documentation.

## 9. Premier objectif concret

Produire un prototype minimal démontrant les fonctionnalités suivantes :

- Lancement de Pokémon ORAS modifié.
- Détection d'un événement précis dans le jeu.
- Transmission de cet événement au client Python.
- Envoi d'une location check à un serveur Archipelago local.
- Réception d'un item depuis le serveur.
- Transmission de cet item au plugin.
- Application de l'item dans Pokémon ORAS.
- Persistance de l'item après sauvegarde et redémarrage.

Ce prototype doit fonctionner avant d'entreprendre la création du randomizer complet.

## 10. Contraintes de développement

- Code modulaire et documenté.
- Python pour l'APWorld et le client.
- C/C++ pour le plugin 3DS.
- Identifiants centralisés.
- Séparation stricte entre logique Archipelago et logique du jeu.
- Aucun offset ou flag inventé.
- Utilisation de copies personnelles des jeux pour les tests.
- Ne jamais distribuer les ROM originales ou leurs fichiers propriétaires.

À chaque phase, produire un rapport technique contenant les fichiers créés, les tests réalisés, les problèmes identifiés et les fonctionnalités effectivement validées.

En cas de blocage technique, rechercher une solution alternative et documenter les limites plutôt que simuler une implémentation fonctionnelle.

## 11. Analyse comparative des implémentations Pokémon existantes

Avant de développer Pokémon ORAS, effectuer un audit technique de trois projets :

1. Archipelago Pokémon Émeraude (intégration officielle).
2. Archipelago Pokémon Noir et Blanc (implémentation communautaire).
3. Gen6 CTRPluginFramework (support Pokémon ORAS).

Pour Pokémon Noir et Blanc, étudier particulièrement :

- Le code de `worlds/pokemon_bw/`.
- Le mécanisme de patch ROM.
- Le fonctionnement du connecteur BizHawk.
- Les scripts Lua.
- La détection des événements.
- La gestion des objets reçus.
- La gestion des roadblocks.
- La persistance et la synchronisation des données.

Produire un document comparatif comprenant :

- Les composants réutilisables.
- Les composants dépendants de la Nintendo DS.
- Les composants dépendants de BizHawk.
- Les mécanismes à réimplémenter pour Nintendo 3DS.
- Les différences entre le moteur Pokémon de génération V et celui de génération VI.

Ne pas commencer le développement complet d'ORAS avant d'avoir produit cet audit.

## Priorité : intégration BizHawk 3DS

BizHawk prend en charge la Nintendo 3DS avec le cœur Encore.

Avant de développer un plugin 3GX ou un client spécifique à Azahar :

1. Vérifier que Pokémon Rubis Oméga et Saphir Alpha fonctionnent correctement sur le cœur Encore.
2. Vérifier que les API Lua de BizHawk exposent la mémoire 3DS.
3. Tester la lecture d'une variable du jeu.
4. Tester une écriture mémoire contrôlée.
5. Étudier le connecteur BizHawk utilisé par Archipelago Pokémon Noir et Blanc.
6. Développer un prototype capable de détecter une location et de recevoir un item Archipelago.
7. Documenter les limitations éventuelles du cœur Encore.

Si les API nécessaires sont disponibles, privilégier BizHawk pour la première version du projet.

Conserver Azahar et un plugin 3GX comme solutions alternatives.

Ne pas supposer que toutes les API mémoire fonctionnent sur Encore sans validation expérimentale.
