# Rapport 028 — détection de paires hybrides et reprise sur copie

## Résultat

Les deux combinaisons hybrides de `main` et `aptest` ont un manifeste v2
cohérent et un `main` avec 58 CRC valides. Le nouveau contrôle les refuse
**avant EmuHawk**. `main` ancien + `aptest` nouveau passait même l'ancien
contrôle du marqueur `ASV1`.

La paire post-SAVE intacte, sélectionnée explicitement, redémarre dans un
nouveau profil sans hook writer. Le sidecar complet est relu avant et
après reconnexion ; l'archive source et le fork restent inchangés.
Pas de fusion, réparation en place, index AP ou replay.

## Témoin local

`tools/oras_sidecar_recovery.py` revérifie le `result.json` du SAVE réussi
du [rapport 027](027-native-sidecar-save-reload.md). Il exige l'identité OR
exacte, un arrêt normal et une tentative writer réussie. Il revalide les
deux snapshots référencés, leurs empreintes et la transition attendue :
`main` différent mais inventaire/EventWork identiques, sidecar différent
uniquement par son marqueur de test. Le résultat doit lier les deux
empreintes d'archive et la lecture RAM post-SAVE.

Cette observation est un témoin externe **local et non signé**. Elle ne
suffit pas si le résultat ou les snapshots ont été falsifiés. Elle ne
prouve ni durabilité physique, ni livraison, ni que le checkpoint est le
plus récent. Un état nouveau mais légitime et non observé est aussi refusé.
L'inspection suppose que l'archive candidate est au repos.

Le classificateur distingue les paires observées pré/post, les deux sens
de mélange, un sidecar manquant, des fichiers inconnus, un layout inattendu
et un `main` invalide. La sonde `sidecar-reload` exige désormais
`--sidecar-save-result` et `observed-after`, avant import, dans la copie
avant boot, puis après sortie. Ce contrôle vise `aptest`, pas le mode de
récupération OR générique ni une validation de ledger.

## Essais sur copies réelles

Témoin : `local/oras/profiles/oras-connector-3v319yju/result.json`.
Snapshots pré/post : `before-connector-cx97hc_i` et `after-connector-ru0nhqh3`.

| `main` | `aptest` | Résultat |
| --- | --- | --- |
| avant | après | Refus `split-main-before-sidecar-after`, profil `oras-connector-9gmwf0lb` |
| après | avant | Refus `split-main-after-sidecar-before`, profil `oras-connector-y3xd8tap` |
| après | après | Cold boot et reconnexion, profil `oras-connector-rospuy9j` |

Les hybrides sont fabriqués hors ligne sous `local/oras/profiles/` à partir
des vrais snapshots. Leurs manifestes sont recalculés à partir des octets
copiés : ce ne sont pas des contrôles de hash invalide ni des backups de
récupération. Aucun processus lancé et aucune lecture mémoire pour ces deux
refus. Le fork intact a soumis 28 READ, zéro WRITE et vérifié les 512 octets
du sidecar ; ses deux nouveaux snapshots v2 correspondent au témoin.

[Preuves structurées](../research/sidecar-pair-recovery-results.json).
**243 tests réussis**, dont paires synthétiques, archives illisibles,
témoin invalide et garde CLI. ROM, profils d'origine, témoins et captures
préservés.

## Limites et suite

Les mélanges représentent des états possibles, **pas des résultats de
crash provoqué**. La reprise choisit la paire connue explicitement ; elle
ne récupère pas la progression non sauvegardée et ne réconcilie pas AP.
Prochain test : instrumenter puis interrompre une sauvegarde sur copie
pour déterminer quels états arrivent réellement. Un vrai index doit
rester bloqué tant qu'on ne sait pas réconcilier l'item et ce compteur.
