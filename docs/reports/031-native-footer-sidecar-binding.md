# Rapport 031 — footer natif embarqué dans le sidecar

**Un SAVE natif écrit dans `aptest` le footer de `main` de cette même
sauvegarde.** Les 488 octets correspondent au fichier après fermeture, et le
sidecar complet correspond à la RAM. Un cold boot indépendant, sans writer ni
`result.json` antérieur, recharge les 512 octets après validation de la paire.
Un `main` plus ancien avec le nouveau sidecar est refusé avant EmuHawk, malgré
des CRC et un manifeste v2 valides.

## Expérience

`sidecar-footer-save` prend le build OR exact et le checkpoint mono-fichier
du rapport 027. Sur une copie, il initialise `aptest` avec :

| Octets | Contenu |
| --- | --- |
| 0–19 | Signature expérimentale `ORAS-AP-FOOTER-V1`, complétée à 20 octets |
| 20–507 | Payload de métadonnées native de `main` (488 octets) |
| 508–511 | Zéro initialement, `ASV1` après l'écriture expérimentale |

Le seed initial copie le footer ancien côté hôte ; le footer nouveau ne
provient pas de l'hôte. Après retour zéro du writer natif de `main`, le
wrapper vérifie le dispatch du manager et appelle l'accesseur natif
`0x00465284` pour le bloc 58. L'objet de métadonnées doit être aligné, en
plage heap et avoir le dispatch attendu. Son getter (`0x004630FC`) et sa
taille sont contrôlés statiquement. Le patch copie 122 mots depuis
`objet+8` dans le sidecar avant de lancer son writer natif. En cas de
provenance inattendue, il n'écrit pas le sidecar et la vérification échoue.

Le préflight valide RAM, inventaire, EventWork, sidecar et archive de départ.
Après SAVE, le lanceur exige le retour natif du sidecar, un footer changé,
un `main` valide et une concordance exacte entre le footer porté par le
sidecar, celui du `main` à `0x75E00` et le sidecar relu en RAM. Le test ne
modifie ni la ROM ni les profils d'origine.

`sidecar-footer-reload` prend un snapshot v2. Il valide l'archive source,
compare ses deux fichiers, répète la vérification dans la copie et
après fermeture. Les modes du rapport 028, qui s'appuient sur un témoin
externe pour refuser un rollback, restent séparés et inchangés.

## Mesures

| Profil privé | Résultat |
| --- | --- |
| `oras-connector-t03fjp0_` | SAVE réussi, 39 READ soumis, zéro WRITE du connecteur, 58 CRC valides et inventaire/EventWork inchangés. |
| `oras-connector-ea0xy9y2` | Nouveau processus, writer absent, 28 READ soumis, zéro WRITE ; 512 octets identiques sur les deux connexions, archive inchangée. |
| `oras-connector-7vqalg81` | Contrôle : ancien `main` CRC-valide, sidecar post-SAVE avec `ASV1`. Manifeste v2 valide mais paire refusée avant lancement, zéro READ/WRITE. |

Seed : `local/oras/backups/before-connector-8ny3zimx`.
SAVE : `before-connector-8012homq` / `after-connector-fab0iiua`.
Cold boot du snapshot `after-connector-fab0iiua` :
`before-connector-wk1v2gle` / `after-connector-vu7undue`.
[Preuves structurées](../research/native-footer-sidecar-results.json).

**261 tests réussis**, dont rejet des deux sens de mélange synthétique,
taille/format, `main` corrompu malgré un footer concordant et capture
bornée entre les deux writers. Aucun item appliqué.

## Limites et suite

Cette comparaison détecte un mélange lorsque les footers diffèrent. Elle
ne prouve pas qu'une paire est récente ou authentique : un rollback
cohérent des deux fichiers, une collision des CRC par bloc ou une paire
fabriquée côté hôte restent possibles. Le footer n'est pas un SHA-256 de
tout `main`. Pas de nouvel essai SIGKILL dans cette phase ; le découpage en
deux écritures n'est pas devenu atomique.

Le format ne contient ni identifiant AP, ni index, ni preuve d'item.
Avant la livraison live, il faut tester un **état de livraison synthétique**
lié au checkpoint et capable de refuser un rollback cohérent via l'ancre
durable du journal. La modification d'inventaire et le replay restent
bloqués.
