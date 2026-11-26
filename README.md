# Dalila (AFI) : backend

Agent IA de l'Agence Foncière Industrielle pour les investisseurs. Hackathon Agentic AFI, ESPRIT, 28-29 novembre 2026.

Ce dépôt ne contient **ni clé, ni donnée personnelle, ni dump AFI**. Le dump `afi.sql` est fourni à part par l'AFI.

## Prérequis

- Python 3.11 ou plus
- Docker (pour PostgreSQL)

## Installation

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
copy .env.example .env        # puis remplacer les deux mots de passe
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

Le compte administrateur ne sert qu'à l'import et aux migrations.

## Lancer l'API

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --port 8000
```

- `GET /sante` : vérifie que l'API répond.
- `GET /outils` : catalogue des outils, avec leurs schémas JSON.
- `POST /outils/{nom}` : exécute un outil.
- `.\.venv\Scripts\python.exe -m scripts.mesurer_outils` : mesure les temps de réponse.

## Interface de test avec un LLM (développement uniquement)

1. Dans `.env` : `GEMINI_API_KEY=...`, `BANC_LLM_ACTIF=true`, et si besoin `GEMINI_FALLBACK_MODELS` et `LLM_TIMEOUT_SECONDS`.
2. Lance l'API (voir ci-dessus), puis ouvre http://127.0.0.1:8000/banc.

La page affiche la conversation, et pour chaque question :
- les appels d'outils (arguments, durée, avertissements, JSON complet) ;
- le **contrôle après rédaction** (prototype BNF1), qui signale les nombres absents des données, les chiffres modifiés et les balises inventées.

Elle est désactivée par défaut : à ne jamais activer en production (aucune authentification, conversations gardées en mémoire). La même chose existe en ligne de commande : `.\.venv\Scripts\python.exe -m scripts.banc_llm_gemini`.

## Documentation

- [docs/outils_role3.md](docs/outils_role3.md) : les 8 outils métier (contrat, enchaînements, avertissements, limites)
- [docs/jeu_test_metier.md](docs/jeu_test_metier.md) : jeu de test métier et temps de réponse
- [docs/statuts_lots.md](docs/statuts_lots.md) : correspondance des codes de statut des lots (confirmée)
- [docs/qualite_donnees.md](docs/qualite_donnees.md) : constats sur les données AFI
