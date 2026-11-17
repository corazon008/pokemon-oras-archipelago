# Validation expérimentale BizHawk / Encore

Statut au 17 novembre 2026 : **menu de langue atteint sur les deux jeux et
inventaire Lua validé**. Gameplay, sauvegarde et accès à une variable non validés.
Voir le [rapport 002](../reports/002-bizhawk-capabilities.md) et les
[mesures](bizhawk-results.json).

## Conditions préalables

- Commencer avec BizHawk **2.11.1**, référence figée dans `sources.json`.
  Toute autre version doit avoir sa propre ligne de résultats.
- Utiliser des copies personnelles des jeux et des sauvegardes de test.
- Copier le profil utilisateur de l'émulateur avant les essais. Désactiver
  toute synchronisation des sauvegardes susceptible d'écraser la référence.
- Ne pas modifier les ROMs originales ni les sauvegardes principales.
- Utiliser une installation Archipelago identifiée, avec son connecteur Lua
  générique et les modules Lua qui l'accompagnent.

Sous Linux, le README de BizHawk 2.11.1 indique Mono, OpenAL, Lua 5.4 et
`lsb_release`. L'absence de `dotnet` ne suffit pas à conclure que la release
ne peut pas fonctionner. Aucun paquet système n'est installé par cet audit.

## Fiche obligatoire pour chaque configuration

Consigner :

- OS, version exacte de BizHawk, core Encore, modèle 3DS émulé.
- Édition OR/AS, région, langue, Title ID, révision de base et mise à jour.
- Empreinte locale du jeu et des composants influençant le code exécuté.
  Ne publier aucun fichier de jeu, clé ou identifiant personnel.
- Identifiant de sauvegarde de test, point de progression, empreinte avant/après.
- Version/commit Archipelago et version du connecteur Lua.
- Résultats observés, logs et étapes reproductibles.

Toute donnée non obtenue reste « inconnue », jamais déduite du nom du fichier ROM.

## Séquence de tests

| Test | Manipulation | Preuve exigée |
|---|---|---|
| BH-01 | Lancer chaque édition sous Encore | Titre, accès à une partie jouable, absence de blocage observé |
| BH-02 | Sauvegarder en jeu, fermer proprement, relancer | Partie relue sans savestate, progression conservée |
| BH-03 | Énumérer domaines et API Lua | Noms exacts, tailles observées, version Lua, système renvoyé |
| BH-04 | Lire une variable identifiée et non sensible | Valeur corrélée à une action réelle, répétable |
| BH-05 | Charger le connecteur AP et lire depuis Python | Même valeur que Lua et jeu, aucune écriture |
| BH-06 | Écrire un changement minime sur sauvegarde jetable | Gardes satisfaites, relecture conforme, effet visible |
| BH-07 | Sauvegarder, fermer, relancer après BH-06 | Modification conservée dans la sauvegarde native |
| BH-08 | Identifier un événement permanent | Faux avant, vrai après, vrai après rechargement ; témoins négatifs |
| BH-09 | Déconnecter/reconnecter le pont local | Retour à un état identifié, aucun accès sur pointeur périmé |
| BH-10 | Tester chargement d'état séparément | Caches invalidés ; aucune livraison automatique avant réconciliation |

BH-06 exige BH-01 à BH-05 réussis et une structure documentée pour **la version
exacte**. Pas de « test » consistant à écrire à une adresse arbitraire.
BH-08 peut être étudié en lecture seule avant BH-06 si l'événement est identifié.

## Inventaire Lua : précautions

API repérées dans les sources, à vérifier dans la console réelle :

- `client.getversion()`, `emu.getsystemid()`.
- `memory.getmemorydomainlist()`.
- `memory.getmemorydomainsize(domain)`, `memory.usememorydomain(domain)`.
- `memory.read_bytes_as_array(address, length, domain)`.
- `memory.write_bytes_as_array(address, bytes, domain)` : **réservée à BH-06**.

Ne pas lire d'adresse dans le seul but de prouver que Lua existe.
L'inventaire des domaines ne nécessite aucune écriture ni offset ORAS.

Points particuliers :

1. Parcourir la table des domaines en tenant compte de son indexation depuis zéro.
2. Vérifier qu'un nom existe avant toute mesure ou lecture.
3. Toujours transmettre explicitement le domaine lors des accès.
4. Mesurer le résultat de taille de `System Bus` ; le cast 32 bits des sources
   peut masquer son espace de 4 Gio.
5. Zéro lu n'est pas une preuve que la variable existe ou que la page est mappée.

## Identifier une première variable

Commencer par une donnée observable et modifiable naturellement dans le jeu :
par exemple la quantité d'un objet ordinaire déjà possédé. Ce n'est pas encore
un choix d'item Archipelago.

Pour chaque candidat :

1. Noter provenance et hypothèse : source exacte, symbole ou recherche différentielle.
2. Observer plusieurs valeurs par des actions natives, y compris une baisse.
3. Vérifier que voisins, ID, quantité, limites et poche sont cohérents.
4. Refaire après changement de carte, menu, sauvegarde et redémarrage.
5. Distinguer copie d'interface, donnée active et donnée sérialisée.
6. Enregistrer le domaine et les éventuelles chaînes de pointeurs.

L'inventaire du plugin Gen6 donne des pistes ; le layout PKHeX donne des
structures de fichier. Aucun des deux ne remplace ces vérifications RAM.

## Écriture contrôlée

Une écriture peut corrompre une sauvegarde. Utiliser uniquement une copie jetable,
avec sauvegarde de référence récupérable.

- Refuser édition/mise à jour inconnue, partie non chargée, combat, sauvegarde en
  cours ou état non identifié comme sûr.
- Lire ID, quantité, structure et pointeurs attendus avant modification.
- Appliquer un changement minimal, borné et documenté. Ne pas remplir une poche.
- Utiliser les gardes du connecteur pour éviter d'écraser une valeur modifiée.
- Relire immédiatement et vérifier l'effet à l'écran.
- En cas d'incohérence : arrêter les écritures et conserver les logs ; pas de
  tentative automatique de restauration à une adresse devenue incertaine.
- Vérifier ensuite sauvegarde native et rechargement, pas seulement un savestate.

## Passage au prototype Archipelago

Après validation des accès nécessaires :

1. Implémenter `GameInterface` et l'adaptateur BizHawk, avec profils OR/AS.
2. Définir une location et un item dont les preuves ont été établies.
3. Réutiliser `BizHawkClientContext` et le connecteur générique.
4. Produire un APWorld minimal puis générer une seed locale.
5. Tester événement → `LocationChecks` → `ReceivedItems` → jeu → sauvegarde.
6. Tester doublons, reconnexion, inventaire plein et crashs avant/après application.

Le premier succès sur une édition n'implique pas le succès sur l'autre.
La matrice reste indépendante :

| Configuration | Démarrage/sauvegarde | Lua/domaines | Lecture | Écriture/persistance | Événement | E2E AP |
|---|---|---|---|---|---|---|
| Rubis Oméga — build à identifier | Menu de langue ; sauvegarde non testée | Inventaire validé | Non testé | Non testé | Non testé | Non testé |
| Saphir Alpha — build à identifier | Menu de langue ; sauvegarde non testée | Inventaire validé | Non testé | Non testé | Non testé | Non testé |

## Politique de repli

Ne pas abandonner BizHawk sur un seul échec de configuration.
Consigner erreur, version, reproduction et tentative de résolution.
Un passage à Azahar ou 3GX exige un blocage documenté empêchant les accès
nécessaires, pas seulement une préférence de transport.
