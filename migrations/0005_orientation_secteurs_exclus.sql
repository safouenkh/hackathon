-- =====================================================================
-- Migration 0005 : une règle d'orientation peut exclure PLUSIEURS secteurs.   (schéma `assistant`)
--
-- À RELIRE PAR L'ÉQUIPE AVANT EXÉCUTION.
-- Application : .venv\Scripts\python.exe -m scripts.migrer --appliquer
--
-- Pourquoi : la TIA écrit « APII […] pour les projets dans les autres secteurs » et l'APIA couvre
-- « le secteur agricole, de la pêche, des services liés et de la première transformation ». La
-- règle APII doit donc exclure l'agriculture, la pêche et la première transformation, et non
-- seulement l'agriculture (décision de l'équipe du 2026-11-27 : pêche -> APIA seule, cahier BF20).
-- Les valeurs existantes sont reprises telles quelles (secteur_exclu -> [secteur_exclu]).
-- L'espace admin passe en 0006.
-- =====================================================================

ALTER TABLE assistant.regles_orientation ADD COLUMN secteurs_exclus text[]
    CHECK (secteurs_exclus IS NULL OR (cardinality(secteurs_exclus) > 0
           AND array_to_string(secteurs_exclus, ',') ~ '^[a-z][a-z0-9_]*(,[a-z][a-z0-9_]*)*$'));

UPDATE assistant.regles_orientation SET secteurs_exclus = ARRAY[secteur_exclu] WHERE secteur_exclu IS NOT NULL;

-- Supprime aussi la contrainte UNIQUE et le CHECK qui portaient sur l'ancienne colonne.
ALTER TABLE assistant.regles_orientation DROP COLUMN secteur_exclu;

ALTER TABLE assistant.regles_orientation
    ADD CONSTRAINT regles_orientation_secteur_ou_exclusions CHECK (secteur IS NULL OR secteurs_exclus IS NULL),
    ADD CONSTRAINT regles_orientation_criteres_uniques
        UNIQUE NULLS NOT DISTINCT (organisation, role, secteur, secteurs_exclus, investissement_min_dt,
                                   investissement_max_dt, investisseur_etranger);
