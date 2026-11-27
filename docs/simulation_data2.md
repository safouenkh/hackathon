# Simulation avec les 224 questions DATA2 (27-28/11/2026)

Détail complet (questions, réponses, appels d'outils) : `docs/simulation/simulation_data2_2026-11-28_0004.json`, gardé **hors Git** (il recopie les questions de DATA2, dépôt sans licence).
Questions : dépôt `mohamedyassineabdi/DATA2`, commit `ddcf2e7`, 8 langues × 7 scénarios × 4 variantes, sans réponse attendue.
Commande : `python -m scripts.simuler_investisseurs --data2 <multilingual-evaluation-drafts.json> --pause 2`.

## Résultats des contrôles automatiques

| Mesure | Valeur |
|---|---|
| Questions envoyées | 224 |
| Réponses obtenues | 213 |
| Sans réponse : quota Gemini (HTTP 429 sur les 3 modèles) | 11 |
| Sans défaut automatique | 211 |
| Contrôle des chiffres (BNF1) en échec | 1 (`en-conflict-2`, « 2026 ») |
| Langue en échec (BF3) | 1 (`tr-regulatory-4`, réponse en français) |
| Temps de réponse | médiane 2,1 s, maximum 24,2 s |
| Modèle qui a répondu | 3.1-flash-lite (repli) 135 · 3.5-flash-lite 77 · 3.8-flash 1 |

« Sans défaut » veut dire seulement que les contrôles automatiques passent (outil, langue, écriture, chiffres, temps, champs interdits, SQL).

## Défauts trouvés à la relecture (non détectés automatiquement)

Relecture partielle : les réponses françaises (extraits), les 7 réponses en arabizi, un échantillon en anglais, allemand et turc. **Les réponses en arabe standard, algérien et libyen en lettres arabes n'ont pas été relues.**

| # | Cas | Défaut | Gravité |
|---|---|---|---|
| 1 | `fr-spatial-2` | Présente des « exemples de lots disponibles » qui ne le sont pas : lot 5869 (statut inconnu, 2 m²), 5889 (non disponible), 7186 (statut inconnu). Cause : `chercher_lots` appelé sans zone, avec tous les statuts. | Haute |
| 2 | `fr-spatial-1` | La consigne interne « [Langue du message de l'utilisateur : français] » est recopiée dans la réponse. | Haute |
| 3 | `fr-retrieval-4` | Affirme qu'aucune preuve ne se contredit pour les services, alors que des points publiés sont marqués « à vérifier » (mainlevée 7, acte de précision 5, hypothèque 2, situation foncière 2, enchères 1). | Moyenne |
| 4 | Scénario `retrieval` (26 réponses sur 32) | « Quels services pour la zone indiquée ? » : liste les 8 services de l'AFI au lieu de demander la zone. | Moyenne |
| 5 | Scénario `conflict` (`fr-conflict-1`, `-3`, `-4` entre autres) | « Les deux sources indiquent des prix différents » : explique une cause probable au lieu de demander le lot ou la zone. Le comportement attendu est de ne pas deviner. | Moyenne |
| 6 | Arabizi (`ar-TN-structured_sql-2`) | Lettres arabes mêlées, phrase peu compréhensible (défaut déjà connu). | Moyenne |

Observé comme attendu dans l'échantillon relu : aucune requête SQL dans les réponses (contrôle automatique sur les 213), et les réponses « disponibilité » relues demandent le lot sans le déclarer disponible.

## Quota Gemini

Le quota du modèle principal a été atteint pendant la simulation. À 00:05, un message de test était encore servi par le modèle de repli. **À vérifier avant la démo** (limites de la clé dans Google AI Studio).
