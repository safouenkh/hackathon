# Couverture des sources : ce que Dalila utilise, ce qui reste à faire

Inventaire du 27/11/2026 (mis à jour le soir même après les corrections 1 à 5), fait par requêtes en lecture seule sur la base `dalila` et par recherche dans le code (`backend/app`). Il suit la règle « ne rien ignorer » : toute source est soit utilisée, soit écartée **avec sa raison**.

Légende : ✅ utilisé · 🟡 utilisé en partie · ❌ pas encore utilisé · ⛔ écarté volontairement (raison donnée).

## 1. Tables du dump AFI (`afi.*`)

| Table | Lignes | État | Détail |
|---|---|---|---|
| `zones` | 185 | 🟡 | Noms, gouvernorat, prix, coordonnées, visibilité : utilisés. Colonnes non utilisées : voir §2. |
| `lots` | 6 579 | 🟡 | Surface, statut (`lot_etape`), zone : utilisés. Champs interdits jamais lus en sortie. Colonnes non utilisées : voir §2. |
| `lots_kml` | 5 354 | 🟡 | Seule l'existence d'un polygone est vérifiée ; les polygones (4 204 rattachés à un lot) ne sont pas renvoyés au front (carte, rôle 5). |
| `zone_commodites` | 1 501 | ✅ | Distances et libellés utilisés ; `zc_libelle_arabe` ⛔ : ses 974 valeurs sont toutes identiques au libellé français, sans aucune lettre arabe (requête du 27/11). |
| `zone_services` | 1 628 | ✅ | Services de proximité (OSM). |
| `zone_documents` | 106 | ✅ | Cahiers des charges des zones (migration 0003, index Qdrant). |
| `chatbot_connaissances` | 85 | ✅ | 83 fiches cherchables (outil `connaissances_afi`) ; 3 et 12 écartées avec leur raison. Voir §3. |
| `chatbot_sources` | 150 | ✅ | 23 extraits des organismes (APIA, APII, TIA, FIPA) depuis le 27/11 ; **127 fiches SICAD depuis ce soir** (voir §4). |
| `chatbot_logs` | 214 | ⛔ | Conversations réelles du 18/09 au 12/11/2026 : données personnelles possibles, table illisible pour le compte du backend. Utilisable comme questions de test **seulement après anonymisation et accord de Safouen**. |
| `chatbot_besoins` | 38 | ⛔ | Besoins par conversation (20/10 au 12/11/2026), même raison. Le cahier (§IV.5) y cite `ChatbotBesoins::SECTEURS` comme point de départ des secteurs : liste à demander à l'AFI (code Laravel non fourni). |
| `chatbot_rapports` | 1 | ⛔ | Même raison. |
| `zone_indicateurs`, `zone_kml` | 0 | — | Vides dans le dump. |

Absent du dump, mais cité par le cahier : `chatbot_etudes` (6 lignes au 02/11), vues `carte_v_*`, table des 437 activités `par_activite_nat`, constantes `QualificationProjet`, `ConseilProjet::NATURES`. **À demander à l'AFI.**

## 2. Colonnes non utilisées

| Colonne | Remplie | Raison |
|---|---|---|
| `zones.zone_sup_total`, `zone_sup_amenager` | 144 et 158 zones | ❌ superficie de la zone, non exposée. Unité à confirmer (m² ou ha ?) avant usage. |
| `zones.datecreation` | 173 zones, 9 valeurs | ❌ signification à confirmer. |
| `zones.zone_type`, `niveau_id`, `dirreg_id` | 68 / 182 / 185 | ⛔ codes sans libellé connu (`docs/qualite_donnees.md`). |
| `zones.zone_devreg` | 185 | ⛔ « développement régional » non confirmé : `zone_developpement_regional = null`. |
| `zones.zone_assainie`, `annee_assainissement` | 1 / 0 zone | ⛔ quasi vides. |
| `zones.zone_prix_prive`, `zone_prix_taux` | 0 | ⛔ NULL partout. |
| `lots.lot_sup_piq` | 4 831 lots | ❌ seconde surface, sens à confirmer avec l'AFI. |
| `lots.lot_nbr`, `lot_nature` | 6 424 / 6 579 | ⛔ codes sans libellé connu. |
| `lots.lot_etat`, `lot_etat_init`, `lot_valid` | — | ⛔ remplacés par `lot_etape` (mapping confirmé, `docs/statuts_lots.md`). |
| `lots.lot_num_otc`, `lot_sup_otc` | 0 | — vides. |
| `lots.main_levee*`, `lot_contrat_*`, `lot_promoteur`, `lot_dossier`, `lot_inv_id`, `lot_projet` | — | ⛔ contractuel ou personnel : jamais en sortie. |

## 3. Fiches validées de l'AFI (`chatbot_connaissances`)

Le cahier (annexe, « II. Base de données ») les présente comme la « base de connaissances validée par l'AFI ». Avant le 27/11 au soir, 71 fiches sur 85 n'étaient lues par aucun outil. **Depuis : les 83 fiches actives non écartées sont des documents `fiche_afi` (107 passages Qdrant) et l'outil `connaissances_afi` rend le texte intégral relu dans la table.** Fiches écartées (ontologie, `afi:ficheEcartee`) : 12 (ancienne version des fiches 13 et 14) et 3 (contact aux numéros écrits à l'envers ; le contact vient de la fiche 26). Seuls contacts trouvés : institutionnels (AFI, directions régionales de l'APII).

Sujets désormais couverts :

| Fiches | Sujet | Utilité |
|---|---|---|
| 3 à 11, 39 à 41, 92 | Présentation, missions, chiffres clés de l'AFI, accès à l'information ; 92 = démarche d'acquisition en arabe | Questions générales sur l'AFI |
| 27, 28, 34 à 38 | Zones aménagées, en cours et programmées, par région | Questions sur les zones futures (pas dans `zones`) |
| 42, 51 à 56 | Déclaration de projet auprès de l'APII : pièces, en ligne, TRE, modification, fonds propres minimum, guichet unique, hydrocarbures | **Démarches de création de projet** (cas d’utilisation 6 « Décrire son projet ») |
| 43 à 50, 57 à 61 | Études du CEPI et de l'APII : régions, secteurs, stratégie 2035, monographies | Idées de projet, potentiel d'une région |
| 62 à 86 | Données industrielles des 24 gouvernorats | Guide par région |
| 87 à 90 | Documents de l'AFI, **obligations de l'acquéreur** (délais de construction…), **règles de construction** (COS, hauteur…), réseaux et normes de rejet | Compléments directs de `regles_zone` et `demarche` |
| 91 | Zone de Jendouba – El Irtiyeh | Zone absente des cahiers |

## 4. Fiches SICAD : fait le 27/11 au soir

- 127 extraits de `afi.chatbot_sources` (collectés le 23/10/2026), avec 67 fiches « Prestations » et 60 fiches « Cahiers des charges » d'activités. Ils sont importés en documents `fiche_sicad` (migration 0006, `assistant.demarches_externes`), soit 704 passages indexés dans Qdrant.
- La recherche de données personnelles n'a trouvé que des contacts institutionnels des ministères (e-mails `@ministeres.tn`, standards téléphoniques).
- Ontologie : famille « Démarche » (`afi:DemarcheAdministrative`, `afi:DomaineDemarche`, `afi:relevePar`). Elle compte 16 domaines SICAD, avec des synonymes en 5 langues (français, anglais, allemand, turc, arabe) et en arabizi. Le graphe est construit depuis la base (`graphe_demarches.py`), avec des requêtes SPARQL fixes.
- Outil `demarches_administratives`, et les fiches d'aides (FOPRODEX, FODEP, avantages fiscaux) ajoutées à `avantages`.
- Organismes sans nom sur la page (fiches 29, 109 : adresse et site seulement) : aucun nom n'est déduit.

## 5. Ontologie : les 9 familles du cahier (§IV.5)

Graphe complet : `backend/app/semantique/graphe_familles.py` (37 208 triplets, construit en ≈ 1 s), export Turtle pour Fuseki : `python -m scripts.exporter_graphe` (`ontology/genere/graphe_complet.ttl`, hors Git), qui lance aussi la requête SPARQL de test de chaque famille.

| Famille | Instances (27/11) | Limite |
|---|---|---|
| Lieu | 24 gouvernorats, 185 zones rattachées par `gouv_id` | Gafsa (8) déduit, signalé `gouvernoratDeduit` |
| Lot | 6 579 lots (identifiant et zone seulement) ; 24 orphelins sans zone | Prix, statut, surface restent en SQL |
| Secteur d'activité | 5 secteurs ; règles APIA agriculture, pêche, 1re transformation | 437 activités `par_activite_nat` absentes du dump |
| Commodité et proximité | 11 types `com_id` ; zones reliées quand une distance en km existe | Distances en SQL |
| Démarche | 127 démarches SICAD, 16 domaines, + 8 services AFI | — |
| Incitation | 15 pages ou fiches dont le titre annonce une aide, reliées à leur organisme | Le texte reste dans Qdrant/PostgreSQL |
| Organisme | AFI, APIA, APII, TIA, FIPA, INS (noms lus dans le guide APII) + 8 organismes SICAD | Rôle de l'INS : seulement « source des statistiques du commerce extérieur » (guide APII) |
| Projet | Schéma (nature, emplois, investissement, surface, lieu), jamais d'instance enregistrée | Listes `QualificationProjet`, `ConseilProjet::NATURES` non fournies |
| Service de l'AFI | 8 services | — |

Test : `tests/test_graphe_familles.py` (chaque famille répond à sa requête SPARQL).

## 6. Autres sources du projet

| Source | État |
|---|---|
| 23 cahiers des charges de zones (PDF) | ✅ importés et indexés |
| `sources-organismes/liens.json` (pages APIA, APII, FIPA) | ✅ ; les 5 pages TIA sont en échec (hébergeur suspendu), et seuls leurs extraits du dump servent |
| AFI, INS, ministères | ✅ organismes de l'ontologie (INS sans page lue, comme le demande le cahier) ; ministères : ceux que citent les fiches SICAD |
| DATA2 : 224 questions de test en 8 langues | ✅ `simuler_investisseurs --data2 <fichier>` (fichier lu sur place, non copié : dépôt sans licence) ; bilan dans `docs/simulation_data2.md`, résultats détaillés hors Git |
| `DALILA.pptx`, charte graphique, logo, mascotte | Rôle 5 (interface) |
| Vidéo de l'ancienne Dalila | ⛔ consigne : ne pas la lire |
| Use case 2 (marchés publics) | ⛔ hors priorité (CLAUDE.md) |
