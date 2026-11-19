# Rapport 027 — SAVE natif et rechargement du sidecar expérimental

Date : 19 novembre 2026.

## Résultat

Le build OR vérifié, sur BizHawk/Encore, **écrit `aptest` lors d'un SAVE** :
le hook change les quatre derniers octets de son buffer, puis appelle le
writer natif après celui de `main`. La sonde vérifie les 512 octets en RAM
et sur disque. Un second processus, sans hook d'écriture, recharge les mêmes
octets depuis une copie du snapshot post-SAVE.

`main` a changé et ses 58 CRC restent valides. Inventaire et EventWork entiers
inchangés. Ni la ROM d'origine, ni le profil d'origine, ni le snapshot source
ne sont modifiés. Aucun WRITE du connecteur ou ajout d'item.

**Un marqueur de test survit à un arrêt normal et à un cold boot.** Ce n'est
pas encore un ledger AP, un reçu de livraison ni une transaction inter-fichiers.

## Protocole borné

`--experimental-bootstrap sidecar-save` exige un snapshot mono-fichier
vérifié et une nouvelle copie. Le lanceur prépare `aptest` avec le préfixe
et le challenge du rapport 026, mais réserve quatre octets nuls à `0x1FC`.
Le préflight exige le contenu complet, le statut de lecture, les records,
un statut writer nul, l'inventaire et EventWork de référence, sur deux
connexions. L'archive doit aussi être inchangée avant le signal de boutons.

Le patch vérifie la signature de `0x0045DC38` et ne redirige que ses trois
appels connus : `0x0045D23C`, `0x00124E50`, `0x00124F34`. Le wrapper filtre le
contrôleur et le manager de `main`, deux lectures de boot et un marqueur
encore nul. Après retour zéro du writer de `main`, il :

1. Enregistre une tentative et l'adresse de retour dans la page RAM ajoutée
   (`0x006AF060`). Le résultat reste sentinelle jusqu'au retour.
2. Remplace le marqueur nul par `ASV1` à `0x006AF3FC`, sans changer le reste
   du buffer de `aptest`.
3. Appelle le même writer natif avec le manager de `aptest`, enregistre son
   résultat et préserve le résultat de `main` pour le caller du jeu.

Il n'y a pas de retry du sidecar après tentative, ni de signal d'erreur
sidecar propagé au jeu. En cas d'échec, l'outil refuse la preuve : un SAVE
visible dans l'UI ne suffit pas à la valider.

Après la macro, une troisième connexion vérifie le préfixe patché, le statut
writer et les 512 octets modifiés. Après fermeture propre, la sonde vérifie
`main`, le sidecar complet et les métadonnées. Les deux fichiers sont
préservés dans un snapshot v2.

`sidecar-reload` exige un snapshot multi-fichiers vérifié contenant déjà
le marqueur, n'installe que le patch d'enregistrement/lecture du rapport 026
et ne génère aucun nouveau contenu. La copie et sa source doivent rester
identiques après boot. Une variante ne se réutilise pas pour jouer.

## Essais privés

Build OR identique au rapport 026 ; seed historique
`local/oras/backups/before-connector-8ny3zimx/00000001/main`,
horloge de copie `2026-11-18T18:36:36`, vitesse 400 %.

| Profil dans `local/oras/profiles/` | Résultat |
| --- | --- |
| `oras-connector-ae5ef_vx` | Échec conservé : l'UI était encore sur Continue ; la macro est entrée en jeu, sans SAVE. Statut writer nul et archives pré/post identiques. |
| `oras-connector-3v319yju` | Succès après ajout de l'étape Continue : writer appelé depuis `0x00124E50`, retour `0x00124E54`, une tentative terminée, résultat 0. |
| `oras-connector-lpb0rxzy` | Succès : nouveau processus et copie du snapshot `after-connector-ru0nhqh3`, sans writer patché. 512 octets relus à l'identique avant et après reconnexion. |
| `oras-connector-8z78dpft` | Contrôle négatif : snapshot pré-SAVE valide mais marqueur nul. Refus avant EmuHawk, aucune lecture mémoire. |

Le SAVE final a soumis 39 READ (dont deux sautés par GUARD) et quatre
GUARD ; le cold reload 28 READ (dont deux sautés) et quatre GUARD. Zéro
WRITE AP/Lua : le changement de marqueur vient du code A32 invité et le
fichier est écrit par le writer du jeu.

Blocs `main` modifiés : `[3, 4, 6, 10, 11, 17, 44]`. Tous les octets de
`aptest` restent identiques sauf le suffixe `00000000 → 41535631`.
Les six snapshots pré/post des essais lancés ont passé la validation complète.
Les hashes et chemins précis sont dans les
[résultats structurés](../research/native-sidecar-save-results.json).

## Fichiers, tests et limites

Modifiés : `tools/oras_sidecar_probe.py`, builder du bootstrap, lanceur,
tests synthétiques, README et documentation. **239 tests réussis.**
Les tests couvrent le ciblage des appels writer, les états incomplets ou
erronés, la préservation du challenge et le refus de combiner les modes
avec d'autres macros ou profils. Pas de réaffectation du bloc 47.

Le hook écrit **après** le writer de `main`. Une interruption peut donc
laisser deux fichiers désynchronisés même si chacun est lisible. Ni arrêt
brutal ni durabilité physique testés. Le marqueur n'établit pas une identité,
une liaison entre les fichiers ou un index AP. Le chemin de jeu avec sidecar
manquant, le reset interne et la récupération d'une paire partiellement
écrite ne sont pas testés. La livraison live reste bloquée.

Prochaine étape : définir la liaison et le protocole de récupération
inter-fichiers avant de stocker un vrai index de livraison.
