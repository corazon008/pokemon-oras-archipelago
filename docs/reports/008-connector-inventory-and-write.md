# Rapport 008 — inventaire via AP et première écriture contrôlée

Date : 17 novembre 2026.

## Résultat réel

**Potion 1 → 2 écrite via l'API Python et le connecteur Lua génériques
d'Archipelago, puis retrouvée dans la sauvegarde et le sac après redémarrage.**

Une seule requête d'écriture de 2 octets dans une nouvelle copie privée.
La sauvegarde source conserve Potion ×1 ; son fichier et ses métadonnées
d'archive conservent leurs SHA-256.

Cela valide un accès mémoire expérimental, **pas une réception d'item depuis
un serveur Archipelago**, ni un protocole de livraison fiable.

## Configuration

- BizHawk 2.11.1 Linux x86_64, cœur Encore fourni ; empreintes des binaires
  relevées dans les résultats privés.
- Rubis Oméga, Program ID `000400000011C400`.
- SHA-256 ROM :
  `d76faafacd746fdcc5ec04a60b8b82ceb9678c3ad937b374234a506c50c417e4`.
- Version commerciale de mise à jour toujours non vérifiée ; profil isolé
  sans ajout de mise à jour ou mod du profil d'origine.
- Connecteur/API AP au commit
  `cf08efe5b1c132bf966ae810c007b8268d47b7b0`, fichiers amont intacts et SHA-256 vérifiés.
- Sauvegarde source validée sur ses 58 blocs ; copie de `main` et du fichier
  Encore `00000001.metadata` de 16 octets seulement.
- Démarrage natif, sans savestate, puis poche Médecine ; vitesse automatisée 400 %.

## Essai 1 — lectures seules et reconnexion

Preuve privée : `/tmp/opencode/oras-connector-2o7yz6sn`.

Deux connexions successives, chacune avec :

1. Version du script, système `3DS` et tailles des domaines vérifiés.
2. Lecture des 64 octets de code à `0x00100000`, comparés à la ROM.
3. Lecture des 2 960 octets d'inventaire à `System Bus:0x08C6AC80`,
   comparés au bloc extrait de la sauvegarde CRC-valide.

Les deux lectures contiennent Potion ×1 et sont identiques au bloc complet
déjà observé via Lua et dans le sac. **4 requêtes READ, aucune écriture**,
fermeture propre. Le connecteur reprend sur un autre port de sa plage après
déconnexion ; aucun état mémoire n'est supposé conservé sans relecture.

## Essai 2 — écriture bornée

Preuve privée : `/tmp/opencode/oras-connector-s2xbk_zf`.

Nouvelle copie créée depuis la source intacte, pas depuis l'essai de rejet
natif du rapport 007. L'option explicite `--experimental-potion-1-to-2` :

- Refuse tout autre SHA-256 ROM, domaine, adresse, préfixe de code ou slot.
- Exige Potion (ID 17) au slot 0 Médecine et quantité exactement 1.
- Exige une seule occurrence de l'ID Potion dans l'inventaire.
- Recontrôle code et inventaire au démarrage et après première reconnexion.
- Envoie **un seul appel `api.guarded_write`** : deux GUARD, puis un WRITE.

Gardes et écriture sont regroupées dans une même liste traitée par le
connecteur amont, sans frame émulée entre les requêtes de cette liste :

| Opération | Domaine/adresse | Longueur |
|---|---|---|
| GUARD code | `System Bus:0x00100000` | 64 |
| GUARD inventaire avant modification | `System Bus:0x08C6AC80` | 2 960 |
| WRITE quantité 2, uint16 little-endian | `System Bus:0x08C6B5F2` | 2 |

Le connecteur accuse l'écriture. Une lecture immédiate du bloc complet
vérifie la référence initiale avec **uniquement le champ quantité remplacé**.
Une troisième connexion relit code et inventaire : quantité 2, mêmes autres
octets. Total : **7 READ, 2 GUARD, 1 WRITE**. GUARD implique ses propres lectures
mémoire mais n'est pas compté comme requête READ.

Le JSON distingue référence issue de sauvegarde et référence calculée après
transition : `matches_validated_save: false` après écriture signifie que le
bloc diffère de la source ×1 ; `matches_reference: true` valide alors le bloc ×2.

Une réponse perdue laisse l'état « soumis, résultat inconnu ». Aucun renvoi,
rollback RAM ou nouvelle tentative d'écriture automatique. Un accusé WRITE seul
ne valide ni la relecture, ni la sauvegarde.

## Persistance native et redémarrage

Après vérification RAM et reconnexion seulement, Python déclenche la macro
SAVE par un fichier local. Un callback de frames applique des boutons natifs ;
il ne lit ni n'écrit la mémoire. Le connecteur amont n'est pas modifié.

Le message de sauvegarde est observé dans `native-save/step-10.png`.
Après fermeture propre :

```text
main SHA-256 :
6b816069a6cc13b56efd55f8e95343f8a862766e7ca942168b7b19c44b558018

inventaire SHA-256 :
c700b8de203ea03c6b58800cbf451beb41ada1a4b64693bf5587d28f1fb4cc9f
```

Les 58 CRC sont valides et le bloc inventaire correspond entièrement à
la référence ×2.

Nouvel essai, dans un nouveau processus, sur ce profil sans réimport :
`/tmp/opencode/oras-connector-s2xbk_zf/attempt-a5eoayw3`.
Le sac affiche **Potion ×2** (`step-13.png`) ; une lecture Lua complète
correspond au fichier validé. Aucun savestate, aucune écriture mémoire.
Le fichier conserve son SHA-256.

La source utilisateur reste à :
`7fe9813cf5ed377e67da4d9e279a69cd63efc697b1a07c3b6f9354a85896f465`.
Les [résultats structurés](../research/connector-inventory-write-results.json)
conservent chemins, compteurs et limites sans distribuer d'octets propriétaires.

## Reproduction

Lecture seule :

```sh
python3 tools/run_bizhawk_connector_probe.py \
  --rom "/chemin/vers/OR-verifie.3ds" \
  --seed-save "/chemin/prive/00000001/main" --speed 400 --timeout 150
```

Pour l'écriture bornée, ajouter `--experimental-potion-1-to-2`.
Ne pas lancer plusieurs connecteurs simultanément.

Rechargement natif séparé après réussite :

```sh
python3 tools/run_bizhawk_save_probe.py \
  --rom "/chemin/vers/OR-verifie.3ds" \
  --session /tmp/opencode/oras-connector-IDENTIFIANT \
  --read-inventory --speed 400 --timeout 150 \
  --steps '1800:-,2:A,600:-,2:A,600:-,2:A,600:-,2:X,60:-,2:A,120:-,2:Right,60:-'
```

Les macros supposent le contexte UI observé ; une macro terminée ne suffit
pas à identifier un état sûr. Captures, relecture et fichier restent nécessaires.

## Fichiers et tests

Créés :

- `tools/oras_connector_inventory.py` : références de lecture et exception
  d'écriture strictement bornée.
- `tools/bizhawk_connector_post_ui.lua` : boutons natifs après signal de réussite.
- `tests/test_connector_inventory.py`.
- Présent rapport et résultats JSON associés.

Modifiés :

- Lanceur et wrapper du connecteur : import privé, démarrage natif, lectures,
  écriture explicite, relecture/reconnexion et contrôle du fichier résultant.
- Lanceur de sauvegarde : import d'archive réutilisable, CRC et copie conservés.
- Tests UI, catalogue mémoire, README et matrice de validation.

**67 tests unitaires réussis**, sur données synthétiques :

- Mauvais build, code, domaine, slot, quantité ou référence refusés.
- Références invalides et CRC corrompus refusés.
- Reconnexion avec code/inventaire différent : aucune écriture.
- Gardes code + inventaire et écriture unique, sans retry.
- Garde refusée, réponse perdue ou relecture incohérente : échec.
- Macro postérieure inactive avant signal, sans API mémoire.
- Copie d'archive et refus d'écraser un fichier existant.

Les substitutions d'API des tests ne sont pas des preuves en jeu. Le rejet
d'une garde volontairement fausse n'a pas été testé dans l'émulateur.
Les trois essais réels ci-dessus se sont terminés proprement, sans nouvel
incident SDL. Le contournement HIDAPI reste limité aux processus automatisés.

Limite repérée dans `send_receive` du connecteur amont : une garde renvoyant
`false` annule les commandes suivantes, mais une **exception Lua** dans un
handler produit `ERROR` sans annuler nécessairement les requêtes suivantes
du lot. L'API Python lève alors une erreur ; elle ne prouve pas l'absence
d'écriture. L'essai traite ce cas comme résultat inconnu, sans sauvegarde
déclenchée ni retry. Aucun tel incident n'a été observé ici.
Ce comportement doit être pris en compte avant un protocole de livraison
destiné à une partie principale ; les gardes ne sont pas une transaction
générale avec rollback.

## Portée et suite

- BH-05 OR : inventaire lu via Python/AP, concordant avec Lua/sauvegarde/UI.
- BH-06/BH-07 OR : transition minime, relecture et persistance démontrées.
- BH-09 : contrôles mémoire après reconnexion validés dans ce scénario seulement.
- `write_allowed: false` reste dans le catalogue ; aucune API d'écriture libre.
- Aucun détecteur général de combat, menu sûr, pointeur dynamique ou révision inconnue.
- Aucun événement permanent, serveur AP, index persistant, dédoublonnage,
  nouvelle poche ou livraison idempotente encore validé.
- AS : adresses et inventaire toujours non validés.

Suite : identifier un événement permanent réel, avec comparaison avant/après,
témoins négatifs et rechargement. L'architecture `GameInterface`, le protocole
de livraison et l'APWorld minimal viendront ensuite ; aucun prototype complet
n'est prétendu ici.
