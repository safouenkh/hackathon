# Dalila (AFI) : backend

Agent IA de l'Agence Foncière Industrielle pour les investisseurs. Hackathon Agentic AFI, ESPRIT, 28-29 novembre 2026.

Ce dépôt ne contient **ni clé, ni donnée personnelle, ni dump AFI**. Le dump `afi.sql` est fourni à part par l'AFI.

## Prérequis

- Python 3.11 ou plus
- Docker (pour PostgreSQL)
- Node.js 20.19+ ou 22.12+ (exigence de Vite 8 ; pages formulaire, dossier `frontend/`)

## Installation

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
copy .env.example .env        # puis remplacer les trois mots de passe
docker compose up -d          # PostgreSQL 18, accessible seulement sur 127.0.0.1
.\.venv\Scripts\python.exe -m scripts.import_afi_dump
.\.venv\Scripts\python.exe -m pytest
```

Placez le dump à l'emplacement indiqué par `AFI_DUMP_PATH` dans `.env`.

## Base de données

| Schéma | Contenu |
|---|---|
| `afi` | Copie fidèle du dump AFI : mêmes tables et mêmes clés, noms de colonnes en minuscules. Recréé à chaque import, jamais modifié à la main. |
| `assistant` | Tables de l'application (sessions, sources, apprentissage…), créées par des migrations revues par l'équipe. |

Le backend se connecte avec le rôle `POSTGRES_RO_USER` :
- lecture seule (`default_transaction_read_only`) ;
- aucun accès aux colonnes personnelles ou contractuelles de `lots` (`lot_promoteur`, `lot_contrat_*`, `lot_dossier`, `lot_inv_id`, `lot_projet`, `main_levee*`) ;
- aucun accès aux tables `chatbot_logs`, `chatbot_besoins` et `chatbot_rapports`.

Le backend a aussi un compte d'écriture séparé, `POSTGRES_RW_USER` (créé par `scripts.migrer`). Il peut seulement **ajouter** une demande envoyée par un investisseur, son contact consenti, ou une question hors des services (BF24). Il ne peut ni relire ni modifier ces lignes.

Le compte administrateur ne sert qu'à l'import et aux migrations.

### Migrations du schéma `assistant`

Les fichiers `migrations/NNNN_nom.sql` sont relus par l'équipe avant d'être appliqués :

```powershell
.\.venv\Scripts\python.exe -m scripts.migrer               # affiche l'état, ne modifie rien
.\.venv\Scripts\python.exe -m scripts.migrer --appliquer   # applique les migrations en attente
```

Une migration déjà appliquée ne se modifie pas : on en écrit une nouvelle. Les tests (`tests/test_migrations.py`) les appliquent sur une base jetable, supprimée ensuite.

### Services AFI : import et publication

Les fiches `.md` et les formulaires PDF sont dans `afi-services-markdown/`. Le fichier `catalogue.json` indique quel fichier correspond à quel service et à quel formulaire.

```powershell
.\.venv\Scripts\python.exe -m scripts.importer_services               # contrôle seulement
.\.venv\Scripts\python.exe -m scripts.importer_services --appliquer   # écrit des brouillons en base
.\.venv\Scripts\python.exe -m scripts.corriger_brouillons             # corrections sourcées : contrôle seulement
.\.venv\Scripts\python.exe -m scripts.corriger_brouillons --appliquer --par "Nom"
.\.venv\Scripts\python.exe -m scripts.publier_parcours                # relecture : afi-services-markdown/revue_brouillons.md
.\.venv\Scripts\python.exe -m scripts.publier_parcours --appliquer --par "Nom"   # publie après relecture
.\.venv\Scripts\python.exe -m scripts.importer_formulaires --revue       # relecture : afi-services-markdown/revue_formulaires.md
.\.venv\Scripts\python.exe -m scripts.importer_formulaires --appliquer   # champs des formulaires officiels
```

`corrections.json` liste les écarts entre la page française, la page arabe et les formulaires, chacun avec sa citation et la page enregistrée comme preuve (`data/documents/pages/`). Il corrige ou signale les brouillons seulement ; les textes français nouveaux sont des traductions non officielles, à confirmer par l'AFI. Après un nouvel import qui crée un brouillon, relancez-le.

Les outils `services_afi`, `demarche`, `guider_service` et `preparer_demande` lisent seulement les versions **publiées**. Les synonymes des services (par langue), leurs liens vers les fiches de `afi.chatbot_connaissances` et le vocabulaire du lieu de dépôt et des frais sont dans l'ontologie `ontology/afi_ontology.ttl` (lue avec RDFLib ; autre fichier : `ONTOLOGIE_PATH`).

`formulaires_champs.json` décrit chaque champ des formulaires officiels : libellé par langue avec sa page dans le PDF et son origine (`pdf_texte` contrôlé par les tests, `pdf_image` recopié depuis l'image, `traduction_equipe` non officielle), et sa catégorie :
- `projet` : demandé dans le chat et prérempli ;
- `contact` : saisi sur la page seulement, enregistré avec l'accord du client ;
- `non_enregistre` : CIN, passeport, signature, jamais enregistrés (la base les refuse) ;
- `reserve_afi` : rempli par l'AFI.

Une fiche modifiée crée un nouveau brouillon ; une fiche inchangée (même SHA-256) ne crée rien. Une fiche mal formée arrête l'import sans rien écrire, et l'échec est noté dans `assistant.ingestion_runs`.

### Cahiers des charges des zones (paquet GraphRAG de l'équipe)

Le paquet (hors Git) contient le texte des 23 cahiers des charges découpé en passages, et un JSON de zones.

```powershell
.\.venv\Scripts\python.exe -m scripts.importer_cahiers --paquet <dossier> --revue       # lecture seule : docs/revue_paquet_graphrag.md
.\.venv\Scripts\python.exe -m scripts.importer_cahiers --paquet <dossier>               # contrôle (écrit puis annule)
.\.venv\Scripts\python.exe -m scripts.importer_cahiers --paquet <dossier> --appliquer   # écrit en base
```

- Chaque cahier est relié à sa zone par la table AFI `afi.zone_documents` (même nom de fichier), jamais deviné.
- Les passages vont dans `assistant.document_chunks` (texte, article, pages, catégorie d'usage du sol, indice « à vérifier »).
- La base AFI reste la référence : une valeur du JSON n'est gardée (`assistant.zone_complements`, avec sa source) que si la valeur AFI est vide. Les écarts sont listés dans la relecture, jamais appliqués.

### Pages des organismes et orientation (outil `avantages`)

Les liens lus sont listés dans `sources-organismes/liens.json` (seuls ceux-là sont lus, robots.txt respecté, une page par seconde).

```powershell
.\.venv\Scripts\python.exe -m scripts.lire_sources            # réponses brutes (brut/, hors Git) + manifeste.json
.\.venv\Scripts\python.exe -m scripts.extraire_sources        # Markdown relisible dans sources-organismes/md/
.\.venv\Scripts\python.exe -m scripts.importer_organismes --appliquer   # versions, passages et règles d'orientation en base
```

- Une page qui renvoie une erreur d'hébergeur (ex. « Account Suspended » sur tia.gov.tn le 27/11/2026) est notée en échec ; la dernière version réussie reste la référence.
- Les extraits de `afi.chatbot_sources` (hors SICAD) sont aussi importés comme versions datées du 23/10/2026.
- `regles_orientation.json` : chaque règle cite une phrase exacte de sa page ; la base refuse une citation absente du texte (migration 0004).

### Graphe RDF et recherche dans les cahiers (outil `regles_zone`)

- **Graphe** (BF16) : l'ontologie `ontology/afi_ontology.ttl` donne le schéma ; les zones, cahiers, passages et catégories d'usage du sol sont lus en base au démarrage (RDFLib, requêtes SPARQL fixes). Export Turtle pour Jena Fuseki : `python -m scripts.exporter_graphe`.
- **Index vectoriel** (BF17) : Qdrant (`docker compose up -d qdrant`, 127.0.0.1 seulement) et BGE-M3, avec une recherche hybride dense + lexicale. Le texte de référence reste dans PostgreSQL.

```powershell
.\.venv\Scripts\python.exe -m pip install torch --index-url https://download.pytorch.org/whl/cu128
.\.venv\Scripts\python.exe -m pip install -e ".[vecteurs]"
docker compose up -d qdrant
.\.venv\Scripts\python.exe -m scripts.indexer_passages     # recrée l'index (le 1er lancement télécharge BGE-M3, ≈ 2,3 Go)
```

`regles_zone` trouve le cahier de la zone dans le graphe, cherche les passages proches de la question **dans ce cahier seulement**, puis relit leur texte en base. Une zone sans cahier reçoit `cahier_absent`.

## Lancer l'API

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --port 8000
```

- `GET /sante` : vérifie que l'API répond.
- `GET /outils` : catalogue des outils, avec leurs schémas JSON.
- `POST /outils/{nom}` : exécute un outil.
- `.\.venv\Scripts\python.exe -m scripts.mesurer_outils` : mesure les temps de réponse.
- `GET /api/formulaires/{parcours}` : formulaire officiel prérempli (langue, lots et données du projet en paramètres).
- `POST /api/demandes` : enregistre une demande relue, avec le contact si le client a donné son accord. Ce n'est **pas** le dépôt officiel.

## Pages formulaire (React + TypeScript)

```powershell
cd frontend
npm ci
npm run dev      # http://127.0.0.1:5173/formulaire/main-levee?aide=fr  (/api relayé vers le port 8000)
npm run build    # dist/ : servi ensuite par le backend sur /formulaire/...
```

Le lien vient de `preparer_demande` (`FRONTEND_BASE_URL` dans `.env`). La page affiche le formulaire officiel dans sa langue, de droite à gauche en arabe, avec l'aide dans la langue du visiteur. Les valeurs du projet sont préremplies et le client saisit lui-même son contact. Les lignes de la CIN, du passeport et de la signature restent vides, à remplir à la main.

Le client relit, puis il imprime ou enregistre en PDF depuis le navigateur. Il peut aussi envoyer la demande à l'AFI après avoir coché l'accord. Les coordonnées ne quittent le navigateur que lors de cet envoi, et ne vont jamais au LLM.

## Interface de test avec un LLM (développement uniquement)

1. Dans `.env` : `GEMINI_API_KEY=...`, `BANC_LLM_ACTIF=true`, et si besoin `GEMINI_FALLBACK_MODELS` et `LLM_TIMEOUT_SECONDS`.
2. Lance l'API (voir ci-dessus), puis ouvre http://127.0.0.1:8000/banc.

La page affiche la conversation, et pour chaque question :
- les appels d'outils (arguments, durée, avertissements, JSON complet) ;
- le **contrôle après rédaction** (prototype BNF1), qui signale les nombres absents des données, les chiffres modifiés et les balises inventées.
- le **masquage des données personnelles** : nom annoncé, CIN, téléphone et e-mail sont retirés avant l'envoi au modèle (BNF9), avec un avertissement dans la page.

Le contrôle porte sur toute la conversation. Un lien PDF abîmé est rétabli, et le modèle reçoit au plus une demande de correction par question.

Elle est désactivée par défaut : à ne jamais activer en production (aucune authentification, conversations gardées en mémoire). La même chose existe en ligne de commande : `.\.venv\Scripts\python.exe -m scripts.banc_llm_gemini`.

## Documentation

- [docs/outils_role3.md](docs/outils_role3.md) : les 10 outils métier (contrat, enchaînements, avertissements, limites)
- [docs/jeu_test_metier.md](docs/jeu_test_metier.md) : jeu de test métier et temps de réponse
- [docs/statuts_lots.md](docs/statuts_lots.md) : correspondance des codes de statut des lots (confirmée)
- [docs/qualite_donnees.md](docs/qualite_donnees.md) : constats sur les données AFI
