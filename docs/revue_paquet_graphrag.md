# Paquet GraphRAG : relecture avant import

Généré par `scripts.importer_cahiers --revue`. La base AFI reste la référence : un complément ne sert que si la valeur AFI est vide ; un écart n'est jamais appliqué.

## Cahiers des charges ↔ zones (table AFI `zone_documents`)

| Document | Zone AFI |
|---|---|
| 930207 | 930207 |
| 930208 | 930208 |
| 930209 | 930209 |
| 930301 | 930301 |
| 930302 | 930302 |
| 930506 | 930506 |
| 930902 | 930902 |
| 930918 | 930918 |
| 931208 | 931208 |
| 931301 | 931301 |
| 931402 | 931402 |
| 931803 | 931803 |
| 931804 | 931804 |
| 9318300 | 9318300 |
| 931897 | 931897 |
| 931900 | 931900 |
| 932107 | 932107 |
| 932108 | 932108 |
| 932112 | 932112 |
| 932114 | 932114 |
| 932117 | 932117 |
| 932119 | 932119 |
| 932128 | 932128 |

## Concordance JSON / base AFI (valeurs présentes des deux côtés)

| Champ | Égales | Comparées |
|---|---|---|
| aéroport (km) | 22 | 25 |
| port (km) | 25 | 25 |
| gare (km) | 18 | 25 |
| autoroute (km) | 19 | 25 |
| route GP (km) | 13 | 17 |
| électricité (Kva/Hec) | 25 | 25 |
| eau potable (m3/j/hec) | 24 | 24 |
| prix (Dt/m², colonne prixunitaire) | 41 | 44 |

## Compléments proposés (valeur AFI vide)

| Zone | Champ | Valeur du JSON |
|---|---|---|
| 930606 | prix (Dt/m², colonne prixunitaire) | 100 |
| 88888 | prix (Dt/m², colonne prixunitaire) | 50 |
| 931300 | aéroport (km) | 200 |
| 931300 | port (km) | 204 |
| 931300 | gare (km) | 3 |
| 931300 | autoroute (km) | 191 |
| 931300 | route GP (km) | 1 |
| 931300 | électricité (Kva/Hec) | 100 |
| 931300 | eau potable (m3/j/hec) | 40 |
| 930602 | prix (Dt/m², colonne prixunitaire) | 100 |
| 931100 | eau potable (m3/j/hec) | 40 |

## Écarts (non appliqués : la base AFI est gardée)

| Zone | Champ | Base AFI | JSON |
|---|---|---|---|
| 9302051 | prix (Dt/m², colonne prixunitaire) | 2022 | 100 |
| 931706 | gare (km) | 3 | 3.5 |
| 931706 | autoroute (km) | 40 | 38 |
| 930920 | aéroport (km) | 28 | 90 |
| 930920 | gare (km) | 2 | 22 |
| 931804 | prix (Dt/m², colonne prixunitaire) | 32 | 118 |
| 931803 | autoroute (km) | 40 | 70 |
| 931009 | aéroport (km) | 32 | 41 |
| 931009 | gare (km) | 4 | 4.5 |
| 931009 | autoroute (km) | 9 | 14 |
| 930607 | aéroport (km) | 3 | 68 |
| 930607 | route GP (km) | 0 | 1 |
| 931704 | gare (km) | 1 | 1.5 |
| 931704 | autoroute (km) | 50 | 64 |
| 931501 | gare (km) | 5 | 161 |
| 931500 | gare (km) | 15 | 149 |
| 931301 | route GP (km) | 5 | 1 |
| 931705 | autoroute (km) | 110 | 126 |
| 931705 | route GP (km) | 0 | 0.5 |
| 931011 | route GP (km) | 30 | 40 |
| 932119 | prix (Dt/m², colonne prixunitaire) | 70 | 90 |
| 9315043 | gare (km) | 65 | 188 |
| 932114 | autoroute (km) | 180 | 200 |
