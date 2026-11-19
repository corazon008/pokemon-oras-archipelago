# Rapport 029 — interruption réelle entre `main` et `aptest`

**Un arrêt forcé d'EmuHawk a laissé `main` modifié et CRC-valide, mais
`aptest` identique au checkpoint pré-SAVE.** La reprise a chargé le checkpoint
intact dans un nouveau profil ; l'archive interrompue reste disponible pour
inspection. Un `main` lisible n'est donc pas un reçu de livraison.

### Expérience

Sur le build OR et le checkpoint du [rapport 027](027-native-sidecar-save-reload.md),
`sidecar-interrupt` exige la paire `observed-before` du témoin local et la
revérifie sur une copie fraîche. Le patch conserve le writer natif. Après
son retour zéro pour `main`, il enregistre son caller et un état distinct
de tout succès, puis retient le thread par une branche sur elle-même avant
la mutation du marqueur et l'appel du writer `aptest`. La fenêtre temporelle
est donc artificiellement élargie, mais les octets sur disque ne sont pas
assemblés à partir de deux copies après coup.

Le lanceur vérifie la barrière initialement nulle, déclenche les boutons,
puis exige deux lectures identiques du statut de la barrière et le buffer
`aptest` pré-SAVE complet. Seulement alors il envoie `SIGKILL` à son processus
enfant et vérifie le code de sortie `-9`. Il inspecte les fichiers au repos
sans publier de backup post-interruption ni créer de profil réutilisable.

### Observations

| Essai | Résultat |
|---|---|
| `oras-connector-vubpy3c2` | Échec conservé : confirmation SAVE à l'écran, aucune barrière observée, connexion réinitialisée. Aucun kill demandé, sortie 0, paire toujours `observed-before`. |
| `oras-connector-3076clxw` | Après délai de confirmation augmenté : retour `0x00124E54`, barrière `0x005797F4`, 512 octets de RAM encore anciens, enfant tué. |
| Reprise immédiate | Refus avant lancement par le contrôle des ports ; socket `43057` en `TIME-WAIT`. Aucun contournement. |
| `oras-connector-eb0ssrk9` | Cold boot depuis `before-connector-l0_9wyid` en mode `sidecar-rollback`, sans writer : deux connexions, `observed-before` avant/après, archive inchangée. |

L'archive interrompue conserve les 58 CRC valides de `main`. Blocs modifiés :
`[3,4,6,10,11,17,44]`. Inventaire (Potion ×1), EventWork et métadonnées
inchangés. Le hash du nouveau `main` ne correspond **pas** au hash post-SAVE
du témoin antérieur ; le classificateur renvoie correctement `unknown-pair`
(`main_matches=unknown`, `sidecar_matches=before`), pas
`split-main-after-sidecar-before`. L'inspecteur en lecture seule sort avec
le code 1. La paire est impropre à une reprise AP.

La reprise démontrée revient **en arrière** : son checkpoint précède
l'interruption et contient l'ancien marqueur. Elle n'utilise pas le `main`
plus récent de l'archive interrompue. Les deux lectures natives du fichier et
les relectures après reconnexion sont vérifiées. Aucun journal réinitialisé,
aucun item rejoué, aucune intervention sur la sauvegarde originale.

### Validation et limites

Nouveau : `tools/oras_save_interruption.py`, tests synthétiques d'orchestration,
rapport et [mesures](../research/interrupted-save-results.json). Modifiés :
bootstrap, hook sidecar, lanceur et documentation. **246 tests réussis.** Les
tests vérifient notamment la place de la barrière entre les writers, le refus
d'un statut incomplet/déjà terminé, et la distinction sortie normale/SIGKILL.

Cet essai ne mesure ni fréquence de l'incident sur un jeu non instrumenté,
ni coupure électrique, ni durabilité physique. Il démontre une fenêtre où
les deux fichiers divergent sur ce build et ce backend. Prochaine question :
comment lier une intention de livraison à un checkpoint récupérable avant de
modifier l'inventaire ? L'index AP reste inconnu et la livraison live bloquée.
