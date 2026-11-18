# Rapport 016 — interface et journal de livraison hors ligne

Date : 18 novembre 2026.

## Résultat et frontière

Ajout d'une interface abstraite **`GameInterface`** et d'un journal SQLite pour
préparer réception, ordre, accusés et réconciliation des items.

**Aucun adaptateur ORAS en écriture, client WebSocket ou APWorld n'est ajouté.**
Les tests utilisent un faux backend qui possède un compteur atomique de
livraison ; un tel compteur **n'a pas été identifié ni implémenté dans ORAS**.
Le succès de ces tests n'est pas une livraison réussie dans le jeu.

Le [rapport 015](015-new-durable-save-verification.md) décrit séparément la
nouvelle sauvegarde réelle, ses backups durables et sa lecture via le pont.
Cette phase de code ne touche pas à cette sauvegarde.

## Contrat de l'interface

`oras_client/game_interface.py` sépare :

- Identité de génération, équipe, slot, build ROM et liaison stable de sauvegarde.
- Item reçu, index et provenance réseau, sans définir d'identifiants AP réels.
- Observation du jeu : identité, époque runtime, état sûr et index éventuel.
- Accusé d'application RAM après gardes et relecture.
- Preuve distincte de persistance native, liée à l'époque et au fichier sauvegardé.

L'empreinte de génération et la liaison de sauvegarde sont des contrats pour le
futur adaptateur, **pas des champs mémoire inventés**. Le SHA-256 changeant
d'un fichier `main` ne constitue pas à lui seul une identité stable de partie.

L'absence de compteur vérifié est représentée par `None`. Le coordinateur
refuse alors de soumettre un item. Ni la quantité d'une Potion ni un flag
de scénario ne remplacent un index de livraison.

## Journal et transitions

`oras_client/delivery.py` :

1. Enregistre les items par indices contigus ; doublon identique ignoré.
2. Refuse trou d'index ou contenu contradictoire pour un index existant.
3. Lie le journal à une seule identité ; une autre génération/partie est refusée.
4. Vérifie l'état et réclame atomiquement la tête de file.
5. Commit l'intention `submitted` **avant** tout appel pouvant écrire en RAM.
6. Enregistre `ram_ack` seulement après accusé correspondant à la commande.
7. N'avance vers `committed` qu'après preuve de sauvegarde native.

Une réponse perdue, une annulation ou un accusé incohérent laisse une commande
incertaine. Les états `submitted`, `ram_ack` et `uncertain` interdisent une
nouvelle application automatique, même après réouverture du journal.

`confirm_saved()` consulte le backend en lecture. Une preuve doit correspondre
à l'identité, à l'époque courante, à l'index attendu et à l'index observé du jeu,
avec une empreinte de sauvegarde correctement formée. Sans preuve, aucune
autorisation de réessai n'est déduite.

SQLite utilise transactions, `synchronous=FULL`, journal DELETE, permissions
privées et synchronisation du répertoire parent lors de la création.
Le chemin par défaut est `local/oras/client/delivery.sqlite3`, ignoré par Git.
Un fichier inconnu ou incompatible n'est jamais réinitialisé.

## Limites importantes

- Le futur adaptateur doit prouver application atomique **item + index**, puis
  persistance commune dans un fichier CRC-valide.
- Une empreinte bien formée n'est pas une preuve en soi : la vérification
  effective du fichier relève du contrat du backend, non encore implémenté.
- Le compteur doit appartenir exclusivement au flux identifié.
- Une preuve venant d'un fichier ancien après rollback ne doit pas être acceptée.
- Le défaut amont où une exception de GUARD peut laisser exécuter la suite d'un
  lot reste ouvert ; l'expérience Potion n'implémente donc pas ce contrat.
- Les refus connus du backend suspendent aussi la livraison ; aucune reprise
  ou écriture de récupération automatique n'est proposée dans cette version.
- Un journal actif ne doit pas être fusionné entre PC via Nextcloud.
- Les snapshots natifs ne copient pas le journal ; perte de DB ou restauration
  d'une partie demande réconciliation, pas remise à zéro aveugle des indices.
- Ce mécanisme ne démontre pas un « exactly once » réel sur ORAS.

## Tests

**117 tests unitaires réussis**, dont 17 nouveaux sur le client :

- Rejeu identique, conflit et trou d'indices.
- Accusé RAM insuffisant pour avancer la file.
- Commit après sauvegarde, puis fermeture/réouverture sans seconde application.
- Item suivant bloqué tant que le premier n'est pas persisté.
- Réponse perdue, annulation et accusé incorrect.
- Crash simulé après enregistrement de l'intention : pas de renvoi.
- Compteur absent, index erroné et état non sûr refusés.
- Mauvaise génération/partie et preuve périmée refusées.
- Fichier inconnu préservé et double réclamation de la tête refusée.
- Types de payload invalides refusés.

Les crashs sont des frontières simulées et des réouvertures SQLite, pas des
tests de panne électrique. Les identifiants et empreintes utilisés sont
synthétiques ; aucun paquet serveur réel n'est traité.

Fichiers créés : `oras_client/__init__.py`, `game_interface.py`, `delivery.py`,
`oras_client/README.md`, `tests/test_delivery.py` et présent rapport.

## Suite

Étudier une méthode réelle pour stocker et sauvegarder l'index avec l'item,
et identifier un contexte sûr. Tant que ces prérequis ne sont pas vérifiés,
ne pas relier le coordinateur à une écriture mémoire. La boucle serveur
minimale et le test de livraison en jeu restent des jalons distincts.
