export type Overview = {
  counts: Record<"runtime_contract_domains" | "runtime_object_types" | "runtime_link_types" | "ontologies" | "object_types" | "link_types" | "sources" | "mappings" | "capabilities" | "data_types" | "value_sets", number>;
  validation: { status: "valid" | "invalid"; diagnostic_count: number };
};

export type RuntimeContractSummary = {
  id: string;
  name: string;
  description: string;
  object_count: number;
  link_count: number;
};

export type ObjectNode = {
  id: string;
  ontology: string;
  object_type: string;
  group?: string;
  name: string;
  description: string;
  primary_key: string | null;
  external: boolean;
  properties: Array<{ id: string; name: string; description: string; type: string; collection: "scalar" | "list" }>;
};

export type LinkEdge = {
  id: string;
  ontology: string;
  link_type: string;
  name: string;
  description: string;
  source: string;
  target: string;
};

export type RuntimeContractGraph = {
  runtime_contract: { id: string; name: string; description: string };
  nodes: ObjectNode[];
  edges: LinkEdge[];
};

export type ValidationDiagnostic = {
  code: string;
  message: string;
  path: string;
  severity: "error" | "warning";
  location: string | null;
};

export type ValidationReport = {
  status: "valid" | "invalid";
  diagnostic_count: number;
  diagnostics: ValidationDiagnostic[];
};

export type RegistryRelease = {
  version: string | null;
  git_commit: string | null;
  checksum: string | null;
  published_at: string | null;
  status: "draft" | "published" | "modified";
};

export type CapabilitySummary = { id: string; name: string; description: string; inputs: string[]; steps: string[]; returns: string[] };
export type SourceSummary = { id: string; name: string; description: string | null; type: "api" | "database"; provider: string | null; items: number; item_label: string };
export type MappingSummary = { id: string; name: string; description: string; ontology: string; binding_count: number; property_count: number };
export type LineageLink = { from: string; via: string; to: string; kind: "mapping" | "capability" };
export type MetadataStatus = { enabled: boolean; available: boolean; provider: "openmetadata"; base_url: string | null; database_service: string | null; reason: string | null };
export type MetadataEntity = {
  reference: { system: "openmetadata"; entity_id: string; entity_type: string; fully_qualified_name: string | null; version: number | null };
  name: string; display_name: string | null; description: string | null;
  owners: Array<Record<string, unknown>>; tags: Array<Record<string, unknown>>; domains: Array<Record<string, unknown>>;
};
export type MetadataPage = { items: MetadataEntity[]; total: number; after: string | null; before: string | null };
export type MetadataTableDetail = MetadataEntity & {
  database: Record<string, unknown> | null;
  database_schema: Record<string, unknown> | null;
  columns: Array<{ name: string; displayName?: string; description?: string; dataType?: string; fullyQualifiedName?: string; tags?: Array<Record<string, unknown>> }>;
  glossary_terms: Array<Record<string, unknown>>;
};
export type IntelligenceSuggestion = {
  suggestion_id: string;
  target_type: string;
  target_ref: string;
  suggestion_type: string;
  proposed_value: { description?: string; ontology_stable_key?: string; alternatives?: Array<{ stable_key: string; score: number }> };
  confidence: number;
  rationale: string | null;
  risk_level: "low" | "medium" | "high";
  model_provider: string;
  model_name: string;
  policy_version: string;
  status: "pending" | "approved" | "rejected" | "changes_requested" | "applied" | "failed";
  created_at: string;
  evidence: Array<{ evidence_id: string; evidence_type: string; source_ref: string; excerpt: string | null; provenance: { score?: number; source_version?: string | null } }>;
  resulting_binding?: SemanticBinding;
};
export type OntologyConcept = { concept_id: string; concept_kind: "object" | "property" | "relationship" | "rule" | "metric"; stable_key: string; ontology_version: string; version_status: string };
export type SemanticBinding = {
  binding_id: string; ontology_ref_type: OntologyConcept["concept_kind"];
  ontology_ref_id: string; ontology_concept_id: string; ontology_stable_key: string; ontology_concept_kind: OntologyConcept["concept_kind"];
  target_type: "glossary_term" | "data_asset"; target_locator: string;
  external_entity_id: string; entity_type: string; fully_qualified_name: string;
  binding_type: string; purpose: string | null; authority: "authoritative" | "preferred" | "supplemental";
  priority: number; confidence: number | null; status: "draft" | "approved" | "rejected" | "deprecated";
  created_by: string; approved_by: string | null; created_at: string; last_verified_at: string | null;
};
export type BindingValidation = { status: "valid" | "invalid"; binding_count: number; diagnostic_count: number; diagnostics: Array<{ binding_id: string; code: string }> };
export type OntologyVersion = { ontology_version_id: string; version: string; status: "draft" | "in_review" | "approved" | "published" | "deprecated"; based_on_version_id?: string | null; created_at: string };
export type OntologySummary = { namespace: string; name: string; description: string; version_count: number; latest_version: string | null; latest_status: OntologyVersion["status"] | null };
export type OntologyVersionDetail = OntologyVersion & { namespace: string; ontology_name: string; objects: Array<{ business_object_id: string; concept_id: string; stable_key: string; code: string; name: string; description: string; identity_policy: { properties?: string[] }; properties: Array<{ concept_id: string; stable_key: string; code: string; name: string; description: string; value_type: string; cardinality: string; unit: string | null; temporal: boolean }> }>; relationships: Array<{ concept_id: string; stable_key: string; code: string; name: string; source_object_id: string; target_object_id: string; source_cardinality: string; target_cardinality: string; temporal: boolean }>; rules: Array<{ concept_id: string; stable_key: string; code: string; name: string; description: string; evaluator_key: string | null }>; metrics: unknown[] };
export type OntologyDiff = { added: string[]; removed: string[]; changed: string[] };
export type OntologyBindingImpact = { compatible: boolean; incompatible_binding_count: number; incompatible_bindings: Array<{ binding_id: string; stable_key: string; status: string }> };
const API_ROOT = "/admin-api/v1/admin";

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_ROOT}${path}`);
  if (!response.ok) throw new Error(`Admin API 요청 실패 (${response.status})`);
  return response.json() as Promise<T>;
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const token = window.sessionStorage.getItem("teoria-admin-token");
  const response = await fetch(`${API_ROOT}${path}`, {
    method: "POST", headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) }, body: JSON.stringify(body),
  });
  if (!response.ok) throw new Error(`Admin API 요청 실패 (${response.status})`);
  return response.json() as Promise<T>;
}

export const adminApi = {
  overview: () => getJson<Overview>("/overview"),
  runtimeContracts: () => getJson<{ runtime_contracts: RuntimeContractSummary[] }>("/runtime-contracts"),
  runtimeContractGraph: (id: string) => getJson<RuntimeContractGraph>(`/runtime-contracts/${encodeURIComponent(id)}/graph`),
  capabilities: () => getJson<{ capabilities: CapabilitySummary[] }>("/capabilities"),
  sources: () => getJson<{ sources: SourceSummary[] }>("/sources"),
  mappings: () => getJson<{ mappings: MappingSummary[] }>("/mappings"),
  lineage: () => getJson<{ links: LineageLink[] }>("/lineage"),
  validation: () => getJson<ValidationReport>("/validation"),
  registryRelease: () => getJson<RegistryRelease>("/registry-release"),
  metadataStatus: () => getJson<MetadataStatus>("/metadata/status"),
  metadataTables: (databaseSchema?: string) => getJson<MetadataPage>(`/metadata/tables${databaseSchema ? `?database_schema=${encodeURIComponent(databaseSchema)}` : ""}`),
  metadataTable: (fqn: string) => getJson<MetadataTableDetail>(`/metadata/tables/${encodeURIComponent(fqn)}`),
  intelligenceSuggestions: (status?: string) => getJson<{ items: IntelligenceSuggestion[] }>(`/intelligence/suggestions${status ? `?status=${encodeURIComponent(status)}` : ""}`),
  reviewSuggestion: (id: string, decision: "approve" | "reject") => postJson<IntelligenceSuggestion>(`/intelligence/suggestions/${encodeURIComponent(id)}/reviews`, { decision, reviewer: "teoria-admin-ui" }),
  suggestColumnBinding: (tableId: string, columnName: string) => postJson<IntelligenceSuggestion>("/intelligence/binding-suggestions", { table_id: tableId, column_name: columnName }),
  ontologyConcepts: (namespace = "procurement") => getJson<{ items: OntologyConcept[] }>(`/ontology-authoring/ontologies/${encodeURIComponent(namespace)}/concepts`),
  bindings: (status?: string) => getJson<{ items: SemanticBinding[] }>(`/bindings${status ? `?status=${encodeURIComponent(status)}` : ""}`),
  bindingValidation: () => getJson<BindingValidation>("/bindings/validation"),
  createBinding: (body: Record<string, unknown>) => postJson<SemanticBinding>("/bindings", body),
  reviewBinding: (id: string, decision: "approve" | "reject" | "deprecate", comment?: string) => postJson<SemanticBinding>(`/bindings/${encodeURIComponent(id)}/reviews`, { decision, comment }),
  ontologyVersions: (namespace: string) => getJson<{ items: OntologyVersion[] }>(`/ontology-authoring/ontologies/${encodeURIComponent(namespace)}/versions`),
  authoredOntologies: () => getJson<{ items: OntologySummary[] }>("/ontology-authoring/ontologies"),
  ontologyVersion: (id: string) => getJson<OntologyVersionDetail>(`/ontology-authoring/versions/${encodeURIComponent(id)}`),
  ontologyVersionValidation: (id: string) => getJson<ValidationReport & { binding_impact: OntologyBindingImpact }>(`/ontology-authoring/versions/${encodeURIComponent(id)}/validation`),
  ontologyVersionBindingImpact: (id: string) => getJson<OntologyBindingImpact>(`/ontology-authoring/versions/${encodeURIComponent(id)}/binding-impact`),
  ontologyVersionDiff: (id: string, against: string) => getJson<OntologyDiff>(`/ontology-authoring/versions/${encodeURIComponent(id)}/diff?against=${encodeURIComponent(against)}`),
  createOntologyDraft: (namespace: string, version: string) => postJson<OntologyVersion>(`/ontology-authoring/ontologies/${encodeURIComponent(namespace)}/versions`, { version }),
  transitionOntology: (id: string, action: "submit" | "request_changes" | "approve" | "revoke") => postJson<OntologyVersion>(`/ontology-authoring/versions/${encodeURIComponent(id)}/transitions`, { action }),
  publishOntology: (id: string) => postJson<OntologyVersion>(`/ontology-authoring/versions/${encodeURIComponent(id)}/publish`, {}),
};
