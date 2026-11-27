-- =====================================================================
-- Migration 0006 : démarches administratives hors AFI (fiches SICAD)        (schéma `assistant`)
--
-- Application : .venv\Scripts\python.exe -m scripts.migrer --appliquer
--
-- Principes :
-- - Toujours aucune table ni clé étrangère vers le schéma `afi`.
-- - Le texte d'une fiche est une version de document (assistant.document_versions, type
--   `fiche_sicad`), découpée en passages comme les pages des organismes ; cette table garde
--   seulement ce que la fiche dit d'elle-même (type, organismes, secteur, domaines, documents
--   joints), pour l'ontologie (famille « Démarche », cahier §IV.5) et les filtres de l'outil.
-- - Rien n'est déduit : un organisme absent de la fiche n'est pas ajouté.
-- - L'espace admin passe en 0007.
-- =====================================================================

CREATE TABLE assistant.demarches_externes (
    version_id        bigint PRIMARY KEY REFERENCES assistant.document_versions (id),
    origine           text NOT NULL CHECK (origine IN ('sicad')),
    id_source         bigint,                                 -- afi.chatbot_sources.id (sans clé étrangère)
    type_fiche        text NOT NULL CHECK (type_fiche IN ('prestation', 'cahier_des_charges')),
    titre             text NOT NULL CHECK (length(titre) BETWEEN 2 AND 500),
    organismes        text[] NOT NULL DEFAULT '{}',
    secteur           text,
    domaines          text[] NOT NULL DEFAULT '{}',
    documents_joints  text[] NOT NULL DEFAULT '{}'
);
CREATE INDEX demarches_externes_domaines ON assistant.demarches_externes USING gin (domaines);

GRANT SELECT ON assistant.demarches_externes TO assistant_lecture;
