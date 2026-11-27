# Outils du rôle 3 : guide pour l'agent (rôle 1)

Version du 26 novembre 2026. Le contrat (schémas Pydantic) est dans `backend/app/processing/schemas.py`. **Il reste une proposition, à valider par le rôle 1.**

## Comment appeler les outils

| Moyen | Usage |
|---|---|
| Python | `from app.processing.registre import executer` puis `executer("chercher_lots", {...})`. Les arguments sont validés : un champ inconnu est refusé. |
| REST | `POST /outils/{nom}` avec les arguments en JSON. `GET /outils` liste les 10 outils avec les schémas JSON de leur entrée et de leur sortie. Ces schémas peuvent servir à générer les définitions d'outils du LLM. |
| Lancement | `.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --port 8000` |

Chaque sortie a la même forme :

```json
{ "outil": "...", "donnees": {...}, "provenance": [...], "avertissements": [{"code": "..."}], "balises": [{"type": "LOT", "id": "7079", "libelle": "...", "texte": "[[LOT:7079:Lot 37 - Ras El Morj Monastir]]"}] }
```

Le LLM rédige à partir de `donnees`. Il **recopie les chiffres sans les recalculer**, insère les `balises[].texte` et restitue les `avertissements`.

## Les 11 outils

| Outil | Entrée principale | Ce qu'il renvoie |
|---|---|---|
| `chercher_lots` | `gouvernorat`, `zone_ids`, `zone_nom`, `surface_min_m2`, `surface_max_m2`, `budget_max_dt`, `pres_de` + `distance_max_km`, `tri` (`prix_total` ou `distance_equipement`), `statuts` (défaut : `["disponible"]`), `limite` ≤ 50 | Lots triés par prix total indicatif ou par distance à l'équipement, avec `distance_equipement_km` et `equipement_nom` ; `total_correspondants` |
| `details_lot` | `lot_id` | Lot, zone, commodités (aéroport, port, gare, autoroute, GP, électricité, eau, gaz, téléphone, GMG, OTC), services proches (OSM), documents de zone, polygone présent ou non |
| `comparer_lots` | `lot_ids` (2 à 10) | Une ligne par lot avec ses distances, et les meilleurs lots par critère (prix total, prix au m², surface, chaque type de distance) |
| `lots_proches` | `type` (`port`, `gare`, `aeroport`, `autoroute`, `route_gp`, `bank`, `hospital`…) **et/ou** une référence (`lot_id`, `zone_id`, `point`), plus `distance_max_km` | Zones triées par distance, avec le nombre de lots disponibles et aux enchères |
| `avantages` | `activite`, `secteur`, `investissement_dt`, `investisseur_etranger`, `question`, `gouvernorat`, `zone_id` | Secteurs reconnus (ontologie), **organisme(s) compétent(s)** selon les règles sourcées de `assistant.regles_orientation` (citation exacte + lien : APIA pour l'agricole, TIA ≥ 15 MDT, APII < 15 MDT hors agricole, FIPA pour un investisseur étranger), et **extraits** des pages de ces organismes (texte exact, lien, date). Condition inconnue (montant, nationalité) : jamais supposée, `montant_a_preciser` / `nationalite_a_preciser`. Index absent : `source_indisponible` |
| `services_afi` | `besoin` (texte libre, facultatif) | Les services actifs (schéma `assistant`), les services candidats et des balises `CHOIX` pour la question à choix (BF22), plus le contact AFI |
| `demarche` | `service` (code donné par `services_afi`), `parcours` (code, si le service en a plusieurs) | Pour chaque parcours **publié** : conditions, étapes, pièces (avec sous-lignes et phases), frais en dinars, lieu de dépôt, lignes de paiement sans montant, formulaire (PDF par langue, ligne à cocher), URL source et date. Plus les fiches validées de l'AFI en complément. Service inconnu : `service_non_couvert` + contact AFI (BF24) |
| `guider_service` | `parcours` (code), `position` (0, puis `suivant`) | **Un point à la fois** : présentation (si l'ontologie en désigne une), conditions, pièces, formulaire, étapes, frais, puis lieu de dépôt (ou contact AFI s'il n'est pas dans la source). Avec `total`, `plan`, `precedent` et `suivant` |
| `preparer_demande` | `service` (code, **obligatoire**), `parcours`, `lot_ids`, `projet` (activité, emplois, investissement, surface, gouvernorat : **aucune donnée personnelle**) | Résumé (lots, totaux, pièces, frais, lieu de dépôt, formulaire), informations manquantes, liens, et `formulaires_preremplis` : pour chaque langue officielle, le lien de la page du formulaire, les valeurs préremplies (champs « projet » seulement) et `champs_projet_a_completer` (ce que l'agent peut encore demander). `depot_effectue = false` et `confirmation_requise = true`, toujours |
| `noter_besoin` | `question` (≤ 500 caractères, sans nom ni numéro), `langue` | Note la question hors des services dans `assistant.besoins_non_couverts` (BF24). `note = false` si l'enregistrement est indisponible |
| `regles_zone` | `question`, et **une** zone : `zone_id`, `zone_nom` ou `lot_id` ; `categorie` (code d'usage du sol, facultatif), `limite` ≤ 8 | Cahier de la zone (graphe RDF, lien `afi.zone_documents`), catégories qu'il définit, et les passages les plus proches de la question **dans ce cahier seulement** (Qdrant, hybride dense + lexical), avec texte exact relu en base, article, chapitres, pages, catégorie et `a_verifier`. Zone sans cahier : `cahier_absent` |

Rien n'est écrit dans le code : les services, parcours, textes, montants et formulaires viennent des **versions publiées** du schéma `assistant` ; les synonymes, les liens vers les fiches de `afi.chatbot_connaissances`, le vocabulaire du lieu de dépôt et des frais, et le lien entre statut d'un lot et service viennent de l'ontologie `ontology/afi_ontology.ttl`. Chaque ligne garde son identifiant (`assistant.parcours_elements.id`) ; une ligne corrigée d'après une autre source porte `corrige = true`, `a_verifier = true` et sa preuve dans `note_verification`.

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
| `valeur_complementaire` | Prix ou commodité absent de la base AFI, repris de `assistant.zone_complements` (JSON du paquet GraphRAG, origine non documentée) : à confirmer auprès de l'AFI. Une valeur AFI présente n'est jamais remplacée |
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
| `lieu_depot_non_precise` | La source ne dit pas où déposer : inviter poliment à contacter l'AFI (`contact_afi`), sans deviner |
| `frais_non_chiffres` | La source cite un paiement sans montant : ne rien compléter |
| `point_a_verifier` | Une ligne est à confirmer auprès de l'AFI (`note_verification` dit pourquoi) |
| `parcours_a_choisir` | Le service a plusieurs parcours : question à choix avec les balises `CHOIX` |
| `demarche_non_publiee`, `parcours_inconnu` | Aucune démarche publiée : contact AFI |
| `position_hors_parcours` | `position` dépasse le dernier point du guidage |
| `source_indisponible` | Incitations indisponibles (le retrieval du rôle 2 n'est pas branché) |
| `confirmation_requise` | Rien n'est déposé : l'investisseur dépose lui-même |
| `valeur_non_preremplie` | Les lots choisis diffèrent sur ce champ (`detail` = code du champ) : l'investisseur le remplit |
| `formulaire_indisponible` | Le parcours n'a pas de formulaire en ligne (ex. enchères) : suivre la démarche |

## Interface attendue du rôle 2 (incitations)

`backend/app/processing/avantages.py` définit le protocole `SourceIncitations.rechercher(activite, gouvernorat, zone_id, limite)`, qui renvoie une liste d'`Incitation` (intitulé, extrait exact, organisme, URL ou document + page, date). On le branche au démarrage avec `brancher_source(impl)`. Une incitation sans URL ni document est écartée.

## Confidentialité et contrôle de la réponse (à reprendre dans l'agent du rôle 1)

Essai en conditions réelles du 27/11/2026 avec Gemini ; le banc (`backend/app/banc/`) applique déjà ces trois protections :

- **Aucune donnée personnelle vers le LLM (BNF9)** : `masquer()` (`processing/confidentialite.py`) remplace le nom annoncé (« esmi … », « je m'appelle … »), la CIN ou le passeport, le téléphone et l'e-mail par des marques (`[nom masqué]`…). L'agent dit alors de les saisir sur la page du formulaire. Limite : un nom donné sans annonce n'est pas reconnu.
- **Contrôle sur toute la conversation** : un nombre, une adresse ou une balise doit venir d'un outil **de la conversation**, pas seulement du dernier tour. Cas réel corrigé : une adresse de l'AFI inventée.
- **Balises abîmées** : une URL de PDF recopiée de travers est rétablie d'après les balises des outils (jamais d'un lot à un autre). Si le contrôle trouve encore un défaut, le modèle reçoit **une seule** demande de correction.

## Limites connues

- **Données :** elles datent du dump du 13/11/2026, sans lecture en direct du site AFI. Statuts et prix peuvent avoir changé : le 26/11, le site listait 720 lots, et 80 lots notés 1 ou 4 dans le dump n'y figuraient plus.
- **Activités :** pas de filtre par activité autorisée (absente des tables SQL).
- **Regroupement :** pas de regroupement de lots adjacents (l'ancienne `RechercheTerrain` le faisait) ; à étudier avec les polygones de `lots_kml`.
- **Proximité :** la distance aux équipements est celle saisie par l'AFI (`zone_commodites.value`), ou celle d'OSM pour les services. Les distances « depuis un point » sont à vol d'oiseau, d'après les coordonnées de la zone.
- **Orientation BF22 :** elle repose sur les synonymes de l'ontologie (saisis par l'équipe, en attendant l'apprentissage BF18) et les mots-clés des fiches de l'AFI. La compréhension par le sens (BF17) reste à faire.
- **Lieu de dépôt :** la page de l'AFI ne le donne que pour l'acquisition ; pour les autres services, l'agent oriente vers le contact de l'AFI.
- **Qualité du tunisien :** avec `gemini-3.5-flash-lite`, les réponses en arabizi mélangent souvent français et arabizi. `gemini-3.5-flash` écrit plus naturellement mais a mis 25 s pour une phrase le 27/11 (limite du projet : 35 s par réponse).
- **Guidage :** la position est portée par la conversation (argument `position`) ; l'enregistrer côté serveur demandera une table de sessions (migration à relire).
- **Formulaires :** l'agent ne demande jamais l'identité dans le chat (nom, société, CIN, passeport, adresse, téléphone, e-mail) : l'investisseur la saisit sur la page. La page d'acquisition « confirmation » (pages 3-4 des PDF, à renvoyer dans les 6 mois) n'est pas encore proposée.
