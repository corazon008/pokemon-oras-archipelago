# Rapport 002 — premiers essais BizHawk / Encore

Date : 17 novembre 2026.

## Résultat effectivement observé

**Les deux éditions atteignent l'écran de choix de langue sous Encore.**
La sonde Lua s'exécute dans BizHawk 2.11.1, inventorie cinq domaines mémoire
et avance de la frame 0 à 180 avant fermeture propre.

Il ne s'agit pas encore d'une validation de partie jouable, de sauvegarde
ou d'accès à une variable du jeu.

Les résultats structurés, empreintes et références aux sorties locales sont
dans [`bizhawk-results.json`](../research/bizhawk-results.json).
Les captures ont été inspectées localement, sans ajout au projet.

## Isolation

Installation fournie : `bin/BizHawk-2.11.1-linux-x64/`.
`mono EmuHawk.exe --version` retourne `Version 2.11.1`.

Chaque essai utilise une copie distincte dans `/tmp/opencode/`, sans reprendre
`3DS/`, les sauvegardes ou les mises à jour du profil fourni. Les originaux ne
sont pas modifiés par le lanceur. Aucune touche n'est injectée et aucune
lecture/écriture RAM de jeu n'est exécutée par la sonde.

Le modèle New 3DS provient de la configuration fournie. Les autres informations
de version/région ne sont pas déduites des noms des ROMs. Elles restent inconnues.

## Mesures communes aux deux jeux

| Observation | Résultat |
|---|---|
| Version de BizHawk | 2.11.1 |
| Version Lua | Lua 5.4 |
| Identifiant système Lua | `3DS` |
| `FCRAM` | 268 435 456 octets |
| `VRAM` | 6 291 456 octets |
| `DSP RAM` | 524 288 octets |
| `N3DS Extra RAM` | 4 194 304 octets |
| `System Bus`, taille renvoyée par Lua | **0** |
| API `read_bytes_as_array` / `write_bytes_as_array` | Présentes, non exécutées |
| `require("socket")` dans ce profil sans dépendances AP | Échec : module introuvable |
| Code de sortie des deux essais retenus | 0 |

Le retour nul de taille du bus confirme le piège du cast 32 bits identifié
dans l'audit statique. Le domaine est bien énuméré ; sa taille renvoyée par
Lua ne doit pas être utilisée comme critère d'absence.

## Problèmes et corrections

### Fonctions NLua

Le premier lancement a montré qu'une API CLR callable peut avoir un type Lua
autre que `function`. Le premier inventaire signalait donc à tort certaines API
comme indisponibles, tout en réussissant déjà l'énumération des domaines.

La sonde a été corrigée pour utiliser des closures et `pcall` pour les
observations. Les deux essais retenus ici ont été exécutés après correction.
Un test couvre les objets callables sans type `function`.

### Dépendances du connecteur

L'installation seule ne fournit pas le module `socket.lua` attendu par AP.
Le fichier `Lua/socket/core.dll` fourni est un binaire Windows, d'après `file`.
Cela ne démontre pas une impossibilité TCP sous Linux.

Le `data/lua/socket.lua` d'Archipelago étudié prévoit explicitement Linux,
Lua 5.4 et `x64/socket-linux-5-4.so`. Il faudra préparer les dépendances
correspondantes au commit AP retenu, dans un emplacement local isolé, puis
tester le connecteur générique. Aucun paquet système n'a été installé.

### Avertissement GTK

EmuHawk signale l'absence du thème GTK et utilise son thème intégré.
Les deux essais atteignent néanmoins le menu et se ferment proprement.
Aucune correction système n'est nécessaire pour ce constat.

## Fichiers créés ou modifiés

Créés :

- `tools/bizhawk_probe.lua` : inventaire sans accès RAM de jeu.
- `tools/run_bizhawk_probe.py` : lancement isolé et sorties locales.
- `tools/README.md` : utilisation et limites.
- `tests/test_bizhawk_probe.py` : tests de l'outillage.
- `docs/research/bizhawk-results.json` : mesures expurgées des logs bruts.
- `docs/reports/002-bizhawk-capabilities.md` : présent rapport.

Modifiés :

- `.gitignore` : exclusion de `bin/`, qui contient aussi des données utilisateur.
- `README.md` et `docs/research/bizhawk-validation.md` : état des validations.
- `docs/research/sources.json` : chemins supplémentaires étudiés.
- `docs/research/audit-initial.md` : lien vers les résultats ultérieurs.

## Tests

- `python3 -m unittest discover -s tests -v` : **6 tests réussis**.
- `luac5.4 -p tools/bizhawk_probe.lua` : syntaxe valide.
- Exécution réelle de la sonde : Rubis Oméga et Saphir Alpha.
- Empreintes SHA-256 des deux fichiers ROM et des exécutables de référence.

Les tests unitaires utilisent des doublures : ils ne prouvent pas que les
fonctions de lecture et d'écriture d'Encore fonctionnent sur une variable ORAS.

## État des jalons

- **BH-01 : partiel**, menu de langue seulement.
- **BH-03 : inventaire validé**, accès aux données de jeu non testé.
- **BH-02 et BH-04 à BH-10 : non validés**.
- Pas de location, item, offset RAM ou client APWorld ORAS ajouté.

## Suite

1. Préparer les dépendances Linux du connecteur AP et tester TCP en métadonnées
   seulement (`PING`, `SYSTEM`) avant tout accès à la RAM de jeu.
2. Identifier les builds exacts et préparer une sauvegarde de test jouable.
3. Identifier et vérifier une variable observable, en lecture seule.
4. N'entreprendre une écriture qu'après les validations préalables requises.
