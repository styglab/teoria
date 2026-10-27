-- Source registrations remain unchanged; definitions and mappings have separate authority.
CREATE TABLE goods.concept_revisions (
    revision_id uuid PRIMARY KEY,
    concept_id uuid NOT NULL,
    concept_key text NOT NULL,
    revision integer NOT NULL CHECK (revision > 0),
    kind text NOT NULL CHECK (kind IN ('item_type','characteristic')),
    content jsonb NOT NULL,
    content_checksum text NOT NULL,
    status text NOT NULL CHECK (status IN ('draft','approved','rejected','deprecated')),
    created_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(concept_key,revision),
    UNIQUE(concept_id,revision)
);
CREATE UNIQUE INDEX concept_current_approved ON goods.concept_revisions(concept_id) WHERE status='approved';
CREATE TABLE goods.concept_mappings (
    mapping_id uuid PRIMARY KEY,
    source_entry_id uuid NOT NULL REFERENCES goods.dictionary_entries(entry_id),
    target_revision_id uuid NOT NULL REFERENCES goods.concept_revisions(revision_id),
    classification_code text CHECK (classification_code IS NULL OR classification_code ~ '^[0-9]{10}$'),
    owner_concept_id uuid,
    relation text NOT NULL CHECK (relation IN ('equivalent','related')),
    rationale text NOT NULL,
    evidence jsonb NOT NULL,
    status text NOT NULL CHECK (status IN ('draft','approved','rejected','deprecated')),
    created_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX concept_mapping_lookup ON goods.concept_mappings(source_entry_id) WHERE status='approved';
CREATE TABLE goods.meaning_events (
    event_id uuid PRIMARY KEY,
    entity_kind text NOT NULL CHECK (entity_kind IN ('concept','mapping')),
    entity_id uuid NOT NULL,
    action text NOT NULL,
    actor text NOT NULL,
    rationale text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
