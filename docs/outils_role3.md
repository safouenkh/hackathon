# Outils du rôle 3 : guide pour l'agent (rôle 1)

Version du 26 novembre 2026. Le contrat (schémas Pydantic) est dans `backend/app/processing/schemas.py`. **Il reste une proposition, à valider par le rôle 1.**

## Comment appeler les outils

| Moyen | Usage |
|---|---|
| Python | `from app.processing.registre import executer` puis `executer("chercher_lots", {...})`. Les arguments sont validés : un champ inconnu est refusé. |
| REST | `POST /outils/{nom}` avec les arguments en JSON. `GET /outils` liste les 8 outils avec les schémas JSON de leur entrée et de leur sortie. Ces schémas peuvent servir à générer les définitions d'outils du LLM. |
| Lancement | `.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --port 8000` |

Chaque sortie a la même forme :

```json
{ "outil": "...", "donnees": {...}, "provenance": [...], "avertissements": [{"code": "..."}], "balises": [{"type": "LOT", "id": "7079", "libelle": "...", "texte": "[[LOT:7079:Lot 37 - Ras El Morj Monastir]]"}] }
```

Le LLM rédige à partir de `donnees`. Il **recopie les chiffres sans les recalculer**, insère les `balises[].texte` et restitue les `avertissements`.

## Les 8 outils

| Outil | Entrée principale | Ce qu'il renvoie |
|---|---|---|
| `chercher_lots` | `gouvernorat`, `zone_ids`, `zone_nom`, `surface_min_m2`, `surface_max_m2`, `budget_max_dt`, `pres_de` + `distance_max_km`, `tri` (`prix_total` ou `distance_equipement`), `statuts` (défaut : `["disponible"]`), `limite` ≤ 50 | Lots triés par prix total indicatif ou par distance à l'équipement, avec `distance_equipement_km` et `equipement_nom` ; `total_correspondants` |
| `details_lot` | `lot_id` | Lot, zone, commodités (aéroport, port, gare, autoroute, GP, électricité, eau, gaz, téléphone, GMG, OTC), services proches (OSM), documents de zone, polygone présent ou non |
| `comparer_lots` | `lot_ids` (2 à 10) | Une ligne par lot avec ses distances, et les meilleurs lots par critère (prix total, prix au m², surface, chaque type de distance) |
| `lots_proches` | `type` (`port`, `gare`, `aeroport`, `autoroute`, `route_gp`, `bank`, `hospital`…) **et/ou** une référence (`lot_id`, `zone_id`, `point`), plus `distance_max_km` | Zones triées par distance, avec le nombre de lots disponibles et aux enchères |
| `avantages` | `activite`, `gouvernorat`, `zone_id` | Incitations **avec leurs sources**. **STUB** en attendant le rôle 2 : liste vide + `source_indisponible` |
| `services_afi` | `besoin` (texte libre, facultatif) | Les 8 services, les services candidats et des balises `CHOIX` pour la question à choix (BF22), plus le contact AFI |
| `demarche` | `service` (id), `variante` (acquisition : `developpement_regional` ou `littoral_grand_tunis`) | Pour chaque fiche : conditions, étapes, pièces par phase, frais, lieu de dépôt, texte source et URL. Service inconnu : `service_non_couvert` + contact AFI (BF24) |
| `preparer_demande` | `lot_ids`, `projet` (activité, emplois, investissement, surface, gouvernorat : **aucune donnée personnelle**), `service`, `variante` | Résumé (lots, totaux, pièces, frais, lieu de dépôt), informations manquantes, liens. `depot_effectue = false` et `confirmation_requise = true`, toujours |

Identifiants des services : `acquisition`, `encheres`, `situation_fonciere`, `insertion_hypotheque`, `mainlevee`, `acte_precision`, `autorisation_vente_leasing`, `copie_conforme`.

## Enchaînement type (BF10 : « lot de 3 000 m² près d'un port, le moins cher »)

**Un seul appel suffit :**

```json
{"surface_min_m2": 3000, "pres_de": "port", "distance_max_km": 40}
```

Le tri par défaut est déjà le prix croissant. Viennent ensuite `comparer_lots`, puis `preparer_demande` si l'investisseur choisit un lot.

Résultat sur le dump du 13/11/2026 : lot 37 de Ras El Morj Monastir, port de Sousse à 35 km, 3 122 m² × 70 Dt/m² = 218 540 DT (prix indicatif).

**Règles de `pres_de` :**
- `pres_de` exige un rayon (`distance_max_km`) ou `tri=distance_equipement`. Sans l'un ou l'autre, aucun filtre ne s'appliquerait, et un lot à 150 km serait présenté comme « proche ». Ce cas renvoie donc une erreur de validation, que le LLM corrige lui-même (observé avec Gemini).
- `lots_proches` reste utile pour lister des **zones** (par exemple « quelles zones sont près d'une gare ? »).

## Avertissements à restituer

| Code | Ce que l'agent doit faire comprendre |
|---|---|
| `prix_indicatif` | Prix d'un instantané (13/11/2026), pas un prix actuel |
| `prix_ecart_site_public` | Le site AFI affichait un autre prix le 26/11/2026 : à vérifier auprès de l'AFI |
| `prix_inconnu`, `prix_suspect` | Pas de prix communicable : ne rien estimer |
| `donnee_non_fraiche` | Disponibilité à reconfirmer auprès de l'AFI |
| `statut_inconnu` | Lot « gris » : pas d'information |
| `lot_orphelin` | Lot sans zone connue |
| `surface_invalide` | Surface absente ou ≤ 0 dans les données |
| `activite_non_filtree` | La base ne dit pas quelles activités sont autorisées par zone (cahiers des charges : rôle 2) |
| `budget_non_verifiable` | Des lots sans prix ont été écartés d'une recherche par budget |
| `resultats_tronques` | Il existe plus de résultats que ceux affichés |
| `distance_ambigue`, `coordonnees_manquantes` | Distance inconnue pour certaines zones |
| `document_sans_lien` | Le document existe, mais aucune URL publique n'est connue |
| `besoin_non_reconnu` | Poser la question à choix avec les 8 services |
| `service_non_couvert` | Donner le contact AFI, sans inventer de démarche |
| `lieu_depot_non_precise`, `frais_non_chiffres` | La source ne le précise pas : ne rien compléter |
| `source_indisponible` | Incitations indisponibles (le retrieval du rôle 2 n'est pas branché) |
| `confirmation_requise` | Rien n'est déposé : l'investisseur dépose lui-même |

## Interface attendue du rôle 2 (incitations)

`backend/app/processing/avantages.py` définit le protocole `SourceIncitations.rechercher(activite, gouvernorat, zone_id, limite)`, qui renvoie une liste d'`Incitation` (intitulé, extrait exact, organisme, URL ou document + page, date). On le branche au démarrage avec `brancher_source(impl)`. Une incitation sans URL ni document est écartée.

## Limites connues

- **Données :** elles datent du dump du 13/11/2026, sans lecture en direct du site AFI. Statuts et prix peuvent avoir changé : le 26/11, le site listait 720 lots, et 80 lots notés 1 ou 4 dans le dump n'y figuraient plus.
- **Activités :** pas de filtre par activité autorisée (absente des tables SQL).
- **Regroupement :** pas de regroupement de lots adjacents (l'ancienne `RechercheTerrain` le faisait) ; à étudier avec les polygones de `lots_kml`.
- **Proximité :** la distance aux équipements est celle saisie par l'AFI (`zone_commodites.value`), ou celle d'OSM pour les services. Les distances « depuis un point » sont à vol d'oiseau, d'après les coordonnées de la zone.
- **Orientation BF22 :** elle repose sur des mots-clés (français, anglais, arabe, quelques formes tunisiennes). La compréhension fine des 8 langues relève des rôles 2 et 4.
