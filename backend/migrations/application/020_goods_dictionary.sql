CREATE TABLE goods.dictionary_operations (
    operation_id text PRIMARY KEY,
    request_checksum text NOT NULL,
    actor text NOT NULL,
    result jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE goods.dictionary_entries (
    entry_id uuid PRIMARY KEY,
    kind text NOT NULL CHECK (kind IN ('item_type', 'characteristic')),
    stable_key text NOT NULL UNIQUE,
    preferred_name text NOT NULL,
    owner_entry_id uuid REFERENCES goods.dictionary_entries(entry_id),
    content jsonb NOT NULL,
    content_checksum text NOT NULL,
    status text NOT NULL CHECK (status = 'approved'),
    approved_by text NOT NULL,
    approval_mode text NOT NULL CHECK (approval_mode = 'automatic_policy'),
    policy_version text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK ((kind = 'item_type' AND owner_entry_id IS NULL) OR
           (kind = 'characteristic' AND owner_entry_id IS NOT NULL))
);

CREATE TABLE goods.dictionary_decisions (
    decision_id uuid PRIMARY KEY,
    operation_id text NOT NULL REFERENCES goods.dictionary_operations(operation_id),
    candidate_key text NOT NULL,
    status text NOT NULL CHECK (status IN ('proposed', 'approved', 'reused', 'held')),
    reason text NOT NULL,
    entry_id uuid REFERENCES goods.dictionary_entries(entry_id),
    candidate jsonb NOT NULL,
    evidence_digest text NOT NULL,
    actor text NOT NULL,
    policy_version text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(operation_id, candidate_key)
);

CREATE TABLE goods.dictionary_events (
    event_id uuid PRIMARY KEY,
    operation_id text NOT NULL REFERENCES goods.dictionary_operations(operation_id),
    candidate_key text NOT NULL,
    entry_id uuid REFERENCES goods.dictionary_entries(entry_id),
    action text NOT NULL CHECK (action IN ('proposed', 'approved', 'reused', 'held')),
    actor text NOT NULL,
    approval_mode text,
    policy_version text NOT NULL,
    reason text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX dictionary_entries_owner_idx ON goods.dictionary_entries(owner_entry_id);
CREATE INDEX dictionary_decisions_entry_idx ON goods.dictionary_decisions(entry_id);
