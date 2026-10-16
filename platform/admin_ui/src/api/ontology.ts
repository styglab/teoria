import { getJson, postJson } from "./http_client";
import type { ValidationReport } from "./registry";

export type OntologyConcept = {
  concept_id: string;
  concept_kind: "object" | "property" | "relationship" | "rule" | "metric";
  stable_key: string;
  ontology_version: string;
  version_status: string;
};

export type OntologyVersion = {
  ontology_version_id: string;
  version: string;
  status: "draft" | "in_review" | "approved" | "published" | "deprecated";
  based_on_version_id?: string | null;
  created_at: string;
};

export type OntologySummary = {
  namespace: string;
  name: string;
  description: string;
  version_count: number;
  latest_version: string | null;
  latest_status: OntologyVersion["status"] | null;
};

export type OntologyVersionDetail = OntologyVersion & {
  namespace: string;
  ontology_name: string;
  objects: Array<{
    business_object_id: string;
    concept_id: string;
    stable_key: string;
    code: string;
    name: string;
    description: string;
    identity_policy: { properties?: string[] };
    properties: Array<{
      concept_id: string;
      stable_key: string;
      code: string;
      name: string;
      description: string;
      value_type: string;
      cardinality: string;
      unit: string | null;
      temporal: boolean;
    }>;
  }>;
  relationships: Array<{
    concept_id: string;
    stable_key: string;
    code: string;
    name: string;
    source_object_id: string;
    target_object_id: string;
    source_cardinality: string;
    target_cardinality: string;
    temporal: boolean;
  }>;
  rules: Array<{
    concept_id: string;
    stable_key: string;
    code: string;
    name: string;
    description: string;
    evaluator_key: string | null;
  }>;
  metrics: unknown[];
};

export type OntologyDiff = {
  added: string[];
  removed: string[];
  changed: string[];
};

export type OntologyBindingImpact = {
  compatible: boolean;
  incompatible_binding_count: number;
  incompatible_bindings: Array<{
    binding_id: string;
    stable_key: string;
    status: string;
  }>;
};

export const ontologyApi = {
  ontologyConcepts: (namespace = "procurement") =>
    getJson<{ items: OntologyConcept[] }>(
      `/ontology-authoring/ontologies/${encodeURIComponent(namespace)}/concepts`,
    ),
  ontologyVersions: (namespace: string) =>
    getJson<{ items: OntologyVersion[] }>(
      `/ontology-authoring/ontologies/${encodeURIComponent(namespace)}/versions`,
    ),
  authoredOntologies: () =>
    getJson<{ items: OntologySummary[] }>("/ontology-authoring/ontologies"),
  ontologyVersion: (id: string) =>
    getJson<OntologyVersionDetail>(
      `/ontology-authoring/versions/${encodeURIComponent(id)}`,
    ),
  ontologyVersionValidation: (id: string) =>
    getJson<ValidationReport & { binding_impact: OntologyBindingImpact }>(
      `/ontology-authoring/versions/${encodeURIComponent(id)}/validation`,
    ),
  ontologyVersionBindingImpact: (id: string) =>
    getJson<OntologyBindingImpact>(
      `/ontology-authoring/versions/${encodeURIComponent(id)}/binding-impact`,
    ),
  ontologyVersionDiff: (id: string, against: string) =>
    getJson<OntologyDiff>(
      `/ontology-authoring/versions/${encodeURIComponent(id)}/diff?against=${encodeURIComponent(against)}`,
    ),
  createOntologyDraft: (namespace: string, version: string) =>
    postJson<OntologyVersion>(
      `/ontology-authoring/ontologies/${encodeURIComponent(namespace)}/versions`,
      { version },
    ),
  transitionOntology: (
    id: string,
    action: "submit" | "request_changes" | "approve" | "revoke",
  ) =>
    postJson<OntologyVersion>(
      `/ontology-authoring/versions/${encodeURIComponent(id)}/transitions`,
      { action },
    ),
  publishOntology: (id: string) =>
    postJson<OntologyVersion>(
      `/ontology-authoring/versions/${encodeURIComponent(id)}/publish`,
      {},
    ),
};
