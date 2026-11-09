import { getJson } from "../../../../api/http_client";

export type CapabilitySummary = {
  id: string;
  name: string;
  description: string;
  kind?: string;
  exposure?: string;
  processor?: string | null;
  effects?: Record<string, unknown>;
  inputs: string[];
  steps: string[];
  returns: string[];
};

export type CapabilityCoverageItem = {
  capability_id: string;
  status: "covered" | "partial" | "unbound";
  capability_bound: boolean;
  inputs: { total: number; bound: number; unbound_fields: string[] };
  outputs: { total: number; bound: number; unbound_fields: string[] };
};

export type CapabilityCoverage = {
  summary: {
    capability_count: number;
    capability_bound_count: number;
    input_count: number;
    bound_input_count: number;
    output_count: number;
    bound_output_count: number;
    capability_coverage_rate: number | null;
  };
  items: CapabilityCoverageItem[];
};

export const capabilityApi = {
  capabilities: (signal?: AbortSignal) =>
    getJson<{ capabilities: CapabilitySummary[] }>("/capabilities", signal),
  capabilityCoverage: (signal?: AbortSignal) =>
    getJson<CapabilityCoverage>("/bindings/capability-coverage", signal),
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
  properties: Array<{
    id: string;
    name: string;
    description: string;
    type: string;
    collection: "scalar" | "list";
  }>;
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

export type SourceSummary = {
  id: string;
  name: string;
  description: string | null;
  type: "api" | "database";
  provider: string | null;
  items: number;
  item_label: string;
};

export type MappingSummary = {
  id: string;
  name: string;
  description: string;
  ontology: string;
  binding_count: number;
  property_count: number;
};

export type LineageLink = {
  from: string;
  via: string;
  to: string;
  kind: "mapping" | "capability";
};

export const registryApi = {
  sources: (signal?: AbortSignal) =>
    getJson<{ sources: SourceSummary[] }>("/sources", signal),
  mappings: (signal?: AbortSignal) =>
    getJson<{ mappings: MappingSummary[] }>("/mappings", signal),
  lineage: (signal?: AbortSignal) =>
    getJson<{ links: LineageLink[] }>("/lineage", signal),
  validation: (signal?: AbortSignal) =>
    getJson<ValidationReport>("/validation", signal),
  registryRelease: (signal?: AbortSignal) =>
    getJson<RegistryRelease>("/registry-release", signal),
};
