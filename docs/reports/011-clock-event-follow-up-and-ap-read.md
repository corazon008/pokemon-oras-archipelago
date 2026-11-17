# Rapport 011 — suite manuelle et lecture du candidat via AP

Date : 17 novembre 2026.

## Résultat

Le jeu manuel a produit une nouvelle sauvegarde valide : **`work[130]` passe
de 3 à 4**. Le rechargement montre le personnage au rez-de-chaussée, près de
maman et de la télévision.

Les états **3 et 4** sont ensuite lus via l'API Python et le connecteur Lua
génériques d'Archipelago, avant/après reconnexion. Chaque lecture du bloc
EventWork complet correspond à une sauvegarde dont les 58 CRC sont valides.
Aucune écriture mémoire, aucun changement de fichier sauvegardé durant
ces sondes.

**Le test `work[130] == 3` ne serait donc pas un indicateur permanent.**
L'outillage ne l'emploie pas et n'invente pas non plus une règle `>= 3`.

## Suite de la session clavier

Le rapport 010 décrit le contournement d'une entrée bloquée. L'utilisateur a
accepté le clavier et indiqué ne pas avoir besoin d'une nouvelle copie.
Le profil `/tmp/opencode/oras-save-ev5_8vq1` a été réutilisé, sans nouvel import.

L'essai manuel `attempt-z2tn_bf_` se termine proprement avec :

```text
main SHA-256 :
99c19458cf96f097f15f0e63c1d0fe72d689f06d76cc3bebe48dc0224d548356

EventWork SHA-256 :
56973ed746824c0303eecfbb73e67a068baa18825e9d2686d50281d2605fa6ed
```

Différences par rapport à la sauvegarde d'après horloge/conversation :

| Mot décimal | Avant | Après |
|---|---:|---:|
| 10 | 0 | 1 |
| 17 | 1 | 0 |
| 115 | 0 | 1 |
| 130 | 3 | 4 |

Aucun flag différent et aucun changement de la fin inconnue du bloc.
Le retour du mot 17 à zéro confirme qu'il ne fallait pas le retenir comme
preuve de fin de scène.

Les actions intermédiaires n'ont pas été capturées par une macro. Le résultat
prouve une progression depuis l'état 3, pas l'ordre exact des dialogues joués.
Le démarrage suivant, `attempt-u3al77pe`, montre le rez-de-chaussée près de la TV,
avec deux lectures complètes conformes et le mot 130 à 4. Aucun savestate.

## Lecture via l'API AP

Deux profils existants sont réutilisés en lecture seule :

| Profil | Preuve privée | Valeurs aux connexions |
|---|---|---|
| `oras-save-pmlcj2zw` | `connector-attempt-guej9ygb` | 3, 3 |
| `oras-save-ev5_8vq1` | `connector-attempt-hu7mlw_0` | 4, 4 |

Pour chaque connexion :

1. Version du script, système 3DS et domaines vérifiés.
2. Préfixe de code ROM relu et comparé.
3. Inventaire complet relu et comparé à la sauvegarde.
4. Bloc EventWork complet relu et comparé à la sauvegarde.
5. Classification bornée du mot 130.

Donc **6 READ par essai**, aucune GUARD/WRITE envoyée. Les deux processus se
terminent proprement. Les fichiers `main` restent identiques à leur empreinte
avant lancement. Les dépendances AP restent intactes au commit
`cf08efe5b1c132bf966ae810c007b8268d47b7b0`.

Le catalogue conserve les adresses vérifiées sur le SHA-256 OR exact :
bloc `System Bus:0x08C7DAEC`, champ `0x08C7DBF0`. Aucun résultat AS.

## Classification prudente, pas encore une location

`clock_scene_observation` classe uniquement les valeurs observées :

| Valeur | Résultat expérimental |
|---:|---|
| 2 | Scène non terminée dans les témoins du rapport 009 |
| 3 | Séquence horloge/maman terminée, sauvegardée et rechargée |
| 4 | État ultérieur obtenu par jeu manuel, sauvegardé et rechargé |
| Autre | **Inconnu (`null`)** |

Les valeurs inconnues ne deviennent ni vraies par un seuil numérique, ni
fausses par défaut. Le résultat porte `production_location_approved: false`.
Le passage par un état futur ou un retour d'état doit suspendre une éventuelle
réconciliation de client, pas provoquer une livraison ou un check implicite.

Le mot 130 est une variable de scénario, pas un bit persistant indépendant.
La permanence sur toute la partie n'est toujours pas démontrée. La valeur 2
a des témoins natifs réels mais n'a pas encore été relue via le pont AP dans
cette phase. Le classificateur ne constitue pas un client de jeu fonctionnel.

## Fichiers et reproduction

Créés :

- `tools/oras_connector_events.py` : référence CRC-validée, lecture AP complète,
  classification limitée aux états observés.
- `tests/test_connector_events.py`.
- [Résultats structurés](../research/clock-event-follow-up-results.json)
  et présent rapport.

Modifiés : lanceur du connecteur, catalogue de candidats, résultats de recherche
et documentation.

```sh
python3 tools/run_bizhawk_connector_probe.py \
  --rom "/chemin/vers/OR-verifie.3ds" \
  --session /tmp/opencode/oras-save-IDENTIFIANT \
  --read-event-work --speed 400 --timeout 150
```

`--session` accepte uniquement un profil créé par l'outillage, dont le manifeste
correspond au SHA-256 de la ROM. Aucun réimport ni copie de runtime. Le résultat
est dans un nouveau `connector-attempt-*`, sans remplacer les résultats natifs.
Fermer auparavant tout émulateur utilisant ce profil.

Le lancement réisole les chemins et remet la vitesse par défaut à 100 avant
l'éventuelle macro accélérée. Les bindings clavier du profil sont conservés.
`--session` est incompatible avec `--seed-save` et avec l'expérience d'écriture.
`--read-event-work` est également incompatible avec l'écriture expérimentale.
La macro par défaut ouvre la partie, pas le sac. Une référence d'inventaire
non nulle est encore exigée par ce diagnostic combiné.

## Tests et suite

**85 tests unitaires réussis**. Nouveaux tests : états inconnus, mauvais build,
CRC corrompus, référence complète avant/après reconnexion, absence de garde
de code, lecture incohérente, manifeste/chemins incompatibles et runtime
symlink refusé. Les tests synthétiques ne remplacent pas les essais ci-dessus.

La source initiale conserve le SHA-256
`7fe9813cf5ed377e67da4d9e279a69cd63efc697b1a07c3b6f9354a85896f465`.

Suite : sélectionner un indicateur dont la permanence et les états tardifs sont
établis, puis développer l'interface client et le protocole de livraison avec
persistance/dédoublonnage. Aucun serveur, `LocationChecks`, `ReceivedItems`,
index persistant ou APWorld n'est prétendu validé par cette phase.
