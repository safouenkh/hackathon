-- =====================================================================
-- Migration 0002 : structure complète des formulaires, demandes préparées par les
--                  investisseurs, contacts consentis, besoins non couverts (BF24),
--                  et rôle d'écriture.                     (schéma `assistant`)
--
-- À RELIRE PAR L'ÉQUIPE AVANT EXÉCUTION.
-- Application : .venv\Scripts\python.exe -m scripts.migrer --appliquer
--
-- Principes :
-- - Toujours aucune table ni clé étrangère vers le schéma `afi`.
-- - Les CIN, passeports et signatures (catégorie `non_enregistre`) ne peuvent pas être
--   enregistrés : un déclencheur refuse toute valeur dont le champ n'est pas de la bonne
--   catégorie, même si l'API avait un défaut.
-- - Le contact n'est enregistré qu'avec l'accord du client (texte de l'accord et date gardés).
-- - Le backend écrit avec un rôle séparé (`assistant_ecriture`) qui peut seulement AJOUTER
--   une demande, un contact ou un besoin : il ne peut ni les relire, ni les modifier.
-- - Les comptes admin et la lecture des demandes par l'AFI viendront avec l'espace admin
--   (migration 0003).
-- =====================================================================

-- ---------------------------------------------------------------------
-- 1. Formulaires : sections, origine des libellés, mentions imprimées, préremplissage
-- ---------------------------------------------------------------------

CREATE TABLE assistant.formulaire_sections (
    id                     bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    formulaire_id          bigint NOT NULL REFERENCES assistant.formulaires (id),
    code                   text NOT NULL CHECK (code ~ '^[a-z][a-z0-9_]*$'),
    ordre                  integer NOT NULL CHECK (ordre >= 0),
    UNIQUE (formulaire_id, code)
);

-- Origine d'un texte de formulaire :
--   pdf_texte         : recopié du texte du PDF officiel (contrôlé par les tests) ;
--   pdf_image         : recopié depuis l'image de la page (texte du PDF illisible) ;
--   traduction_equipe : traduction non officielle écrite par l'équipe.
CREATE TABLE assistant.formulaire_section_libelles (
    section_id             bigint NOT NULL REFERENCES assistant.formulaire_sections (id) ON DELETE CASCADE,
    langue                 text NOT NULL,
    libelle                text NOT NULL,
    source_texte           text NOT NULL CHECK (source_texte IN ('pdf_texte', 'pdf_image', 'traduction_equipe')),
    page                   integer CHECK (page > 0),
    PRIMARY KEY (section_id, langue),
    CHECK (source_texte = 'traduction_equipe' OR page IS NOT NULL)
);

-- Un champ appartient à une section connue de son formulaire.
ALTER TABLE assistant.formulaire_champs
    ADD FOREIGN KEY (formulaire_id, section) REFERENCES assistant.formulaire_sections (formulaire_id, code);

-- Données que l'outil peut mettre dans un champ, par ordre de préférence. Vocabulaire fermé :
-- chaque clé correspond à une donnée calculée par le backend (lot lu en base ou projet décrit
-- dans la conversation). Seuls les champs `projet` peuvent être préremplis.
ALTER TABLE assistant.formulaire_champs
    ADD COLUMN prerempli_depuis text[]
        CHECK (prerempli_depuis <@ ARRAY['lot.zone_nom', 'lot.numero', 'lot.surface_m2',
                                         'projet.activite', 'projet.nombre_emplois', 'projet.investissement_dt',
                                         'projet.surface_souhaitee_m2', 'projet.gouvernorat']::text[]),
    ADD CHECK (prerempli_depuis IS NULL OR categorie_donnee = 'projet');

-- Origine et page de chaque libellé. La table est vide à cette date : les colonnes peuvent être
-- obligatoires (si elle ne l'était pas, la migration échouerait au lieu d'inventer une origine).
ALTER TABLE assistant.formulaire_champ_libelles
    ADD COLUMN source_texte text NOT NULL CHECK (source_texte IN ('pdf_texte', 'pdf_image', 'traduction_equipe')),
    ADD COLUMN page integer CHECK (page > 0),
    ADD CHECK (source_texte = 'traduction_equipe' OR page IS NOT NULL),
    ADD CHECK (officiel = (source_texte <> 'traduction_equipe'));

-- Textes imprimés sur le formulaire officiel (notes, rappels, pièces obligatoires), par langue.
-- `si_champ` / `si_valeur` : la mention ne concerne qu'un choix (ex. pièces du document n° 3).
CREATE TABLE assistant.formulaire_mentions (
    id                     bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    formulaire_id          bigint NOT NULL REFERENCES assistant.formulaires (id),
    langue                 text NOT NULL,
    section                text NOT NULL,
    ordre                  integer NOT NULL CHECK (ordre >= 0),
    texte                  text NOT NULL,
    source_texte           text NOT NULL CHECK (source_texte IN ('pdf_texte', 'pdf_image')),
    page                   integer NOT NULL CHECK (page > 0),
    si_champ               text,
    si_valeur              text,
    FOREIGN KEY (formulaire_id, section) REFERENCES assistant.formulaire_sections (formulaire_id, code),
    FOREIGN KEY (formulaire_id, si_champ) REFERENCES assistant.formulaire_champs (formulaire_id, code),
    UNIQUE (formulaire_id, langue, section, ordre),
    CHECK ((si_champ IS NULL) = (si_valeur IS NULL))
);

-- ---------------------------------------------------------------------
-- 2. Demandes préparées par les investisseurs
-- ---------------------------------------------------------------------
-- Une ligne n'existe que si le client a cliqué « Envoyer à l'AFI » après sa relecture.
-- Ce n'est PAS le dépôt officiel : le client dépose encore le formulaire signé à l'AFI.

-- Permet de vérifier que la version citée par une demande est bien une version de son parcours.
ALTER TABLE assistant.parcours_versions ADD UNIQUE (id, parcours_id);

CREATE TABLE assistant.demandes (
    id                     bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    reference              text NOT NULL UNIQUE CHECK (reference ~ '^[A-Z0-9]{4}-[A-Z0-9]{4}$'),
    parcours_id            bigint NOT NULL REFERENCES assistant.parcours (id),
    parcours_version_id    bigint NOT NULL REFERENCES assistant.parcours_versions (id),  -- version lue par le client
    formulaire_id          bigint NOT NULL REFERENCES assistant.formulaires (id),
    langue                 text NOT NULL,                       -- variante du formulaire utilisée
    lot_ids                integer[] NOT NULL DEFAULT '{}'
                           CHECK (cardinality(lot_ids) <= 10),  -- identifiants afi.lots, sans clé étrangère
    valeurs                jsonb NOT NULL DEFAULT '{}'::jsonb   -- champs `projet` seulement
                           CHECK (jsonb_typeof(valeurs) = 'object'),
    statut                 text NOT NULL DEFAULT 'envoyee' CHECK (statut IN ('envoyee')),  -- suite : migration 0003
    envoyee_le             timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (parcours_version_id, parcours_id) REFERENCES assistant.parcours_versions (id, parcours_id),
    FOREIGN KEY (parcours_id, formulaire_id) REFERENCES assistant.parcours_formulaires (parcours_id, formulaire_id),
    FOREIGN KEY (formulaire_id, langue) REFERENCES assistant.formulaire_variantes (formulaire_id, langue)
);
CREATE INDEX demandes_envoyee_le ON assistant.demandes (envoyee_le DESC);

-- Contact du client : seulement avec son accord, dans une table à part (accès plus restreint).
CREATE TABLE assistant.demande_contacts (
    demande_id             bigint PRIMARY KEY REFERENCES assistant.demandes (id) ON DELETE CASCADE,
    valeurs                jsonb NOT NULL                       -- champs `contact` seulement
                           CHECK (jsonb_typeof(valeurs) = 'object' AND valeurs <> '{}'::jsonb),
    consentement_texte     text NOT NULL,                       -- texte exact accepté par le client
    consentement_le        timestamptz NOT NULL DEFAULT now()
);

-- Refuse toute clé qui n'est pas un champ de la bonne catégorie du formulaire de la demande,
-- et toute valeur qui n'est pas du texte court : aucun CIN, passeport ni signature ne passe.
-- SECURITY DEFINER : le rôle d'écriture ne peut pas relire les demandes ni les champs ; la
-- fonction s'exécute avec les droits de son propriétaire, chemin de recherche fixé.
CREATE FUNCTION assistant.controler_valeurs_demande() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    v_formulaire bigint;
    v_categorie  text;
    v_interdit   text;
BEGIN
    IF TG_TABLE_NAME = 'demandes' THEN
        v_formulaire := NEW.formulaire_id;
        v_categorie := 'projet';
    ELSE
        SELECT d.formulaire_id INTO v_formulaire FROM assistant.demandes d WHERE d.id = NEW.demande_id;
        v_categorie := 'contact';
    END IF;
    SELECT k INTO v_interdit
    FROM jsonb_each(NEW.valeurs) AS e(k, v)
    WHERE jsonb_typeof(v) <> 'string' OR length(v #>> '{}') > 2000
       OR NOT EXISTS (SELECT 1 FROM assistant.formulaire_champs c
                      WHERE c.formulaire_id = v_formulaire AND c.code = k AND c.categorie_donnee = v_categorie)
    LIMIT 1;
    IF v_interdit IS NOT NULL THEN
        RAISE EXCEPTION 'valeur refusée pour le champ « % » (catégorie attendue : %)', v_interdit, v_categorie;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER demandes_valeurs_controlees
    BEFORE INSERT OR UPDATE ON assistant.demandes
    FOR EACH ROW EXECUTE FUNCTION assistant.controler_valeurs_demande();
CREATE TRIGGER demande_contacts_valeurs_controlees
    BEFORE INSERT OR UPDATE ON assistant.demande_contacts
    FOR EACH ROW EXECUTE FUNCTION assistant.controler_valeurs_demande();

-- ---------------------------------------------------------------------
-- 3. Besoins non couverts (BF24) : question hors des services, pour l'analyse des besoins
-- ---------------------------------------------------------------------

CREATE TABLE assistant.besoins_non_couverts (
    id                     bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    question               text NOT NULL CHECK (length(question) BETWEEN 1 AND 500),
    langue                 text CHECK (length(langue) <= 20),
    note_le                timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX besoins_non_couverts_note_le ON assistant.besoins_non_couverts (note_le DESC);

-- ---------------------------------------------------------------------
-- 4. Droits
-- ---------------------------------------------------------------------

GRANT SELECT ON assistant.formulaire_sections, assistant.formulaire_section_libelles,
                assistant.formulaire_mentions
TO assistant_lecture;

-- Rôle de groupe sans connexion ; scripts/migrer.py y ajoute POSTGRES_RW_USER (.env).
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'assistant_ecriture') THEN
        CREATE ROLE assistant_ecriture NOLOGIN;
    END IF;
END;
$$;

GRANT USAGE ON SCHEMA assistant TO assistant_ecriture;
GRANT INSERT ON assistant.demandes, assistant.demande_contacts, assistant.besoins_non_couverts
TO assistant_ecriture;
-- RETURNING id, reference après l'ajout ; rien d'autre n'est lisible.
GRANT SELECT (id, reference) ON assistant.demandes TO assistant_ecriture;
REVOKE ALL ON FUNCTION assistant.controler_valeurs_demande() FROM PUBLIC;
