# Rapport 034 — reprendre le checkpoint antérieur sans rejouer la Potion

**Le checkpoint pré-SAVE du processus interrompu redémarre sur une
copie : Potion ×1 et index de test 0 sur deux connexions.** Le profil
interrompu du [rapport 033](033-inventory-index-interruption.md) conserve
Potion ×2 / index 0. Aucun des deux états n'est une preuve de livraison AP.

## Quel progrès conserve la copie ?

`tools/oras_potion_recovery.py` compare le snapshot v2 pré-SAVE désigné
par le témoin local d'interruption au `main` et au `aptest` encore présents
dans le profil coupé. Il vérifie l'identité du build, la barrière SIGKILL,
le contenu des deux archives et la concordance entre le bloc inventaire
sur disque et sa relecture RAM enregistrée. Il indique avant boot quels
blocs de `main` diffèrent. Pas de recherche du snapshot le plus récent :
la paire index 1 du SAVE réussi appartient à **un autre essai**.

Dans ce cas, les payloads des blocs **1, 3, 4, 6, 10, 11, 17 et 44**
diffèrent entre le `main` coupé et celui du fork. Le bloc 1 contient
l'inventaire : la Potion supplémentaire n'est pas dans la copie. Cette
liste porte sur les payloads des 58 blocs ; ce n'est pas un décompte
d'événements de progression perdus.

## Vérifications sur Encore

| Essai | Observation |
| --- | --- |
| `oras-connector-imxn8_ri` | Le snapshot valide ×2/index 1 de l'autre essai est refusé avant lancement ; zéro READ/WRITE. |
| `oras-connector-_s_21rj7` | `sidecar-index-potion-rollback` importe `before-connector-najqub2f` dans un profil neuf. Cold boot et reconnexion : même inventaire ×1, mêmes 512 octets du sidecar. 28 READ, zéro WRITE du connecteur, aucun hook d'écriture. |

Les deux snapshots du fork (`before-connector-1rrn9q3v`,
`after-connector-cp9t0gaq`) et sa copie finale ont l'empreinte de
l'archive pré-SAVE `590a7df4f66d2f67d37a5a226f45b88487931f033067205b2e3d6889454691f2`.
L'archive coupée a été revérifiée après fermeture :
`eeb486625c1c3d6bf9cea20e72c9f9cb2a733268ba841abc493e2ba8ba44c6f8`.
Le checkpoint d'origine et les fichiers du profil coupé ne sont pas écrasés.

**Contrôle du journal, hors ligne.** Une intention `submitted` à l'index 0
est inscrite dans une base SQLite de test avec l'empreinte pré-SAVE. Après
réouverture, le coordinateur reçoit l'empreinte mesurée sur le fork et une
identité synthétique. La même livraison en double ne crée pas de ligne,
`confirm_saved()` renvoie `False` avant toute demande de reçu,
`deliver_next()` refuse de renvoyer et la base fermée garde son SHA-256.
Le lanceur n'a pas ouvert de journal réel.

**276 tests réussis.** `tests/test_potion_recovery.py` couvre le bilan en
lecture seule, le refus d'un snapshot frère même identique, une modification
CRC-valide ultérieure du profil coupé et un témoin absent ou incompatible
avec la barrière. La reprise est explicite, limitée à cet essai OR et sans
réconciliation automatique. Prochaine étape : lier une commande de test
précise à un reçu produit par le jeu ; le compteur actuel ne distingue pas
une livraison de toute autre cause du même changement d'inventaire.
