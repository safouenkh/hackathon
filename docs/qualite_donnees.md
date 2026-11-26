# Qualité des données AFI : constats (rôle 3)

Analyse du 26 novembre 2026 sur `afi.sql` (dump MariaDB généré le 13 nov. 2026). Tous les chiffres viennent de requêtes d'agrégats. Les champs interdits (`LOT_PROMOTEUR`, `LOT_CONTRAT_*`, `LOT_DOSSIER`…) n'ont servi qu'à des comptages.

## Noms réels des colonnes (MariaDB)

- **`lots`** : colonnes en MAJUSCULES (`LOT_ID`, `ZONE_ID`, `LOT_NUM`, `LOT_SUP_LOTIS`, `LOT_ETAT`, `LOT_ETAPE`…). La jointure se fait sur **`lots.ZONE_ID`** (varchar).
- **`zones`, `zone_*`, `chatbot_*`** : colonnes en minuscules.
- **À vérifier sur la base PostgreSQL migrée** : la casse a-t-elle été conservée (`"LOT_ID"`, entre guillemets) ou convertie en minuscules ?
- `LOT_ID` est unique (6 579 valeurs distinctes), tout comme le couple (`ZONE_ID`, `LOT_NUM`).
- **Clés :** contrairement à ce qu'indiquait le rapport d'inspection, le dump **déclare** des clés (`ALTER TABLE … ADD PRIMARY KEY / UNIQUE KEY`), par exemple `lots` : PK `LOT_ID` et UNIQUE (`ZONE_ID`, `LOT_NUM`). `scripts/import_afi_dump.py` les recrée à l'identique, sans erreur de doublon. Seule exception : **`zones` n'a aucune clé déclarée**, et `lots_kml` n'a qu'un UNIQUE (`ZONE_ID`, `LOT_NUM`).

## Lots

- **Lots orphelins** : 24 lots, répartis sur 4 `ZONE_ID` inexistants dans `zones` : `932107X` (21 lots), `300`, `930509` et `9310051` (1 lot chacun).
- **`LOT_SUP_LOTIS`** :
  - 30 valeurs négatives (minimum : −120 600) ;
  - 83 valeurs à 0 ;
  - maximum : 1 883 092.

  Une surface ≤ 0 donne `surface = null` avec un avertissement.
- **Unité des surfaces** : le site affiche « Superf. m² », et sa valeur est égale à `LOT_SUP_LOTIS` pour 718 des 720 lots publics. **L'unité de `LOT_SUP_LOTIS` est donc le m².**
- `LOT_NATURE` : 1 pour 6 247 lots, 14 autres codes plus rares. Signification inconnue.

## Zones

- **Zones visibles** : `zone_show = 1` pour 50 zones, ce qui correspond aux « 50 zones visibles » du cahier. Le site liste pourtant aussi 2 zones à `zone_show = 0` (930606 BOUFICHA, 931203 ZRIBA 2).
- **`prixunitaire`** :
  - 0 dans de nombreuses zones ;
  - 2022 pour 9302051 BIR EL KASSAA 2, alors que le site affiche 100 Dt/m².

  Le détail des écarts avec le site est dans [statuts_lots.md](statuts_lots.md).
- `zone_prix_prive` et `zone_prix_taux` sont **NULL dans les 185 zones**. Ces colonnes sont inutilisables.
- **Coordonnées** (`zone_lat`, `zone_long`, en texte) :
  - 36 zones ont une coordonnée vide ;
  - 147 zones sont dans un cadre plausible pour la Tunisie (lat 30–38, long 7–12) ;
  - aucune paire n'est inversée ;
  - 2 zones restantes sont hors de ce cadre (185 − 36 − 147) : à examiner.
- `zone_type` : 0 → 117, 1 → 13, 2 → 55. Signification inconnue.

## Compléments du 26/11/2026 (après lecture de la carte publique)

- **Types de commodités (`com_id`) :** le libellé officiel vient de `/data/zone-commodites.php` (carte publique) :

  | `com_id` | Libellé | `com_id` | Libellé |
  |---|---|---|---|
  | 1 | Aéroport | 7 | Eau potable |
  | 2 | Port | 8 | Gaz Naturel |
  | 3 | Gare Ferroviaire | 10 | Maintenance (GMG) |
  | 4 | Autoroute | 11 | Réseau téléphonique |
  | 5 | GP | 12 | OTC |
  | 6 | Electricité | | |

  Codé dans `backend/app/processing/reference.py`.
- **`zc_distance` est tronqué** : 42 lignes sur 660 en `km` ont une partie décimale perdue (3.00 pour « 3,5 km »). La carte publique affiche le texte `value`, que les outils utilisent aussi. Quand `value` contient plusieurs nombres (« 127 - 115 km », « 10 _ 1 km », « 15, 1 km »), la distance vaut `null` avec l'avertissement `distance_ambigue`.
- **Lignes de test** dans `zone_commodites` (« jjjj » d'unité `50`, « YTYTY » d'unité `767`) : écartées par contrôle de l'unité attendue (`donnee_incoherente`).
- **102 lignes de `zone_commodites`** ont `code_zone = 0` (aucune zone).
- **`gouv_id` 8** : seule zone, 932001 « GAFSA », donc Gafsa (déduit). **`gouv_id` 15** : Ben Gerdane, Zarzis et Tejra, donc Médenine (Tejra lue sous « Mednine » sur le site).
- **Coordonnées invalides** : 930904 Menzel Bourguiba 2 (latitude = longitude = 37.146805) et 932116 Sidi Salem (0 / 0). Avec les 36 vides, cela fait 38 zones sans coordonnées exploitables.
- **Documents de zone** : `zone_documents.fichier` est un chemin relatif (`carte/documents/...pdf`). Trois URL candidates testées sur `afi.e-industrie.gov.tn` répondent 404 : aucun lien public n'est connu (variable `AFI_DOCUMENTS_BASE_URL` prévue).
- **`zone_devreg`** : 0 → 119 zones, 1 → 66 zones. Le nom évoque « zone de développement régional », mais la signification n'est pas confirmée : la colonne n'est pas utilisée.

## Géographie, commodités, services

- **`zone_commodites`** : 11 `com_id`, environ 132 lignes chacun (180 pour `com_id = 12`, « OTC »). `zc_unite` mélange plusieurs types de valeurs :
  - distances : `km` (660 lignes) ;
  - capacités : `bar`, `Kva/Hec`, `m3/j/hec`, `paires` ;
  - états : `assainie`/`Assainie`, `actif`, `constitué`… ;
  - quelques valeurs numériques égarées (`767`, `50`).

  Seules les lignes en `km` donnent une distance. Libellés vus : Enfidha, Bizerte et Sousse (probablement des ports), A1 (autoroute), GP 1 (route), GMG, OTC. Plusieurs libellés sont vides : la correspondance `com_id` → type de commodité reste à établir.
- **`zone_services`** : 11 catégories, 148 lignes chacune, toutes de source `osm` :
  - santé : `clinique`, `hospital` ;
  - éducation : `ecole`, `college`, `lycee`, `faculte` ;
  - autres : `bank`, `poste`, `hotel`, `restaurant`, `parking`.

  Aucune catégorie port, gare ou aéroport : pour ces commodités, il faut passer par `zone_commodites`.
- **`lots_kml`** : 5 354 polygones, dont 4 204 rattachés à un lot par (`ZONE_ID`, `LOT_NUM`).
- **`zone_kml`** existe dans le dump (absente de la liste de CLAUDE.md), sans `INSERT` : elle est vide.

## Base de connaissances et sources

- **`chatbot_connaissances`** :
  - 85 fiches, toutes actives ;
  - `lang` : `toutes` (81), `fr` (3), `ar` (1) ;
  - les fiches 12 à 25 correspondent aux 8 services du cahier §IV.6 ;
  - la fiche 26 a pour question « Comment contacter l'Agence Foncière Industrielle (AFI) ? ». Elle est candidate pour BF24 (contenu de la réponse pas encore lu).
- **`chatbot_sources`** : 150 extraits (sicad 127, tia 9, fipa 5, apia 5, apii 4).
