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
