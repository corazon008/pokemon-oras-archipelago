# Sondes BizHawk / Encore

Ces outils inventorient les capacités de Lua et testent le transport AP.
Ils ne constituent pas encore un client de jeu ORAS ni un test de lecture
d'une variable de progression.

## Exécution isolée

Depuis la racine du projet :

```sh
python3 tools/run_bizhawk_probe.py \
  --rom "ROMs/Pokemon Omega Ruby (USA) (En,Ja,Fr,De,Es,It,Ko) (Rev 2).3ds"
```

Changer `--rom` pour tester Saphir Alpha.
`--bizhawk` accepte une autre installation ; celle fournie dans `bin/` est
utilisée par défaut. Mono et un affichage graphique accessible sont requis.

Le lanceur :

1. Copie l'installation dans un nouveau dossier `/tmp/opencode/oras-bizhawk-*`.
2. Exclut le répertoire `3DS/` existant et prépare une configuration privée.
3. Désactive les chargements récents, le son et le plugin loader dans cette copie.
4. Lance le jeu avec `bizhawk_probe.lua`, avance 180 frames, prend une capture
   privée et ferme uniquement cette instance.
5. Écrit `run.json`, `capabilities.json`, `stdout.txt` et `stderr.txt`.

`--frames` accepte 0 à 3600 ; `--timeout` borne la durée du processus.
Un inventaire incomplet, une erreur de processus ou un système autre que `3DS`
produit un code de sortie non nul.

Le dossier temporaire reste disponible pour inspection ; aucune suppression
automatique d'un profil n'est effectuée.

## Limites importantes

- Aucun appel de lecture/écriture de mémoire de jeu, aucune touche injectée,
  aucune sauvegarde déclenchée par la sonde.
- L'émulateur peut écrire ses propres fichiers dans le profil temporaire.
- Les données utilisateur, sauvegardes et mises à jour installées dans le
  répertoire `3DS/` fourni **ne sont pas reprises**. Cet essai n'identifie donc
  pas la version utilisée dans une partie existante.
- La présence de l'API d'écriture est relevée sans l'appeler. Ce n'est pas une
  preuve que les écritures mémoire fonctionnent.
- Les compteurs de frames et une capture du menu ne démontrent pas qu'une partie
  complète est jouable ou que sa sauvegarde est correcte.
- `lua_socket_loadable = false` peut simplement signaler l'absence des
  dépendances du connecteur AP dans cette configuration vierge.
- Les sorties peuvent contenir des chemins locaux ; les captures représentent
  le jeu. Ne pas distribuer ces fichiers bruts.

Les fonctions CLR exposées par NLua ne sont pas nécessairement de type Lua
`function` ; la sonde utilise des appels protégés pour les observations et
ne teste pas la présence des API avec cette seule comparaison de type.

## Tests de l'outillage

```sh
python3 -m unittest discover -s tests -v
luac5.4 -p tools/bizhawk_probe.lua
```

Les tests Lua utilisent des API factices dont toute lecture/écriture mémoire
lève une erreur. Ils vérifient l'outillage uniquement ; les essais Encore réels
sont documentés séparément dans le rapport 002.

## Connecteur TCP amont

```sh
python3 tools/run_bizhawk_connector_probe.py \
  --rom "ROMs/Pokemon Omega Ruby (USA) (En,Ja,Fr,De,Es,It,Ko) (Rev 2).3ds"
```

Ce diagnostic :

- Télécharge les dépendances AP depuis un commit figé, dont LuaSocket Linux.
- Vérifie chaque SHA-256 du fichier `ap_connector.lock.json` avant chargement.
- Utilise le connecteur et l'API Python amont sans les modifier.
- Envoie seulement `VERSION`, `PING`, `SYSTEM` et deux requêtes `MEMORY_SIZE`.
- Vérifie une déconnexion/reconnexion et ferme sa propre instance via un signal
  fichier traité par le wrapper Lua.
- Produit `result.json`, `stdout.txt` et `stderr.txt` sous
  `/tmp/opencode/oras-connector-*`.

Connexion Internet nécessaire pour ces téléchargements. Aucun paquet système
ni dépendance Python externe n'est installé. Plateforme ciblée : Linux x86_64.
`--timeout` borne les essais réseau ; la fermeture dispose d'un délai distinct.
Les logs permettent de distinguer une fermeture propre d'un arrêt forcé.

Fermer les autres connecteurs avant l'essai : l'outil refuse de démarrer si leur
plage de ports est occupée. Ne pas lancer plusieurs diagnostics simultanément.
Les deux modules Python partagent la préparation du profil isolé.

Attention : le connecteur amont expose aussi des commandes d'écriture mémoire.
Le diagnostic ne les envoie pas, mais ce service doit rester sur loopback,
sans redirection de port et sur une machine de confiance.

Ces échanges ne sont pas le protocole WebSocket du serveur Archipelago.
Voir le [rapport 003](../docs/reports/003-bizhawk-tcp.md).

## Identité ROM et preuve de lecture

```sh
python3 tools/rom_identity.py \
  "ROMs/Pokemon Omega Ruby (USA) (En,Ja,Fr,De,Es,It,Ko) (Rev 2).3ds"

python3 tools/run_bizhawk_connector_probe.py --read-code \
  --rom "ROMs/Pokemon Omega Ruby (USA) (En,Ja,Fr,De,Es,It,Ko) (Rev 2).3ds"
```

La première commande lit les en-têtes et calcule le SHA-256 complet sans modifier
la ROM. Elle n'associe pas de numéro commercial à `remaster_version`.

La seconde ajoute **deux lectures de 64 octets**, avant et après reconnexion,
à l'adresse virtuelle du texte dérivée de l'ExHeader. La référence est prise
dans le préfixe non compressé de `.code`, sans extraction sur disque.
La comparaison échoue si la référence est indisponible ou si la mémoire diffère.
Les octets ne sont pas enregistrés dans les résultats JSON.

Cette option ne lit aucune variable de progression et n'envoie aucune écriture.
Le mode sans `--read-code` reste limité aux métadonnées.
Voir le [rapport 004](../docs/reports/004-rom-identity-and-read.md).

## Créer une sauvegarde jouable dans un profil privé

```sh
python3 tools/run_bizhawk_save_probe.py --interactive \
  --rom "ROMs/Pokemon Omega Ruby (USA) (En,Ja,Fr,De,Es,It,Ko) (Rev 2).3ds"
```

Cette commande ouvre une **nouvelle copie isolée** de BizHawk. Créer une partie,
atteindre un état jouable, sauvegarder depuis le menu natif et fermer proprement
l'émulateur. Ne pas remplacer un fichier du répertoire `bin/` ou la ROM originale.

Le terminal indique le dossier `/tmp/opencode/oras-save-*`. Le conserver pour
les essais suivants : il contient le profil et sa sauvegarde de test.
Le mode interactif n'a ni macro, ni fermeture automatique après délai.
Une fermeture réussie de la fenêtre ne prouve pas à elle seule qu'une sauvegarde
a été effectuée ; ce point devra être vérifié au rechargement.

Pour reprendre ce même profil :

```sh
python3 tools/run_bizhawk_save_probe.py --interactive \
  --session /tmp/opencode/oras-save-IDENTIFIANT \
  --rom "ROMs/Pokemon Omega Ruby (USA) (En,Ja,Fr,De,Es,It,Ko) (Rev 2).3ds"
```

Les profils `/tmp` sont temporaires : ils peuvent disparaître après redémarrage
ou nettoyage du système. Conserver une copie privée avant un essai important.

Le mode automatisé, sans `--interactive`, accepte par exemple :

```text
--steps "180:-,2:A,120:-"
```

Cela signifie attendre 180 frames, appuyer sur A pendant deux frames, puis
attendre 120 frames. Chaque étape produit une capture privée. Seuls les boutons
ordinaires sont autorisés ; pas de Reset, toucher ou code Lua arbitraire.

`--seed-save` peut importer une copie d'un `main` validé par taille, marqueur,
descripteurs et CRC ORAS. Son fichier Encore `00000001.metadata` de 16 octets doit être présent à
côté du dossier `00000001/`. Aucun déchiffrement ou conversion n'est tenté.
Ce contrôle ne remplace pas un chargement effectif par le jeu.
`--seed-save` et `--session` sont incompatibles pour éviter
de réinitialiser une sauvegarde de travail.

Le candidat trouvé lors de la recherche initiale n'avait pas le marqueur attendu.
Une nouvelle sauvegarde native a depuis été fournie et rechargée. Voir le
[rapport 005](../docs/reports/005-private-save-profile.md).

## Vérifier une sauvegarde et observer son inventaire

```sh
python3 tools/oras_save.py /chemin/prive/00000001/main
```

Cette inspection vérifie désormais les **58 CRC et descripteurs ORAS**, puis
affiche les objets et quantités sans lire les noms du joueur ou ses identifiants.
Le contrôle est aussi obligatoire avant un nouvel import.

Après création d'une copie de travail, les options de recherche sont :

- `--read-inventory` : une lecture bornée à l'adresse documentée pour le SHA-256
  de cette ROM, comparée au bloc de sauvegarde validé.
- `--scan-inventory` : recherche exacte dans le tas applicatif documenté d'Encore ;
  aucune adresse d'inventaire n'est supposée.
- Ces modes sont exclusifs et interdits en mode interactif.
- La référence doit contenir des données non nulles. Zéro ou plusieurs résultats
  ne sont pas automatiquement promus en adresse utilisable.
- `--speed 400` accélère les pas natifs automatisés ; le profil est remis à
  100 % à la prochaine préparation.

Les lectures sont faites après les `--steps` de démarrage/chargement et de menu.
Leur durée dépend du jeu : une macro terminée ne prouve pas que le bon écran a
été atteint. Inspecter les captures privées.

Les modes mémoire sont **strictement en lecture**. L'adresse retenue pour OR
est restreinte au build identifié ; elle n'autorise pas d'écriture et n'est
pas transposée à AS. Le candidat du plugin Gen6 a échoué sur ce build.

Le lanceur désactive HIDAPI dans les processus automatisés seulement, pour
contourner une exception SDL observée à la fermeture. Les entrées physiques
des sessions interactives ne sont pas modifiées.
Voir le [rapport 006](../docs/reports/006-native-reload-and-inventory.md).
