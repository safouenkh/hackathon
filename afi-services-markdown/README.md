# Services AFI — textes français

Date de constitution du corpus : 2026-11-27.

Les neuf fichiers fr.md reprennent les textes transmis par l’utilisateur. Les intitulés des services et leur ordre correspondent aux neuf rubriques observées précédemment sur la page « Nos services ». Le texte corrigé de la main levée remplace le doublon initial.

La mise en forme Markdown et les niveaux de titres sont harmonisés ; les formulations, les répétitions et les numérotations atypiques sont conservées. Les entités HTML et les échappements de ponctuation sont rendus sous leur forme lisible. Aucun découpage artificiel en étapes n’est ajouté. Les pièces et frais restent à la position où ils figurent dans le texte, plutôt que d’être redistribués dans des champs déduits.

Les rubriques absentes portent null. « Pour qui / dans quels cas » reste null lorsqu’aucune rubrique autonome correspondante n’est fournie ; les indications de destinataires présentes dans le titre et le texte sont conservées à leur place. La date de collecte est celle de cette session ; ce n’est pas une date de publication.

## Fichiers par service

1. [La vente des lots industriels dans les zones de développement régional : Conditions de vente :](data/documents/services/acquisition-developpement-regional/fr.md)
2. [La vente des lots industriels dans les zones littorales et le grand Tunis Conditions de vente :](data/documents/services/acquisition-littoral-grand-tunis/fr.md)
3. [Attestation de situation foncière](data/documents/services/situation-fonciere/fr.md)
4. [Attestation d'insertion d'hypothèque](data/documents/services/insertion-hypotheque/fr.md)
5. [Acte de précision ou de contrats finaux](data/documents/services/acte-precision-contrats-finaux/fr.md)
6. [Autorisation de vente réservée aux institutions de leasing](data/documents/services/autorisation-vente-leasing/fr.md)
7. [Copie Conforme du Contrat de Vente, du Contrat Final ou Acte de Précision](data/documents/services/copie-conforme/fr.md)
8. [Attestation de main levée](data/documents/services/main-levee/fr.md)
9. [Vente aux enchères publiques :](data/documents/services/vente-encheres-publiques/fr.md)

## Parcours d’acquisition

Le critère de choix documenté dans les intitulés est la zone industrielle :

| Indication dans l’intitulé d’origine | Fichier |
| --- | --- |
| zones de développement régional | acquisition-developpement-regional/fr.md |
| zones littorales et le grand Tunis | acquisition-littoral-grand-tunis/fr.md |

Aucune liste de classement des zones n’est fournie. Le chatbot doit demander la zone et ne pas déduire son classement sans source. La vente aux enchères constitue une rubrique distincte ; les données ne précisent pas une règle générale permettant de choisir ce mode de vente.

## Pièces et versions manquantes

- Pages originales HTML/PDF : null. Les dossiers originaux/ contiennent uniquement un fichier de statut.
- Formulaires vierges téléchargés et liste de leurs champs : null. Les liens transmis sont conservés ; ils ne constituent pas les fichiers des formulaires.
- Versions arabes : null dans ce corpus. Aucun ar.md n’est créé en l’absence de texte arabe fourni. Cela ne signifie pas qu’une version arabe du site n’existe pas.

## Points à vérifier pour le chatbot

La situation foncière renvoie à la page de demande d’acquisition : ce lien est conservé tel qu’il a été transmis. Plusieurs autres services renvoient à une même page de formulaire en arabe. La pertinence et le contenu de ces formulaires n’ont pas été vérifiés dans cette étape.

Les textes de l’insertion d’hypothèque, de l’acte de précision et de la main levée contiennent des mentions d’autres actes ou procédures. Elles sont conservées sans correction ; leur cohérence administrative reste à vérifier auprès de l’AFI. Les numérotations répétées sont également conservées.

Pour guider le remplissage champ par champ, il reste nécessaire d’obtenir les formulaires vierges et d’en relever les libellés, les choix et les consignes exacts. Les données présentes ne permettent pas d’inventer ces champs ni leurs règles de validation. Aucun document personnel rempli n’est inclus.

## Vérifications effectuées

Neuf fichiers français sont générés, avec métadonnées, rubriques, liens fournis et contrôle d’intégrité SHA-256 dans manifest.json. La présence des sections, l’absence de marqueurs de remplacement et l’intégrité de l’archive sont contrôlées lors de la génération. Ces contrôles ne valident ni les procédures administratives ni les formulaires.

## Vérification sur le site (2026-11-27)

- Les neuf rubriques françaises ont été comparées mot par mot aux brouillons en base : texte identique (espaces, apostrophes, numéros en début de ligne, titres de rubrique et syntaxe des liens mis à part). La page indique une dernière modification le 2024-12-06.
- Les trois formulaires PDF du dossier `data/documents/formulaire/` ont la même empreinte SHA-256 que ceux en ligne.
- La page arabe et les formulaires diffèrent de la page française sur plusieurs points. La liste, les preuves et les citations sont dans `corrections.json`. La comparaison avec l'arabe est une lecture du sens, non automatisée : à confirmer par l'AFI.
- Les pages comparées sont enregistrées dans `data/documents/pages/`.
