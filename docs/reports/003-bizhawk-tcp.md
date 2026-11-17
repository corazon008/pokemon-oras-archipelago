# Rapport 003 — connecteur TCP Archipelago sous Encore

Date : 17 novembre 2026.

## Résultat

**Le connecteur générique Archipelago fonctionne sous BizHawk/Encore sur les deux
éditions pour les métadonnées testées.**

Pour chaque jeu : connexion Python, négociation de version, requêtes de métadonnées,
déconnexion puis reconnexion et répétition des requêtes. Les deux processus
EmuHawk se ferment proprement à la demande du lanceur.

Ce résultat ne valide ni la lecture d'une variable ORAS, ni une location, ni une
livraison d'item, ni une connexion à un serveur Archipelago.

## Réutilisation effective

Le lanceur télécharge, dans un dossier temporaire privé :

- Le connecteur Lua générique, **sans modification**.
- Ses modules `base64`, `json`, `socket` et compatibilité Lua.
- La bibliothèque native **Linux x86_64 / Lua 5.4** et sa licence.
- `worlds/_bizhawk/__init__.py`, API Python amont, **sans modification**.

Toutes les dépendances sont figées au commit Archipelago documenté et vérifiées
par SHA-256 avant import ou chargement. Le verrou est
[`tools/ap_connector.lock.json`](../../tools/ap_connector.lock.json).
Aucun binaire tiers n'est ajouté au dépôt et aucun paquet système n'est installé.

Un petit wrapper Lua ajoute seulement une fermeture via fichier local et une
limite de durée. Les handlers réseau et le protocole AP ne sont pas réécrits.

## Échanges réellement observés

| Échange | Réponse commune aux deux jeux |
|---|---|
| `VERSION` | `1` |
| `PING` | `PONG` |
| `SYSTEM` | `3DS` |
| `MEMORY_SIZE` sur `FCRAM` | 268 435 456 |
| `MEMORY_SIZE` sur `System Bus` | 0 |

Chaque série est exécutée deux fois. La première connexion utilise le port
43055 ; la reconnexion utilise 43056 dans les deux essais.
Le changement de port est compatible avec le comportement observé du connecteur,
et l'API Python amont le gère.

Avant lancement, l'outil exige que les ports du connecteur soient libres afin
de ne pas se connecter volontairement à une instance existante.
Le précontrôle n'est pas un mécanisme d'authentification : utiliser ce diagnostic
sur une machine locale de confiance, sans lancer un autre connecteur en parallèle.

**Aucun paquet `READ`, `WRITE`, `GUARD` ou `LOCK` envoyé.** Les requêtes de taille
ne lisent pas le contenu de la RAM du jeu. Le service amont expose néanmoins
des commandes mémoire sur loopback : ne pas le rediriger vers un réseau externe.

Les [résultats structurés](../research/bizhawk-connector-results.json) renvoient
aux logs locaux. Les profils originaux, sauvegardes et ROMs ne sont pas modifiés
par le lanceur ; chaque essai utilise une nouvelle copie isolée.

## Limites identifiées

- Le chargement des dépendances manquantes résout le problème LuaSocket observé
  au rapport 002 ; aucune alternative à BizHawk n'est nécessaire à ce stade.
- La version étudiée du serveur Lua essaie six ports, 43055–43060 inclus, tandis
  que l'API Python amont en essaie cinq, 43055–43059. Les essais n'ont pas utilisé
  le dernier port ; la saturation complète de la plage n'est pas validée.
- Une reconnexion de transport ne valide pas la reprise d'items ni l'invalidation
  de pointeurs ORAS : ces mécanismes ne sont pas encore implémentés.
- Le profil isolé ne reprend toujours pas les mises à jour ni les sauvegardes
  du répertoire utilisateur fourni.
- Le script générique expose un service mémoire complet, mais le lanceur actuel
  limite volontairement ses propres requêtes aux métadonnées.

## Fichiers

Créés :

- `tools/ap_connector.lock.json`.
- `tools/ap_connector_bundle.py`.
- `tools/bizhawk_connector_probe.lua`.
- `tools/run_bizhawk_connector_probe.py`.
- `tests/test_bizhawk_connector.py`.
- `docs/research/bizhawk-connector-results.json`.
- `docs/reports/003-bizhawk-tcp.md`.

Modifiés :

- `tools/run_bizhawk_probe.py` : extraction du lancement isolé réutilisable.
- `tools/README.md` : commande de test du connecteur.
- `README.md`, `docs/research/bizhawk-validation.md` et `sources.json` :
  résultats et références à jour.

## Tests

- **14 tests unitaires réussis**, dont vérification d'intégrité, refus d'import
  d'un bundle altéré, exclusion des sauvegardes originales et requêtes autorisées.
- Syntaxe Lua du wrapper vérifiée par `luac5.4 -p`.
- Deux essais réels indépendants : Rubis Oméga et Saphir Alpha.
- Contrôle des résultats JSON contre les sorties locales réelles.

Les doublures des tests unitaires ne sont jamais comptées comme validation du
jeu. Les résultats TCP ci-dessus proviennent des exécutions réelles.

## Git et prochaine étape

Le socle recherche/sondes a été enregistré dans le commit `fc8ffaf`.
Cette phase fait l'objet d'un commit distinct après ses vérifications.

Suite : identifier précisément les builds, préparer une sauvegarde jouable
isolée et vérifier une variable observable en lecture seule. **BH-05 reste
partiel** : transport validé, lecture concrète encore à démontrer.
