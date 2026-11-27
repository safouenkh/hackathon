# Jeu de test métier du rôle 3 (BNF1, BNF13)

Automatisé dans `tests/test_cas_metier.py`. Chaque valeur attendue vient d'une source **indépendante de l'outil testé**.

- Sources : liste publique https://afi.e-industrie.gov.tn/liste.php (lue le 26/11/2026), fiches de `chatbot_connaissances` (dump du 13/11/2026), requête SQL écrite à part.
- Résultat au 26/11/2026 : **20 tests sur 20 réussis** (M03b ajouté : BF10 en un seul appel).
- 27/11/2026 : M03 et M03b changent avec les compléments de zone (migration 0003) : Gabès 88888 n'a pas de prix dans la base AFI, le JSON du paquet GraphRAG donne 50 Dt/m². M03c (valeur AFI jamais remplacée) et M03d (commodités complétées) ajoutés.

| N° | Question / besoin | Outil(s) | Attendu | Source de l'attendu |
|---|---|---|---|---|
| M01 | Fiche du lot 117 d'Ariana Aéroport | `details_lot` | 34 735 m², 100 Dt/m², Ariana, aux enchères | liste.php : « Ariana \| ARIANA AEROPORT \| 117 \| 34735 \| 100 » ; carte publique : `LOT_ETAPE` 4 = « Mis aux enchères » |
| M02 | Prix du lot 37 de Ras El Morj | `details_lot` | 3 122 m², 70 Dt/m² (dump), avec `prix_ecart_site_public` | liste.php : « … \| 37 \| 3122 \| 90 » ; dump : `prixunitaire` = 70 |
| M03 | « Lot de 3 000 m² près d'un port, le moins cher » (BF10) | `lots_proches` + `chercher_lots` | Lots 4799 (154 250 DT), 4858 (154 400 DT), 4859 (154 450 DT) à Gabès, avec `valeur_complementaire` (sans complément : 7079, 218 540 DT) | Requête SQL indépendante (port ≤ 40 km, `LOT_ETAPE` = 1, surface ≥ 3 000 m², prix AFI sinon complément) |
| M03c | Prix de Ras El Morj (AFI 70, JSON 90) | `details_lot` | 70 Dt/m², sans `valeur_complementaire` | La base AFI n'est jamais remplacée |
| M03d | Commodités de la zone 931300 | `details_lot` | Port 204 km, marqué `valeur_complementaire`, provenance `assistant.zone_complements` | `docs/revue_paquet_graphrag.md` |
| M04 | Lots disponibles à Sfax | `chercher_lots` | 2 | SQL : `gouv_id` = 20 et `LOT_ETAPE` = 1 |
| M05 | Lots disponibles de la zone 931103 (Tejra) | `chercher_lots` | 25 lots, gouvernorat Médenine | SQL ; liste.php range Tejra sous « Mednine » |
| M06 | Même recherche écrite « Sfax », « sfax », « SFAX », « صفاقس », « gouvernorat de Sfax » (BNF13) | `chercher_lots` | Résultats identiques | Comparaison des sorties |
| M07 | Frais des services (BF23) | `demarche` | Situation foncière 50 DT, hypothèque 50 DT, acte de précision 150 DT, copie conforme 15 DT par copie, mainlevée 50 DT | Texte des fiches 18, 19, 20, 22 et 23 |
| M08 | « La banque me demande un papier pour mon prêt » (BF22) | `services_afi` | Attestation d'insertion d'hypothèque en premier | Exemple du cahier des charges |
| M09 | Service hors liste (BF24) | `demarche` | `service_non_couvert` + téléphone +216 71 124 260 | Fiche 26 |
| M10 | Lot orphelin | `details_lot` | Ni zone ni gouvernorat, `lot_orphelin` | `lots.zone_id` = '932107X', absent de `zones` |
| M11 | Préparer une demande (BF11) | `preparer_demande` | `depot_effectue = false`, `confirmation_requise = true` | Règle BF11 |

## Temps de réponse des outils (pour le tableau de mesures)

Mesure : `scripts/mesurer_outils.py`, 50 répétitions, caches chauds, PostgreSQL 18.7 en local (Docker), 26/11/2026.

- Premier appel (chargement des référentiels en mémoire) : 101,7 ms.
- Objectif fixé : < 1 s par outil.

| Outil | p50 (ms) | p95 (ms) | max (ms) |
|---|---|---|---|
| `chercher_lots` | 4,7 | 5,3 | 6,1 |
| `details_lot` | 3,5 | 4,9 | 19,4 |
| `comparer_lots` | 2,4 | 2,6 | 3,3 |
| `lots_proches` (port) | 1,4 | 1,7 | 6,7 |
| `lots_proches` (autour d'une zone) | 0,3 | 0,3 | 0,4 |
| `avantages` (stub) | 0,0 | 0,0 | 0,9 |
| `services_afi` | 4,3 | 6,9 | 11,7 |
| `demarche` | 3,2 | 3,5 | 5,4 |
| `preparer_demande` | 3,9 | 4,6 | 5,7 |

Ces temps ne comprennent ni le LLM ni le réseau. À remesurer sur la machine de démonstration.

## Essais avec un LLM (Gemini `gemini-3.5-flash-lite`, 26/11/2026)

Banc de test : `scripts/banc_llm_gemini.py`. Ce n'est pas l'agent final, qui relève du rôle 1. Les chiffres annoncés ont été comparés à la base.

| Question | Outils appelés | Résultat |
|---|---|---|
| « Je cherche un lot de 3000 m² près d'un port, le moins cher possible » | `chercher_lots` (port, 50 km) | ✅ Lots 7079, 7094 et 7095 en tête, totaux exacts, rayon annoncé ; 11,1 s, 8 965 jetons d'entrée |
| *Même question, version initiale (avant `pres_de`)* | `lots_proches` → `chercher_lots` → `details_lot` | ❌ Surface 2 500–3 500, 2 zones sur 10, « le plus proche » faux ; 24,2 s, 22 960 jetons |
| « n7eb terrain f Sfax » | `chercher_lots` | ✅ Arabizi, 2 lots, totaux exacts |
| « La banque me demande un papier pour mon prêt » | `services_afi` | ✅ Hypothèque (réponse directe, sans question à choix) |
| « Combien coûte une copie conforme ? » | `demarche` | ✅ 15 DT par copie, 4 pièces |
| « Je veux un permis de construire » | `services_afi` | ✅ Hors liste, contact AFI |
| « Réserve-moi le lot 7079 » | `details_lot` | ✅ Refus de réserver, proposition de résumé, écart de prix signalé |
| *Même question, 1er essai* | aucun | ❌ Balise `[[LOT:7079]]` inventée et incomplète : désormais interdite par les consignes et détectée par le banc |
| « عندي مشروع سردين… قريب من الميناء؟ » | `chercher_lots` (erreur de validation, puis 20 km et tri par distance) | ✅ Réponse en tunisien et en lettres arabes, surfaces exactes ; ⚠️ « plus de 159 lots » alors que l'outil en renvoie exactement 159 |

**Leçons pour le rôle 1 :**
1. Moins l'agent a d'outils à enchaîner, moins il se trompe : c'est la raison du filtre `pres_de`.
2. Le modèle peut déformer un chiffre ou inventer une balise. Il faut un contrôle après rédaction : comparer chiffres et balises du texte aux sorties des outils.
3. L'API Gemini a répondu une fois 503 (« high demand ») : prévoir un repli (BNF4).

## Écarts constatés entre le dump et le site public (26/11/2026)

- **Sfax :** le dump compte 2 lots disponibles (`LOT_ETAPE` 1) et 7 aux enchères (4), soit 9. Le site en liste 5.
- **Ensemble des 47 zones publiques :** 80 lots notés 1 ou 4 dans le dump n'apparaissent pas sur le site.

D'où l'avertissement `donnee_non_fraiche`, systématique sur les lots disponibles ou aux enchères.
