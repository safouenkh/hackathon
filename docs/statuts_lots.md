# Statuts des lots : ce que montrent les données

> **État : CONFIRMÉ le 26 novembre 2026.** Preuve principale : le code de la carte publique AFI. Les cas 0 et 5 ont été tranchés par Safouen. Implémentation : `backend/app/processing/statuts.py`, testée par `tests/test_statuts.py`.

## Correspondance retenue

| `LOT_ETAPE` | Carte publique (`onEachLot`, `switch(feature.properties.LOT_ETAPE)`) | Statut renvoyé par les outils | Avertissement |
|---|---|---|---|
| 1 | `// disponible`, vert, bouton « je m'intéresse » | `disponible` | `donnee_non_fraiche` |
| 4 | `// Mis aux enchères`, violet | `aux_encheres` | `donnee_non_fraiche` |
| 2 | `// réservé`, bleu, popup « Non disponible » | `non_disponible` | – |
| 3 | `// Attribué`, rouge, popup « Non disponible » | `non_disponible` | – |
| 0 | branche `default`, rouge, popup « Non disponible » | `non_disponible` (décision de Safouen) | – |
| 5 | `// Non disponible`, **gris** | `inconnu` = « gris, pas d'information » (décision de Safouen) | `statut_inconnu` |
| NULL ou autre | non prévu | `inconnu` (par prudence) | `statut_inconnu` |

**Source :** https://afi.e-industrie.gov.tn/, code JavaScript de la page d'accueil, lu le 26/11/2026. La carte charge les lots depuis `/data/lots.php`, qui fournit `LOT_ETAPE` et `LOT_LIB_ETAPE`.

**Fraîcheur :** le statut vient du dump du 13/11/2026. Le 26/11, 80 lots notés 1 ou 4 dans le dump ne figuraient plus dans `liste.php`. Un lot `disponible` ou `aux_encheres` porte donc toujours l'avertissement `donnee_non_fraiche` : sa disponibilité est à reconfirmer auprès de l'AFI.

---

Ce qui suit est l'analyse statistique du 26 novembre 2026 (rôle 3), qui a précédé la lecture du code de la carte et qui la corrobore.

## Sources comparées

| Source | Contenu | Date |
|---|---|---|
| `Chatbot Dalila/Dalila use case 1/afi.sql` | Dump MariaDB, table `lots` (6 579 lignes) | généré le 13 nov. 2026 |
| https://afi.e-industrie.gov.tn/liste.php | « Liste des lots disponibles » : gouvernorat, zone, n° de lot, superficie (m²), prix (Dt/m²) | lu le 26 nov. 2026 |

Aujourd'hui, le site affiche **720 lots dans 47 zones**. CLAUDE.md citait 787 lots dans 44 zones : la liste publique a donc changé depuis cette lecture.

## Méthode

1. Chargement du dump dans une base SQLite jetable. Les volumes obtenus sont identiques à ceux du rapport d'inspection : 185 zones, 6 579 lots, 1 501 commodités, 1 628 services, 106 documents, 85 connaissances, 150 sources.
2. Extraction des 720 lignes du tableau HTML.
3. Rattachement de chaque ligne du site à un lot du dump par (zone, `LOT_NUM`) :
   - 40 zones par nom identique (après normalisation des espaces, de la casse et des accents) ;
   - 7 zones dont le nom diffère, rattachées parce que **tous** leurs numéros de lot existent dans une seule zone du même gouvernorat (ou dans la zone au nom évident, quand plusieurs zones avaient le même score).

   | Nom sur le site | Zone du dump |
   |---|---|
   | KASSERINE 1 | 931301 KASSERINE |
   | KASSERINE 2 | 931300 KASSERINE Extention |
   | GAAFOUR | 931704 GAFOUR |
   | ENFIDHA 2 | 930607 ENNFIDHA II |
   | Zriba 4 | 931206 Zriba 4 1 Tranche |
   | Tejra Mednine | 931103 Tejra Mednibe Tranche 1 |
   | Beni khalled Sidi Ettoumi | 931208 Beni khalled Borj Ettoumi |

4. **Résultat du rattachement :** les 720 lots du site sont rattachés à un lot du dump. La superficie est identique pour 718 d'entre eux.
5. Pour chaque règle candidate, comptage sur les lots du dump appartenant à ces 47 zones :
   - **VP** : dans la règle et sur le site ;
   - **FP** : dans la règle mais absent du site ;
   - **FN** : sur le site mais hors de la règle.

## Résultats

Codes des 720 lots affichés « disponibles » sur le site :

| Code | Répartition |
|---|---|
| `LOT_ETAPE` | 1 → 605 ; 4 → 110 ; 2 → 3 ; 3 → 2 |
| `LOT_ETAT` | surtout 1, mais aussi 2, 3, 4 et 5 |
| `LOT_VALID` | 0, 1, 2, 3 et NULL : aucun lien visible |

| Règle candidate « disponible » | VP | FP | FN |
|---|---|---|---|
| `LOT_ETAT = 1` | 645 | 692 | 47 |
| `LOT_ETAPE = 1` | 577 | 59 | 115 |
| **`LOT_ETAPE IN (1, 4)`** | **715** | **80** | **5** |
| `LOT_ETAT = 1 AND LOT_ETAPE IN (1, 4)` | 643 | 64 | 49 |
| `LOT_ETAPE IN (1, 2, 4)` | 690 | 267 | 2 |

Les lignes autres que `LOT_ETAPE IN (1, 4)` portent sur les 45 premières zones. La ligne en gras inclut les 2 zones vérifiées à part (Tejra : 16 VP et 9 FP ; Beni Khalled : 12 VP et 7 FP).

Indicateurs par `LOT_ETAPE` sur tout le dump. Ce sont des agrégats calculés sur des champs qui ne sortent jamais des outils :

| `LOT_ETAPE` | Lots | Avec date de contrat | Avec acquéreur renseigné | `LOT_SUP_VENDU > 0` | Sur le site « disponibles » |
|---|---|---|---|---|---|
| 0 | 907 | 540 | 569 | 564 | 0 |
| 1 | 901 | 0 | 143 | 75 | 605 |
| 2 | 283 | 1 | 271 | 138 | 3 |
| 3 | 3 836 | 3 836 | 3 836 | 3 484 | 2 |
| 4 | 151 | 136 | 141 | 141 | 110 |
| 5 | 501 | 250 | 290 | 278 | 0 |

**Lecture :**
- La disponibilité publique suit **`LOT_ETAPE`**, et non `LOT_ETAT` comme on aurait pu le supposer.
- `LOT_ETAPE = 3` : tous ces lots ont un contrat et un acquéreur, et seuls 2 sont sur le site. C'est cohérent avec « non disponible (vendu) ».
- `LOT_ETAPE = 1` : aucun contrat, et 605 lots sur le site. C'est cohérent avec « disponible ».
- `LOT_ETAPE = 4` : 136 lots sur 151 ont déjà un contrat, et pourtant 110 sont affichés « disponibles ». Ce profil (lot déjà vendu une fois, puis remis sur le marché) **pourrait** correspondre à « mis aux enchères » ou à une reprise de lot, mais **rien ne le prouve** : à confirmer.
- `LOT_ETAPE = 2` : 271 lots sur 283 ont un acquéreur mais pas de contrat. Peut-être un lot attribué ou en cours de vente, sans preuve.
- `LOT_ETAPE` 0 et 5 : signification inconnue.
- Les 64 FP des 45 premières zones ont tous une surface positive. Pour l'ensemble des 80 FP, deux explications possibles, impossibles à départager avec nos données : des lots attribués entre le 13 et le 26 novembre, ou un critère supplémentaire inconnu.

## Questions (réglées le 26/11/2026)

Le code de la carte publique a répondu aux deux premières questions, et Safouen a tranché les codes 0 et 5 (voir le tableau en tête de fichier). Question encore ouverte : la cause des 80 FP. L'hypothèse la plus simple est un changement de statut après le 13/11, mais rien ne le vérifie.

## Gouvernorats (`zones.gouv_id`)

Correspondance lue sur le site (colonne « Gvt ») pour les zones rattachées par nom exact :

| gouv_id | Gouvernorat | gouv_id | Gouvernorat |
|---|---|---|---|
| 1 | Tunis | 13 | Kef |
| 2 | Ariana | 14 | Mahdia |
| 3 | Ben Arous | 16 | Monastir |
| 4 | La Manouba | 17 | Nabeul |
| 5 | Béja | 18 | Sidi Bouzid |
| 6 | Bizerte | 19 | Siliana |
| 7 | Gabès | 20 | Sfax |
| 9 | Jendouba | 21 | Sousse |
| 10 | Kairouan | 22 | Tataouine |
| 11 | Kasserine | 23 | Tozeur |
| 12 | Kébili | 24 | Zaghouan |

- **15 → Médenine** : déduit, car la zone 931103 (Tejra) a `gouv_id = 15` et le site la range sous « Mednine ». Rattachement par numéros de lot, pas par nom.
- **8 → inconnu** : aucune zone `gouv_id = 8` sur le site. Gafsa est le seul gouvernorat absent de la liste ci-dessus (Médenine compris), mais ce n'est pas une preuve.
- **Attention :** la zone 931704 GAFOUR a `gouv_id = 19` (Siliana), et le site la range bien sous Siliana.

## Prix

Le site affiche les prix en **Dt/m²**. Pour 41 des 47 zones, le prix du site est égal à `zones.prixunitaire`. Écarts constatés :

| Zone | Site (Dt/m²) | Dump `prixunitaire` |
|---|---|---|
| 9302051 BIR EL KASSAA 2 | 100 | 2022 (valeur aberrante) |
| 88888 Gabes I & II & III | 50 | 0 |
| 931804 El Kef Extension | 118 | 32 |
| 932119 Ras El Morj Monastir | 90 | 70 |
| 930606 BOUFICHA | 100 | 0 |
| 930602 SOUSSE II | 100 | 0 |

Conséquence : `prixunitaire` est toujours renvoyé comme **prix indicatif** du dump (avertissement `prix_indicatif`). Une valeur à 0 donne `prix = null` avec un avertissement, et la valeur 2022 est signalée comme suspecte.
