import { getJson, postJson } from "./http_client";
import type { OntologyConcept } from "./ontology";

export type SemanticBinding = {
  binding_id: string;
  ontology_ref_type: OntologyConcept["concept_kind"];
  ontology_ref_id: string;
  ontology_concept_id: string;
  ontology_stable_key: string;
  ontology_concept_kind: OntologyConcept["concept_kind"];
  target_type: "glossary_term" | "data_asset";
  target_locator: string;
  external_entity_id: string;
  entity_type: string;
  fully_qualified_name: string;
  binding_type: string;
  purpose: string | null;
  authority: "authoritative" | "preferred" | "supplemental";
  priority: number;
  confidence: number | null;
  status: "draft" | "approved" | "rejected" | "deprecated";
  created_by: string;
  approved_by: string | null;
  created_at: string;
  last_verified_at: string | null;
};

export type BindingValidation = {
  status: "valid" | "invalid";
  binding_count: number;
  diagnostic_count: number;
  diagnostics: Array<{ binding_id: string; code: string }>;
};

export const bindingApi = {
  bindings: (status?: string, ids?: string[]) => {
    const params = new URLSearchParams();
    if (status) params.set("status", status);
    ids?.forEach((id) => params.append("binding_id", id));
    return getJson<{ items: SemanticBinding[] }>(
      `/bindings${params.size ? `?${params}` : ""}`,
    );
  },
  bindingValidation: () => getJson<BindingValidation>("/bindings/validation"),
  createBinding: (body: Record<string, unknown>) =>
    postJson<SemanticBinding>("/bindings", body),
  reviewBinding: (
    id: string,
    decision: "approve" | "reject" | "deprecate",
    comment?: string,
  ) =>
    postJson<SemanticBinding>(`/bindings/${encodeURIComponent(id)}/reviews`, {
      decision,
      comment,
    }),
};
