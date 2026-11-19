# Rapport 033 — Potion et compteur lors d'une coupure entre fichiers

Sur le build exact de Rubis Oméga, un SAVE normal conserve **Potion ×2
et compteur de test 1**. Le même essai, interrompu entre les deux
écritures natives, produit **Potion ×2 et compteur 0**. Les 58 CRC de
`main` restent valides. Le rechargement expérimental refuse cette paire
avant le boot ; aucun item n'est renvoyé.

## Protocole

1. `sidecar-index-potion-save` part du [seed du rapport 032](032-synthetic-index-rollback.md)
   (Potion ×1). Il crée `aptest` à l'index 0 et capture le snapshot v2
   complet **avant** le boot. Un seul WRITE du connecteur change le
   champ quantité vérifié. Le lot garde le code patché et ses points
   d'entrée, le bloc inventaire complet, EventWork, le sidecar initial
   et le statut du writer inactif. Le préfixe de la ROM d'origine sert
   à l'identification, pas à la garde RAM du préfixe patché.
2. Le bloc inventaire est vérifié en RAM immédiatement après le WRITE,
   puis après reconnexion. Le SAVE ne démarre qu'après ces contrôles
   et si la paire initiale n'a pas changé sur disque. Le writer de
   test écrit `main`, copie le footer et enregistre l'index 1 dans
   `aptest`. Le contrôle hôte recoupe l'archive finale et la RAM.
3. `sidecar-index-potion-interrupt` réimporte le **même snapshot
   pré-SAVE**, identifiant d'essai inclus, dans un autre profil. Le
   point d'arrêt est placé après le retour zéro du writer de `main`,
   avant la copie du footer et l'écriture de l'index. Après observation
   stable de la barrière et du sidecar RAM intact, l'outil tue son
   propre processus EmuHawk par `SIGKILL`. Il n'en publie aucun backup
   post-SAVE.
4. Contrôle : empaqueter séparément les octets coupés dans un manifeste
   v2 **forensique** et les présenter à `sidecar-index-reload`. Cela
   distingue le rejet sémantique d'un simple refus d'archive non
   manifestée. Le nouveau processus de contrôle ne démarre que pour la
   paire intacte, writer absent.

`tools/oras_index_probe.py` distingue explicitement l'avance de
l'inventaire avec l'ancien sidecar d'une paire rechargeable. Il exige
le bloc inventaire complet attendu et l'empreinte de l'ancien sidecar,
pas seulement une quantité ou un numéro d'index.

## Résultats

| Profil privé | Résultat |
| --- | --- |
| `oras-connector-dej60787` | SAVE normal : Potion ×2, index 1, footer concordant ; 58 READ, 1 WRITE. |
| `oras-connector-zo5b1q86` | `SIGKILL` au retour natif `0x00124E54` : Potion ×2, sidecar inchangé à l'index 0 ; 139 READ, 1 WRITE. |
| `oras-connector-p7pr5omp` | Le manifeste v2 forensique passe les vérifications génériques ; le footer discordant bloque le boot, zéro READ/WRITE. |
| `oras-connector-xprfgmpo` | Cold reload : Potion ×2 et index 1 sur deux connexions, aucun writer installé, archive inchangée ; 28 READ, zéro WRITE. |

Snapshots de l'essai normal : `before-connector-3naw2p_l` /
`after-connector-743ozg2r`. Le snapshot pré-coupure
`before-connector-najqub2f` est identique au snapshot pré-SAVE normal.
[Preuves structurées](../research/inventory-index-interruption-results.json).

Le premier contrôle immédiatement après `SIGKILL` a rencontré un port
en `TIME_WAIT`. La disponibilité des ports est désormais vérifiée juste
avant le lancement, après les contrôles d'archive. La paire coupée est
ainsi refusée pour son contenu même lorsque le socket est indisponible.
Un lancement de la paire intacte a également été refusé pendant le
`TIME_WAIT` (`oras-connector-vkep60r6`), sans lancement ni WRITE.

Contrôle hors ligne : un journal v2 **synthétique** a été créé avec
l'empreinte du vrai checkpoint pré-SAVE, puis fermé après l'enregistrement
de l'intention. À la réouverture, les empreintes des vrais octets coupés
ne passent pas le contrôle du successeur. Le journal reste `submitted`,
sans consultation du reçu ni nouvelle soumission. L'identité et le jeu
observé par ce contrôle restent factices.

**272 tests réussis.** Les tests vérifient notamment les gardes de
l'écriture, la position de la barrière et le rejet d'un inventaire ou
d'un sidecar qui ne correspond pas à l'essai interrompu.

## Limites

Dans les deux essais, seule la quantité change dans le bloc inventaire ;
EventWork reste identique. Aucun replay, aucune réparation en place,
aucune modification de la ROM ou du seed originaux. Le compteur reste
synthétique : le writer ne valide pas lui-même l'origine de la Potion,
et le footer ne constitue ni un reçu AP ni une preuve d'identité.

La coupure démontre un split après retour du writer sur Encore, pas
le comportement en cas de panne électrique. Le point d'arrêt élargit
la fenêtre existante et ne mesure pas sa durée normale. La paire
interrompue est bloquée, pas réparée. Renvoyer l'item sur la base de
l'index 0 ou promouvoir l'index sur la seule base de la quantité serait
incorrect : ni l'un ni l'autre n'établit l'historique de la livraison.

La prochaine étape consiste à définir quel checkpoint fait foi quand
un SAVE n'est pas confirmé. Une piste est de garder la dernière
génération complète hors du profil actif et de ne publier une nouvelle
ancre qu'après validation conjointe et conservation d'un snapshot
vérifié. Un retour au checkpoint précédent perd la progression
ultérieure et doit rester explicite ; il ne réconcilie pas AP.
