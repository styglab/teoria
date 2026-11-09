import { getJson, postJson } from "./http_client";

export type DictionaryDefinition = {
  key: string;
  kind: "item_type" | "characteristic";
  preferred_name: string;
  definition: string;
  value_kind: string | null;
  applicable_item_type_ids: string[];
  quantity_dimension: string | null;
  canonical_unit: string | null;
  allowed_units: string[];
  references: string[];
};
export type DictionaryRecord = {
  ontology?: { version_id: string; namespace: string; version: string; checksum: string };
  target_concept_id?: string;
  historical?: boolean;
  requires_review?: boolean;
  revision_id?: string;
  concept_id?: string;
  concept_key?: string;
  revision?: number;
  mapping_id?: string;
  entry_id?: string;
  source_entry_id?: string;
  target_revision_id?: string;
  owner_concept_id?: string;
  preferred_name?: string;
  source_name?: string;
  display_name?: string;
  kind: "item_type" | "characteristic";
  status: "draft" | "approved" | "rejected" | "deprecated";
  content: DictionaryDefinition;
  classification_code?: string | null;
  scope_mode?: string;
  relation?: string;
  evidence?: Array<{
    document_id: string;
    quote: string;
    locator: string;
    source_sha256: string;
  }>;
  rationale?: string;
  created_by?: string;
  approved_by?: string;
  approval_mode?: string;
};
export type DictionaryEvent = {
  event_id: string;
  action: string;
  actor: string;
  rationale?: string;
  reason?: string;
  created_at: string;
};
export type StandardReference = { uri: string; sha256: string };
export type ApplicationStandard = {
  release_id: string;
  name: string;
  source_run_id: string;
  classification_code: string | null;
  standard_kind: "extraction_draft" | "ontology_profile";
  standard_ref: StandardReference;
  dictionary_ref: StandardReference;
  dictionary_checksum: string;
  status: "approved" | "deprecated";
  approved_by: string;
  rationale: string;
  created_at: string;
};
const root = "/goods/dictionary";
const standards = "/specification-processing/application-standards";
export const goodsDictionaryApi = {
  classifications: (query = "", page = 0, signal?: AbortSignal) =>
    getJson<{
      items: Array<{ classification_code: string; expression_count: number }>;
      total: number;
    }>(
      `${root}/classifications?${new URLSearchParams({ query, offset: String(page * 25), limit: "25" })}`,
      signal,
    ),
  catalog: (params: URLSearchParams, signal?: AbortSignal) => {
    const query = new URLSearchParams(params);
    if (!query.get("status")) query.delete("status");
    return getJson<{ items: DictionaryRecord[]; total: number }>(
      `${root}/catalog?${query}`,
      signal,
    );
  },
  importLegacy: (body: { ontology_draft_id: string; revision_ids: string[]; rationale: string }) =>
    postJson<{ status: string; items: Array<{ legacy_revision_id: string; status: string; reason?: string; stable_key?: string }> }>(
      `${root}/ontology-draft-imports`, body,
    ),
  decide: (kind: string, id: string, action: string, rationale: string) =>
    postJson<DictionaryRecord>(
      `${root}/${kind}/${encodeURIComponent(id)}/decisions`,
      { action, rationale },
    ),
  audit: (kind: string, id: string, signal?: AbortSignal) =>
    getJson<{ items: DictionaryEvent[] }>(
      kind === "source"
        ? `${root}/entries/${encodeURIComponent(id)}/audit`
        : `${root}/${kind}/${encodeURIComponent(id)}/audit`,
      signal,
    ),
  impact: (body: { concept_ids?: string[]; source_entry_ids?: string[] }) =>
    postJson<{
      documents: Array<{
        document_id: string;
        source_sha256: string;
        operation_id: string;
      }>;
    }>(`${root}/related-context`, body),
  evidence: (id: string, signal?: AbortSignal) =>
    getJson<{
      items: Array<{ document_id: string; quote: string; locator: string }>;
    }>(`${root}/entries/${encodeURIComponent(id)}/evidence`, signal),
  snapshot: () =>
    getJson<{ checksum: string; schema_version?: 1 | 2; concepts?: unknown[]; mappings: unknown[]; ontologies?: Array<{ ontology: { version_id: string; namespace: string; version: string; checksum: string } }> }>(
      `${root}/snapshot`,
    ),
  standards: (page = 0) =>
    getJson<{ items: ApplicationStandard[]; total: number }>(
      `${standards}?offset=${page * 25}&limit=25`,
    ),
  standard: (id: string) => getJson<ApplicationStandard>(`${standards}/${encodeURIComponent(id)}`),
  standardReadiness: (sourceRun: string) => getJson<{
    source_run_id: string; ready: boolean; reason: string | null;
    definition_count: number; rule_count: number; standard_kind: string;
  }>(`${standards}/sources/${encodeURIComponent(sourceRun)}`),
  standardSources: (page = 0) =>
    getJson<{
      items: Array<{
        run_id: string;
        classification_code: string | null;
        status: string;
      }>;
      total: number;
    }>(`${standards}/sources?offset=${page * 25}&limit=25`),
  approveStandard: (body: {
    name: string;
    source_run_id: string;
    expected_dictionary_checksum: string;
    rationale: string;
  }) => postJson<ApplicationStandard>(standards, body),
};
