# Rapport 026 — enregistrement et lecture d'un fichier AP expérimental

Date : 19 novembre 2026.

## Résultat

Sur le build Rubis Oméga vérifié dans BizHawk/Encore, un patch local
enregistre **un deuxième fichier natif**, `data:/aptest`, à côté de
`data:/main`. Le lecteur natif transfère ses 512 octets vers une page ajoutée
par le patch. Deux cold boots indépendants, deux contenus aléatoires
différents, concordance intégrale avant et après reconnexion.

Le fichier est **préparé côté hôte**, pas écrit par le jeu. Ce test ne valide
ni SAVE/reload, ni un index AP, ni un ledger persistant utilisable. Aucune
livraison, aucun replay et aucune réaffectation du bloc 47.

## Construction

`--experimental-bootstrap sidecar-load` accepte seulement le build OR exact
et une copie fraîche de `00000001/main` issue d'un snapshot vérifié.
L'archive doit contenir seulement `main` et avoir les métadonnées Encore
précises du checkpoint. Le lanceur crée `aptest` sur la copie, puis y fait
passer le champ de nombre de fichiers de `1` à `2`. Il ne formate rien et
n'ajuste ni la taille déclarée de l'archive ni ses autres champs. L'acceptation
de ces métadonnées sous Encore n'est pas une preuve de quota ni de
compatibilité matérielle.

Le patch IPS :

- À `0x00108E3C`, porte la capacité demandée au constructeur de 1 à 2.
- À `0x00108E54`, conserve l'enregistrement original, vérifie compteur/capacité
  `1/2`, puis appelle la même fonction pour `aptest`. Deux records de 48 octets
  sont relus et vérifiés ; `main` reste associé au manager original.
- À `0x0045DACC`, intercepte le lecteur pour la paire contrôleur/manager de
  `main` enregistrée. Après succès de la lecture originale, appelle le même
  lecteur pour le nouveau manager et préserve le résultat de `main` pour le
  caller. Le `PUSH` déplacé est vérifié et rejoué avant continuation native.

Le manager et le bloc ajoutés commencent à `0x006AF020` et `0x006AF024`.
Le bloc retourne longueur 512 et buffer `0x006AF200`. Les pointeurs des
dispatchs et le statut à `0x006AF030` sont contrôlés. Seuls les callbacks
nécessaires à l'enregistrement et à la lecture sont validés ; les autres
slots ne sont pas une implémentation utilisable pour SAVE.

Les 512 octets de preuve ne sont pas dans le patch. Le script les génère
sur l'hôte (préfixe d'identification suivi d'aléa), puis compare le contenu
complet en RAM, et non un marqueur court ou un succès retourné par le jeu.
Les IPS et ExHeader générés restent privés ; aucun executable complet
n'est exporté et aucune ROM originale n'est modifiée.

## Essais

Seed : `local/oras/backups/before-connector-8ny3zimx/00000001/main`.
Horloge du seed sur copie seulement : `2026-11-18T18:36:36`.

| Profil privé | Verdict | Observation |
| --- | --- | --- |
| `oras-connector-_i_5mw4w` | Échec de la sonde | 2 records, dernier résultat 0, 2 lectures au lieu d'une attendue ; pas de validation RAM complète |
| `oras-connector-x3vps5ho` | Complet | Deux retours vérifiés, challenge intégral dans RAM |
| `oras-connector-0haqvoml` | Complet | Nouveau challenge, mêmes retours et même résultat |

Le premier essai n'est pas reclassé en succès. Les suivants instrumentent
deux couples adresse de retour/résultat, avec limite de deux slots :
`0x0045D3D8` puis `0x00124D80`, résultat 0 à chaque fois. La sonde exige
ce chemin précis ; elle ne généralise pas à d'autres checkpoints ou éditions.

Chaque succès a deux connexions, 28 READ soumis (dont deux sautés par GUARD),
quatre GUARD et zéro WRITE de connecteur. Les writes natifs dans la page
ajoutée ne sont pas comptés comme des WRITE du connecteur. Les records
`data:/main` et `data:/aptest` et le contenu du buffer sont identiques après
reconnexion. Inventaire/EventWork complets concordent avec le seed.
`main`, les métadonnées ajustées et `aptest` restent inchangés après boot.
Les snapshots complets pré/post v2 préservent ces fichiers et leurs hashes.
Les fichiers sources restent inchangés, métadonnées originales comprises.

## Limites et suite

Le mode refuse SAVE, Potion, macros personnalisées et réutilisation. Les
profils expérimentaux ne sont pas utilisables pour jouer avec le lanceur
natif. Les tests de l'outil refusent fixture absente/altérée ; le chemin
**dans le jeu** lorsqu'un sidecar manque n'a pas été testé.

Pas de test de reset interne, de reformatage, de SAVE natif ni de panne.
Ce résultat ne valide pas la persistance d'un changement de contenu
effectué dans le jeu. Une future écriture `main` + sidecar serait une
opération à deux fichiers dont l'atomicité reste à démontrer.

Créés : `tools/oras_sidecar_probe.py`, tests synthétiques, rapport et
[preuves structurées](../research/native-sidecar-load-results.json).
Modifiés : bootstrap, lanceurs et documentation. **236 tests réussis.**
Prochain jalon : vérifier un SAVE/reload d'un marqueur de test modifié côté
jeu, et les comportements si le sidecar est absent ou incohérent, avant
de lui confier un index de livraison.
