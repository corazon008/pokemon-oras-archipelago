# Rapport 015 — nouvelle sauvegarde durable vérifiée

Date : 18 novembre 2026.

## Résultat réel

L'utilisateur crée une **nouvelle partie**, sauvegarde nativement puis ferme
le profil clavier `local/oras/profiles/oras-save-kkvwuxa5`.
Ce n'est pas une récupération de la partie Pokédex perdue au reboot.

Le snapshot automatique `local/oras/backups/after-exit-72633fon` est vérifié :

- 58 descripteurs/CRC valides.
- `main` identique octet pour octet au fichier du profil.
- Métadonnées Encore de 16 octets identiques.
- Profil et snapshot séparés, tous deux hors `/tmp`.

```text
main SHA-256 :
f7906a7ec9f61e3f9ce8e13510d35269b3b0cb99ff1fe909c6de066fa68e1887
```

Le fichier contient Potion ×1 et le flag Pokédex est faux. Cela fournit une
référence pour les prochains essais, sans demander de rejouer immédiatement
toute la séquence du rival et du laboratoire.

## Rechargement à froid, en lecture

Le connecteur amont est relancé sur le même profil, sans réimport ni savestate :
`local/oras/profiles/oras-save-kkvwuxa5/connector-attempt-xdsx10tv`.

La capture `boot/step-07.png` montre une partie jouable dans la maison du joueur.
Deux connexions vérifient code ROM, inventaire et EventWork complets :

- Potion ×1 sur les deux connexions.
- Flag Pokédex 2722 faux sur les deux connexions.
- Mot 130 à 2 sur les deux connexions ; ce témoin négatif est maintenant
  également lu via l'API AP.
- 6 READ, aucune écriture, sortie 0, fichier sauvegardé inchangé.

Les snapshots pré/post-connecteur sont également publiés sous
`local/oras/backups/before-connector-qqb6_n_g` et
`local/oras/backups/after-connector-uz_l_tk1`. Leurs CRC, fichiers et métadonnées
correspondent à la référence.

## Portée

La création réelle d'une sauvegarde et de copies indépendantes sous le dossier
persistant est maintenant observée. **Aucun second reboot de la machine n'est
revendiqué comme test**. Ces copies restent sur le même stockage et ne remplacent
pas une sauvegarde externe.

Les [résultats structurés](../research/durable-new-save-results.json) ne
distribuent aucun octet propriétaire. Le profil original de l'émulateur n'a pas
été importé ni modifié. Pas d'item reçu, de serveur AP ou de compteur de
livraison supposé dans cette phase.

Suite : fondations du client hors ligne et protocole qui suspend les commandes
dont l'application ou la persistance est incertaine.
