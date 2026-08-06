export type Overview = {
  counts: Record<"ontologies" | "object_types" | "link_types" | "sources" | "mappings" | "capabilities" | "data_types" | "value_sets", number>;
  validation: { status: "valid" | "invalid"; diagnostic_count: number };
};

export type OntologySummary = {
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

export type OntologyGraph = {
  ontology: { id: string; name: string; description: string };
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

const API_ROOT = "/admin-api/v1/admin";

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_ROOT}${path}`);
  if (!response.ok) throw new Error(`Admin API 요청 실패 (${response.status})`);
  return response.json() as Promise<T>;
}

export const adminApi = {
  overview: () => getJson<Overview>("/overview"),
  ontologies: () => getJson<{ ontologies: OntologySummary[] }>("/ontologies"),
  ontologyGraph: (id: string) => getJson<OntologyGraph>(`/ontologies/${encodeURIComponent(id)}/graph`),
  capabilities: () => getJson<{ capabilities: CapabilitySummary[] }>("/capabilities"),
  sources: () => getJson<{ sources: SourceSummary[] }>("/sources"),
  mappings: () => getJson<{ mappings: MappingSummary[] }>("/mappings"),
  lineage: () => getJson<{ links: LineageLink[] }>("/lineage"),
  validation: () => getJson<ValidationReport>("/validation"),
  registryRelease: () => getJson<RegistryRelease>("/registry-release"),
};
