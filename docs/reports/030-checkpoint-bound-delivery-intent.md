# Rapport 030 — intention de livraison liée au checkpoint

**Le client hors ligne enregistre le checkpoint de reprise avant tout
appel susceptible de modifier l'inventaire.** Un rollback ou une demi-écriture
ne réinitialise pas la file, même si l'index remonté semble correct. Aucun
writer réel n'est activé.

## Contrat et journal

- `CheckpointFingerprint` réunit les SHA-256 de `main`, du sidecar, des
  métadonnées et de l'arbre complet. `RecoveryAnchor` ajoute une référence
  opaque vers un snapshot ; le journal n'ouvre aucun chemin arbitraire à partir
  de cette référence. Ce n'est pas l'identité stable du monde/de la partie.
- Le journal v2 exige un checkpoint initial explicite. Ensuite, le checkpoint
  attendu est le post-SAVE validé de la livraison précédente. La création et
  les transitions préservent les garanties SQLite existantes.
- L'adaptateur doit comparer l'archive **effectivement chargée** et revérifier
  le snapshot de reprise. La transaction SQLite associe `submitted`, l'ancre
  et l'époque d'origine avant `apply`. Le reçu RAM doit nommer l'intention
  complète. En cas de perte de réponse ou reçu incorrect, l'intention reste
  durable et la livraison n'est jamais relancée automatiquement.
- La confirmation exige un reçu qui nomme la livraison, son intention
  d'origine, l'index suivant, et le checkpoint post-SAVE de l'époque
  actuellement chargée. Le snapshot suivant doit aussi être revérifié.
  Pour ce prototype à deux fichiers, `main`, sidecar et arbre doivent avoir
  changé, et les métadonnées rester identiques. Ces différences ne prouvent
  ni la causalité ni la cohérence ; l'adaptateur doit prouver l'item et
  l'index ensemble.

Un hot/cold reload peut prouver la livraison dans une nouvelle époque
uniquement si l'adaptateur lie la preuve à l'époque courante **et** à
l'intention d'origine. Un retour à l'ancre pré-SAVE n'est jamais une
autorisation de renvoyer. L'enregistrement v1 ne contient pas ces données :
il est refusé sans migration ni modification. Une sauvegarde ordinaire
entre deux livraisons peut aussi bloquer la file ; aucune adoption
automatique d'un checkpoint inconnu n'est prévue.

## Vérification et limites

Tests synthétiques : une deuxième connexion SQLite voit l'intention complète
avant l'entrée dans `apply` ; refus d'un snapshot absent, d'un reçu mal lié,
des deux demi-écritures, du rollback en cours et du rollback après commit
même avec index concordant. Les cas perte de réponse, réouverture et
déduplication restent couverts.

Contrôle hors ligne avec les octets du [rapport 029](029-interrupted-native-save.md) :
`main` nouveau / sidecar ancien a été présenté au coordinateur avec un index
avancé **factice**, dans une base SQLite temporaire. Refus avant lecture de
reçu ou tentative de renvoi ; l'intention est restée `submitted`.
Aucun index AP n'a été déduit des fichiers, aucun item appliqué et aucun
émulateur lancé dans cette phase.

Modifiés : `oras_client/game_interface.py`, `oras_client/delivery.py`,
`tests/test_delivery.py` et documentation. **256 tests réussis.**

Le protocole ne sait pas créer des preuves à partir de `aptest`. Il reste
à concevoir et vérifier un vrai état de livraison game-side, à prouver
une mutation item/index indivisible ou à établir une réconciliation
sûre après interruption. Livraison live bloquée.
