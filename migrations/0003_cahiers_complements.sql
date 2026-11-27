-- =====================================================================
-- Migration 0003 : cahiers des charges des zones découpés en passages (chunks),
--                  et compléments de zone venus d'une autre source.   (schéma `assistant`)
--
-- À RELIRE PAR L'ÉQUIPE AVANT EXÉCUTION.
-- Application : .venv\Scripts\python.exe -m scripts.migrer --appliquer
--
-- Principes :
-- - Toujours aucune table ni clé étrangère vers le schéma `afi` (les tables AFI ne changent pas).
-- - Le texte exact de chaque passage est gardé ici (AFI_Pipeline_Architecture.md §6-§7) :
--   Qdrant et le graphe RDF utilisent les mêmes identifiants (UUID du passage).
-- - Un complément ne remplace jamais une valeur AFI : il ne sert que si la base AFI est vide
--   (null ou 0), et il garde la version du document d'où il vient.
-- - L'espace admin (prévu en 0003 par la migration 0002) passe en 0004.
-- =====================================================================

-- ---------------------------------------------------------------------
-- 1. Passages des documents (cahiers des charges, puis autres sources)
-- ---------------------------------------------------------------------

CREATE TABLE assistant.document_chunks (
    id                     uuid PRIMARY KEY,                    -- UUID v5 calculé (version + cle) : stable
    version_id             bigint NOT NULL REFERENCES assistant.document_versions (id),
    cle                    text NOT NULL CHECK (length(cle) BETWEEN 1 AND 100),  -- ex. « 930208-a055-p1 »
    ordinal                integer NOT NULL CHECK (ordinal >= 0),  -- ordre dans le document
    text                   text NOT NULL CHECK (length(text) BETWEEN 1 AND 8000),
    page_from              integer CHECK (page_from > 0),       -- null : pages inconnues
    page_to                integer,
    article                text,                                -- numéro d'article ; null pour un passage non numéroté
    section                text[] NOT NULL DEFAULT '{}',        -- chemin des titres (chapitre > section)
    heading                text,
    partie                 text NOT NULL
                           CHECK (partie IN ('reglement', 'rapport_presentation', 'en_tete', 'annexe')),
    -- Code d'usage du sol défini par CE document (ex. « UIB ») ; null = inconnu ou tout le document.
    categorie_sol          text,
    a_verifier             boolean NOT NULL,                    -- indice automatique ; false ne veut pas dire vérifié
    raisons_verification   text[] NOT NULL DEFAULT '{}',
    UNIQUE (version_id, cle),
    UNIQUE (version_id, ordinal),
    CHECK ((page_from IS NULL) = (page_to IS NULL)),
    CHECK (page_to >= page_from)
);
CREATE INDEX document_chunks_version ON assistant.document_chunks (version_id, ordinal);

-- ---------------------------------------------------------------------
-- 2. Compléments de zone (valeur absente de la base AFI, trouvée dans une autre source)
-- ---------------------------------------------------------------------
-- `champ` désigne la colonne AFI complétée ; la valeur est dans la MÊME unité que cette colonne :
--   prixunitaire : afi.zones.prixunitaire ;
--   com_N        : afi.zone_commodites.zc_distance pour com_id = N (1 aéroport, 2 port, 3 gare,
--                  4 autoroute, 5 GP, 6 électricité, 7 eau potable).

CREATE TABLE assistant.zone_complements (
    code_zone              integer NOT NULL,                    -- afi.zones.code_zone, sans clé étrangère
    champ                  text NOT NULL
                           CHECK (champ IN ('prixunitaire', 'com_1', 'com_2', 'com_3', 'com_4',
                                            'com_5', 'com_6', 'com_7')),
    valeur                 numeric NOT NULL CHECK (valeur > 0),
    version_id             bigint NOT NULL REFERENCES assistant.document_versions (id),  -- d'où vient la valeur
    cle_source             text NOT NULL,                       -- champ lu dans la source, ex. « ZONE_PRIX »
    ajoute_le              timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (code_zone, champ)
);

-- ---------------------------------------------------------------------
-- 3. Droits
-- ---------------------------------------------------------------------

GRANT SELECT ON assistant.document_chunks, assistant.zone_complements TO assistant_lecture;
