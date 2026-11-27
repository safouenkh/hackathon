# Simulation d'investisseurs et mesures langues/voix (27/11/2026)

Script : `python -m scripts.simuler_investisseurs` (banc Gemini + nos outils + service Dalila_Language).
Détail complet de chaque réponse et de chaque appel d'outil : `docs/simulation/simulation_*.json`.
Les profils sont fictifs : aucune donnée personnelle réelle.

## 1. Conversations simulées (24 profils, 27 questions)

Domaines couverts : recherche de lot (BF1, BF10), services de l'AFI (BF22-BF24), avantages et organismes
(BF14, BF20), règles des zones, question hors données (BF6), manipulation, données personnelles (BNF9),
préparation de demande (BF11). Langues : tunisien (arabizi et lettres arabes), arabe, algérien, libyen,
français, anglais, allemand, turc.

| Passage | Questions sans défaut | Temps médian | Temps max (BNF2 : 35 s) |
|---|---|---|---|
| 1 (avant correction) | 14 / 26 | 3,1 s | 24,7 s |
| 2 (avec la consigne de langue) | 26 / 27 | 3,4 s | 25,8 s |

**Défaut principal du passage 1 : langue de la réponse (BF3).** Le modèle répondait souvent en arabizi à une
question en français ou en lettres arabes, et en français à une question en anglais. Correction : à chaque
message, la langue (service Dalila_Language) et l'écriture (lettres arabes, arabizi) sont mesurées, et une
consigne courte est jointe au message (`app.langue.client.consigne_langue`). Un clic sur un bouton de
choix garde la langue de la conversation.

Le seul défaut restant du passage 2 venait de l'attente du scénario (S05) : après la démarche déjà donnée,
le modèle a préparé la demande directement, ce qui est correct ; l'attente a été élargie.

Corrigé après le passage 2 : la page du formulaire prérempli n'était pas citée, car son adresse était
relative (`FRONTEND_BASE_URL` vide) ; le modèle donnait le lien du site de l'AFI. Avec l'adresse complète,
le scénario S24 cite la page préremplie (3/3).

**Cohérence (BNF13)** : « lots disponibles à Gabès » dans les 8 langues donne exactement les mêmes lots
(8/8 au passage 2 ; au passage 1, le tunisien n'a pas eu de réponse : quota Gemini HTTP 429, puis 503).

Points à surveiller (lus dans les réponses, non comptés comme défauts) :
- S11 : pour « sardine », le modèle a ajouté « industrie » à la recherche, et l'APII (accompagnement)
  apparaît à côté de l'APIA.
- S24 : le modèle a rempli la surface souhaitée avec la surface du lot choisi.
- Jetons : environ 635 000 en entrée pour 35 questions ; le quota gratuit peut être atteint (429).

## 2. Langues et voix (service Dalila_Language 0.8.1, local, processeur)

**Détection de la langue** : 48 questions d'investisseurs étiquetées à la main, 6 par langue.

| | tn | ar | dz | ly | fr | en | de | tr | Total |
|---|---|---|---|---|---|---|---|---|---|
| Service seul | 3/6 | 2/6 | 5/6 | 6/6 | 6/6 | 6/6 | 5/6 | 6/6 | 39/48 |
| Avec la règle « lettres arabes => arabe » | 3/6 | 6/6 | 5/6 | 6/6 | 6/6 | 6/6 | 5/6 | 6/6 | 43/48 |

Erreurs restantes : l'arabizi mêlé de français est classé « fr » (l'écriture arabizi est détectée à part
pour la consigne de réponse) ; « بزاف غالية… » (algérien) classé arabe ; une phrase allemande courte classée « fr ».
Temps : médiane 173 ms.

**Aller-retour voix** (synthèse Piper puis reconnaissance Whisper de la même phrase ; ce n'est PAS une mesure
sur une vraie voix humaine) :

| Langue | Voix | Synthèse | Reconnaissance (modèles chargés) | Similarité du texte |
|---|---|---|---|---|
| tn | arabe générique (ar_JO) | 0,5 s | 2,9 s (Whisper tunisien) | 0,91 |
| ar | ar_JO | 0,5 s | 1,0 s | 0,96 |
| dz | arabe générique | 0,9 s | 1,1 s | 0,80 |
| ly | arabe générique | 0,4 s | 1,1 s | 0,86 |
| fr | fr_FR siwis | 0,7 s | 0,9 s | 0,96 |
| en | en_US lessac | 0,7 s | 0,9 s | 0,98 |
| de | de_DE thorsten | 0,7 s | 1,0 s | 0,95 |
| tr | tr_TR dfki | 0,7 s | 4,2 s | 0,92 |

- Premier appel : les modèles Whisper « small » (464 Mo) et « small tunisien » (239 Mo) se téléchargent ;
  la reconnaissance a alors pris 23 à 60 s. À préparer avant la démo.
- Les noms de lieux sont mal reconnus (« SVX », « S-Fax » pour Sfax) : risque pour BF7 (« la bonne zone »).
- Voix tunisienne : non activée (OmniVoice, licence CC-BY-NC, non commerciale) ; le tunisien, l'algérien
  et le libyen sont lus avec une voix arabe générique, ce que la réponse signale (BF8).
