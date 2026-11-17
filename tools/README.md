# Sonde BizHawk / Encore

Ces outils inventorient les capacités de Lua. Ils ne sont ni un client
Archipelago, ni un test de lecture d'une variable ORAS.

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
