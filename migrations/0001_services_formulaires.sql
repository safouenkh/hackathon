-- =====================================================================
-- Migration 0001 : catalogue des services AFI, parcours guidés, formulaires,
--                  et traçabilité des sources.            (schéma `assistant`)
--
-- À RELIRE PAR L'ÉQUIPE AVANT EXÉCUTION.
-- Application : .venv\Scripts\python.exe -m scripts.migrer --appliquer
--
-- Principes :
-- - Aucune table du schéma `afi` n'est créée, modifiée ni référencée par clé étrangère
--   (scripts/import_afi_dump.py recrée `afi` avec DROP SCHEMA ... CASCADE).
-- - Aucune donnée métier ici : les tables sont vides ; l'import (étape 2) les remplit
--   depuis les fichiers sources, avec leur provenance.
-- - Le contenu d'un parcours est versionné : l'admin modifie un brouillon, puis le publie.
--   Une version publiée ou archivée ne change plus (une demande pourra s'y référer).
-- - Les demandes des investisseurs, les contacts et les comptes admin viendront dans
--   une migration séparée (0002), avec un rôle d'écriture distinct.
-- =====================================================================

CREATE SCHEMA IF NOT EXISTS assistant;

-- ---------------------------------------------------------------------
-- 1. Provenance (noms des tables et colonnes : AFI_Pipeline_Architecture.md §6)
-- ---------------------------------------------------------------------

CREATE TABLE assistant.sources (
    id                     bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    organisation           text NOT NULL,                     -- ex. « AFI »
    title                  text NOT NULL,                     -- ex. « Nos services »
    url                    text,                              -- null pour un fichier déposé sans URL
    ingestion_mode         text NOT NULL
                           CHECK (ingestion_mode IN ('manuel', 'automatique', 'lien_seul')),
    enabled                boolean NOT NULL DEFAULT true,
    last_status            text,
    last_error             text,
    last_checked_at        timestamptz,
    created_at             timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX sources_url_unique ON assistant.sources (url) WHERE url IS NOT NULL;

CREATE TABLE assistant.documents (
    id                     bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_id              bigint NOT NULL REFERENCES assistant.sources (id),
    cle                    text NOT NULL UNIQUE,              -- clé stable pour un import idempotent (ex. chemin relatif)
    title                  text NOT NULL,
    type                   text NOT NULL,                     -- ex. 'fiche_service', 'formulaire'
    zone_id                integer,                           -- code_zone AFI éventuel, sans clé étrangère
    language               text,                              -- 'fr', 'ar'… ; null si inconnue
    created_at             timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE assistant.document_versions (
    id                     bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    document_id            bigint NOT NULL REFERENCES assistant.documents (id),
    sha256                 text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    media_type             text NOT NULL,                     -- 'text/markdown', 'application/pdf'…
    original_path          text,                              -- chemin du fichier conservé (hors Git)
    full_text              text,                              -- texte intégral ; null tant qu'il n'est pas extrait
    content_provenance     text,                              -- ex. « Texte transmis par l'utilisateur »
    retrieved_at           date,                              -- date de collecte (pas une date de publication)
    publication_date       date,
    effective_date         date,
    validity_status        text NOT NULL DEFAULT 'a_verifier'
                           CHECK (validity_status IN ('a_verifier', 'valide', 'obsolete')),
    created_at             timestamptz NOT NULL DEFAULT now(),
    UNIQUE (document_id, sha256)
);

CREATE TABLE assistant.ingestion_runs (
    id                     bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_id              bigint REFERENCES assistant.sources (id),
    version_id             bigint REFERENCES assistant.document_versions (id),
    status                 text NOT NULL CHECK (status IN ('en_cours', 'reussi', 'echec')),
    error                  text,
    counts                 jsonb NOT NULL DEFAULT '{}'::jsonb,  -- ex. {"etapes": 5, "pieces": 4}
    started_at             timestamptz NOT NULL DEFAULT now(),
    finished_at            timestamptz,
    CHECK ((status = 'en_cours') = (finished_at IS NULL))
);

-- ---------------------------------------------------------------------
-- 2. Services et parcours
-- ---------------------------------------------------------------------

CREATE TABLE assistant.services (
    id                     bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code                   text NOT NULL UNIQUE CHECK (code ~ '^[a-z][a-z0-9_]*$'),  -- ex. 'copie_conforme'
    nom                    text NOT NULL,
    besoin                 text,                              -- besoin de l'investisseur, si une source le donne
    ordre                  integer NOT NULL,
    actif                  boolean NOT NULL DEFAULT true,
    created_at             timestamptz NOT NULL DEFAULT now()
);

-- Un service a un ou plusieurs parcours (ex. acquisition : développement régional / littoral et Grand Tunis).
CREATE TABLE assistant.parcours (
    id                     bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    service_id             bigint NOT NULL REFERENCES assistant.services (id),
    code                   text NOT NULL UNIQUE CHECK (code ~ '^[a-z][a-z0-9_-]*$'),
    titre                  text NOT NULL,                     -- intitulé d'origine
    critere_choix          text,                              -- ex. « zones de développement régional » ; null s'il n'y en a pas
    ordre                  integer NOT NULL,
    actif                  boolean NOT NULL DEFAULT true,
    created_at             timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE assistant.parcours_versions (
    id                     bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    parcours_id            bigint NOT NULL REFERENCES assistant.parcours (id),
    numero                 integer NOT NULL CHECK (numero > 0),
    statut                 text NOT NULL DEFAULT 'brouillon'
                           CHECK (statut IN ('brouillon', 'publie', 'archive')),
    origine                text NOT NULL CHECK (origine IN ('import', 'admin')),
    document_version_id    bigint REFERENCES assistant.document_versions (id),  -- source importée
    note                   text,
    cree_par               text NOT NULL,
    cree_le                timestamptz NOT NULL DEFAULT now(),
    publie_par             text,
    publie_le              timestamptz,
    UNIQUE (parcours_id, numero),
    CHECK (statut = 'brouillon' OR (publie_par IS NOT NULL AND publie_le IS NOT NULL)),
    CHECK (origine = 'admin' OR document_version_id IS NOT NULL)
);
-- Une seule version publiée par parcours (publier = archiver l'ancienne puis publier la nouvelle).
CREATE UNIQUE INDEX parcours_versions_une_publiee
    ON assistant.parcours_versions (parcours_id) WHERE statut = 'publie';

-- Contenu d'une version : description, conditions, étapes, pièces, frais, liens.
CREATE TABLE assistant.parcours_elements (
    id                     bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    version_id             bigint NOT NULL REFERENCES assistant.parcours_versions (id) ON DELETE CASCADE,
    parent_id              bigint,                            -- sous-élément (ex. critère d'une condition)
    type                   text NOT NULL CHECK (type IN
                           ('description', 'pour_qui', 'condition', 'etape', 'piece', 'frais', 'lien', 'remarque')),
    groupe                 text,                              -- ex. « I – Phase de réservation »
    ordre                  integer NOT NULL CHECK (ordre >= 0),
    titre                  text,                              -- ex. « Dépôt de la demande d'acquisition »
    texte                  text NOT NULL,                     -- texte affiché
    texte_source           text,                              -- texte d'origine ; null si ajouté par l'admin
    modifie_par_admin      boolean GENERATED ALWAYS AS (texte_source IS DISTINCT FROM texte) STORED,
    responsable            text,                              -- ex. « Demandeur de Services », « GMG »
    montant_dt             numeric(12, 3) CHECK (montant_dt IS NULL OR montant_dt >= 0),
    unite_montant          text,                              -- ex. « par copie »
    url                    text,
    a_verifier             boolean NOT NULL DEFAULT false,    -- ex. écart entre la fiche et le formulaire
    note_verification      text,
    UNIQUE (version_id, id),
    FOREIGN KEY (version_id, parent_id) REFERENCES assistant.parcours_elements (version_id, id) ON DELETE CASCADE,
    UNIQUE NULLS NOT DISTINCT (version_id, parent_id, type, groupe, ordre),
    CHECK (montant_dt IS NULL OR type = 'frais'),
    CHECK (unite_montant IS NULL OR montant_dt IS NOT NULL),
    CHECK (NOT a_verifier OR note_verification IS NOT NULL)
);
CREATE INDEX parcours_elements_version ON assistant.parcours_elements (version_id, type, ordre);

-- ---------------------------------------------------------------------
-- 3. Formulaires
-- ---------------------------------------------------------------------

CREATE TABLE assistant.formulaires (
    id                     bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code                   text NOT NULL UNIQUE CHECK (code ~ '^[a-z][a-z0-9_]*$'),  -- ex. 'demande_acquisition'
    titre                  text NOT NULL,
    actif                  boolean NOT NULL DEFAULT true,
    created_at             timestamptz NOT NULL DEFAULT now()
);

-- Version officielle d'un formulaire dans une langue (ex. demande d'acquisition FR et AR).
CREATE TABLE assistant.formulaire_variantes (
    id                     bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    formulaire_id          bigint NOT NULL REFERENCES assistant.formulaires (id),
    langue                 text NOT NULL,
    titre_officiel         text NOT NULL,
    document_version_id    bigint REFERENCES assistant.document_versions (id),   -- PDF vierge conservé
    url_page               text,
    url_fichier            text,
    UNIQUE (formulaire_id, langue)
);

-- Champs d'un formulaire. categorie_donnee décide de ce que Dalila peut faire du champ :
--   projet          : l'agent peut le demander dans le chat et le préremplir ;
--   contact         : saisi par le client sur la page, jamais dans le chat ni envoyé au LLM ;
--                     enregistré seulement avec son accord (migration 0002) ;
--   non_enregistre  : CIN, passeport, signature… : jamais demandé, jamais enregistré ;
--                     le client le complète sur son exemplaire ;
--   reserve_afi     : rempli par l'AFI (ex. accusé de dépôt, date et cachet).
CREATE TABLE assistant.formulaire_champs (
    id                     bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    formulaire_id          bigint NOT NULL REFERENCES assistant.formulaires (id),
    code                   text NOT NULL CHECK (code ~ '^[a-z][a-z0-9_]*$'),
    section                text,
    ordre                  integer NOT NULL CHECK (ordre >= 0),
    type                   text NOT NULL CHECK (type IN
                           ('texte', 'texte_long', 'nombre', 'montant', 'date', 'choix_unique', 'choix_multiple', 'case')),
    categorie_donnee       text NOT NULL CHECK (categorie_donnee IN ('projet', 'contact', 'non_enregistre', 'reserve_afi')),
    choix                  jsonb CHECK (choix IS NULL OR jsonb_typeof(choix) = 'array'),
    unite                  text,                              -- ex. 'm²', 'DT', 'KVA', 'm³/jour'
    obligatoire            boolean,                           -- null : le formulaire ne le précise pas
    UNIQUE (formulaire_id, code),
    CHECK ((type IN ('choix_unique', 'choix_multiple')) = (choix IS NOT NULL))
);

-- Libellés d'un champ par langue : officiel (texte du PDF) ou traduction non officielle.
CREATE TABLE assistant.formulaire_champ_libelles (
    champ_id               bigint NOT NULL REFERENCES assistant.formulaire_champs (id) ON DELETE CASCADE,
    langue                 text NOT NULL,
    libelle                text NOT NULL,
    officiel               boolean NOT NULL,
    aide                   text,
    PRIMARY KEY (champ_id, langue)
);

-- Formulaire utilisé par un parcours (modifiable par l'admin), et valeurs imposées
-- (ex. demande administrative : ligne 1 cochée pour la situation foncière).
CREATE TABLE assistant.parcours_formulaires (
    parcours_id            bigint NOT NULL REFERENCES assistant.parcours (id),
    formulaire_id          bigint NOT NULL REFERENCES assistant.formulaires (id),
    valeurs_imposees       jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(valeurs_imposees) = 'object'),
    a_verifier             boolean NOT NULL DEFAULT false,
    note_verification      text,
    PRIMARY KEY (parcours_id, formulaire_id),
    CHECK (NOT a_verifier OR note_verification IS NOT NULL)
);

-- ---------------------------------------------------------------------
-- 4. Une version publiée ou archivée ne change plus
-- ---------------------------------------------------------------------

CREATE FUNCTION assistant.proteger_version_figee() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_TABLE_NAME = 'parcours_versions' THEN
        IF TG_OP = 'DELETE' THEN
            IF OLD.statut <> 'brouillon' THEN
                RAISE EXCEPTION 'version % figée (%) : suppression interdite', OLD.id, OLD.statut;
            END IF;
            RETURN OLD;
        END IF;
        -- Seul passage autorisé après publication : publie -> archive, sans autre changement.
        IF OLD.statut = 'archive'
           OR (OLD.statut = 'publie' AND NOT (NEW.statut = 'archive'
               AND (NEW.parcours_id, NEW.numero, NEW.origine, NEW.document_version_id, NEW.note,
                    NEW.cree_par, NEW.cree_le, NEW.publie_par, NEW.publie_le)
                   IS NOT DISTINCT FROM
                   (OLD.parcours_id, OLD.numero, OLD.origine, OLD.document_version_id, OLD.note,
                    OLD.cree_par, OLD.cree_le, OLD.publie_par, OLD.publie_le))) THEN
            RAISE EXCEPTION 'version % figée (%) : modification interdite', OLD.id, OLD.statut;
        END IF;
        RETURN NEW;
    END IF;
    -- parcours_elements : seuls les éléments d'un brouillon changent.
    IF EXISTS (SELECT 1 FROM assistant.parcours_versions v
               WHERE v.id IN (OLD.version_id, CASE WHEN TG_OP = 'UPDATE' THEN NEW.version_id END)
                 AND v.statut <> 'brouillon') THEN
        RAISE EXCEPTION 'éléments d''une version figée : % interdit', TG_OP;
    END IF;
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END;
$$;

CREATE TRIGGER parcours_versions_figees
    BEFORE UPDATE OR DELETE ON assistant.parcours_versions
    FOR EACH ROW EXECUTE FUNCTION assistant.proteger_version_figee();

CREATE FUNCTION assistant.proteger_ajout_version_figee() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM assistant.parcours_versions v
               WHERE v.id = NEW.version_id AND v.statut <> 'brouillon') THEN
        RAISE EXCEPTION 'éléments d''une version figée : ajout interdit';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER parcours_elements_figes
    BEFORE UPDATE OR DELETE ON assistant.parcours_elements
    FOR EACH ROW EXECUTE FUNCTION assistant.proteger_version_figee();
CREATE TRIGGER parcours_elements_ajout_fige
    BEFORE INSERT ON assistant.parcours_elements
    FOR EACH ROW EXECUTE FUNCTION assistant.proteger_ajout_version_figee();

-- ---------------------------------------------------------------------
-- 5. Lecture pour le backend
-- ---------------------------------------------------------------------
-- Rôle de groupe sans connexion ; scripts/migrer.py y ajoute POSTGRES_RO_USER (.env).
-- Pas d'accès à ingestion_runs (messages d'erreur internes).

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'assistant_lecture') THEN
        CREATE ROLE assistant_lecture NOLOGIN;
    END IF;
END;
$$;

GRANT USAGE ON SCHEMA assistant TO assistant_lecture;
GRANT SELECT ON
    assistant.sources, assistant.documents, assistant.document_versions,
    assistant.services, assistant.parcours, assistant.parcours_versions, assistant.parcours_elements,
    assistant.formulaires, assistant.formulaire_variantes, assistant.formulaire_champs,
    assistant.formulaire_champ_libelles, assistant.parcours_formulaires
TO assistant_lecture;
