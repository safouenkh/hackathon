-- =====================================================================
-- Migration 0004 : pages des organismes (APIA, APII, TIA, FIPA) découpées en passages,
--                  et règles d'orientation vers l'organisme compétent.   (schéma `assistant`)
--
-- À RELIRE PAR L'ÉQUIPE AVANT EXÉCUTION.
-- Application : .venv\Scripts\python.exe -m scripts.migrer --appliquer
--
-- Principes :
-- - Toujours aucune table ni clé étrangère vers le schéma `afi`.
-- - Une règle d'orientation n'existe qu'avec la phrase exacte de sa source : la base refuse une
--   citation absente du texte de la version citée (comparaison sans tenir compte des espaces).
-- - Les règles ne tranchent pas un cas que la source ne tranche pas : l'outil rend toutes les règles
--   qui s'appliquent, avec leurs citations.
-- - L'espace admin passe en 0005.
-- =====================================================================

-- ---------------------------------------------------------------------
-- 1. Passages : nouvelle partie « contenu » (page web ou PDF d'un organisme)
-- ---------------------------------------------------------------------

ALTER TABLE assistant.document_chunks DROP CONSTRAINT document_chunks_partie_check;
ALTER TABLE assistant.document_chunks ADD CONSTRAINT document_chunks_partie_check
    CHECK (partie IN ('reglement', 'rapport_presentation', 'en_tete', 'annexe', 'contenu'));

-- ---------------------------------------------------------------------
-- 2. Règles d'orientation
-- ---------------------------------------------------------------------
-- Une règle dit : « un projet qui remplit ces critères relève de cet organisme ».
--   secteur            : code d'un secteur de l'ontologie (afi:Secteur) ; null = tous les secteurs ;
--   secteur_exclu      : « les autres secteurs » = tous sauf celui-ci ;
--   investissement_*   : bornes du coût du projet en dinars (min inclus, max exclu) ; null = sans borne ;
--   investisseur_etranger : true = règle propre aux investisseurs étrangers ; null = tous.

CREATE TABLE assistant.regles_orientation (
    id                     bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    organisation           text NOT NULL CHECK (organisation ~ '^[A-Z]{2,10}$'),
    role                   text NOT NULL CHECK (role IN ('octroi_avantages', 'premier_contact', 'accompagnement')),
    secteur                text CHECK (secteur ~ '^[a-z][a-z0-9_]*$'),
    secteur_exclu          text CHECK (secteur_exclu ~ '^[a-z][a-z0-9_]*$'),
    investissement_min_dt  numeric CHECK (investissement_min_dt >= 0),
    investissement_max_dt  numeric CHECK (investissement_max_dt > 0),
    investisseur_etranger  boolean,
    citation               text NOT NULL CHECK (length(citation) BETWEEN 20 AND 1000),
    version_id             bigint NOT NULL REFERENCES assistant.document_versions (id),
    actif                  boolean NOT NULL DEFAULT true,
    ajoute_par             text NOT NULL,
    ajoute_le              timestamptz NOT NULL DEFAULT now(),
    CHECK (secteur IS NULL OR secteur_exclu IS NULL),
    CHECK (investissement_min_dt IS NULL OR investissement_max_dt IS NULL
           OR investissement_min_dt < investissement_max_dt),
    UNIQUE (organisation, role, secteur, secteur_exclu, investissement_min_dt, investissement_max_dt,
            investisseur_etranger)
);

-- La citation doit figurer dans le texte de la version citée (espaces normalisés).
CREATE FUNCTION assistant.controler_citation_regle() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    v_texte text;
BEGIN
    SELECT dv.full_text INTO v_texte FROM assistant.document_versions dv WHERE dv.id = NEW.version_id;
    IF v_texte IS NULL OR position(regexp_replace(NEW.citation, '\s+', ' ', 'g')
                                   IN regexp_replace(v_texte, '\s+', ' ', 'g')) = 0 THEN
        RAISE EXCEPTION 'citation absente du texte de la version % : « % »', NEW.version_id, left(NEW.citation, 80);
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER regles_orientation_citation_controlee
    BEFORE INSERT OR UPDATE ON assistant.regles_orientation
    FOR EACH ROW EXECUTE FUNCTION assistant.controler_citation_regle();

-- ---------------------------------------------------------------------
-- 3. Droits
-- ---------------------------------------------------------------------

GRANT SELECT ON assistant.regles_orientation TO assistant_lecture;
REVOKE ALL ON FUNCTION assistant.controler_citation_regle() FROM PUBLIC;
