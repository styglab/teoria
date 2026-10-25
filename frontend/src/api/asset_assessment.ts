import { getJson, postJson } from "./http_client";
import type { MetadataTableDetail } from "./metadata";

export type AssessmentScope =
  "metadata_enrichment" | "semantic_alignment" | "disclosure_assessment";

export type DisclosureContext = "public_release" | "restricted_sharing";

export type AssessmentRequest = {
  table_fqn: string;
  scopes: AssessmentScope[];
  column_names?: string[];
  disclosure_context?: DisclosureContext;
  assessment_date?: string;
};

export type AssessmentFinding = {
  summary: string;
  scope?: AssessmentScope | null;
  column_name?: string | null;
  code?: string | null;
  evidence_ids?: string[];
  information_type?: string | null;
  internal_processing?:
    "review_required" | "basis_identified" | "not_assessed" | null;
  disclosure_recommendation?:
    | "review_required"
    | "withhold_raw"
    | "transform_and_reassess"
    | "candidate"
    | null;
  protection_recommendation?: string | null;
  tag_candidates?: string[];
  legal_applicability_confirmed?: boolean | null;
  tag_candidates_verified?: boolean | null;
  invalid_evidence_count?: number | null;
  unknown_column?: boolean | null;
  unknown_scope?: boolean | null;
  evidence?: Array<{
    evidence_type: string;
    source_ref: string;
    content_hash?: string | null;
    excerpt?: string | null;
    observed_at?: string | null;
    provenance?: Record<string, unknown>;
  }>;
};

export type AssetAssessment = {
  assessment_id: string;
  target_ref: MetadataTableDetail["reference"];
  status: "queued" | "running" | "completed" | "partial" | "failed";
  scopes: AssessmentScope[];
  column_names: string[];
  assessment_date: string;
  disclosure_context: DisclosureContext;
  requested_by: string;
  model_name: string;
  policy_version: string;
  attempts: number;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  lease_until: string | null;
  error_code: string | null;
  suggestion_ids: string[];
  findings: AssessmentFinding[];
};

export type AssessmentPage = { items: AssetAssessment[] };

export const assetAssessmentApi = {
  createAssetAssessment: (request: AssessmentRequest) =>
    postJson<AssetAssessment>("/intelligence/asset-assessments", request),
  assetAssessments: (tableId: string) =>
    getJson<AssessmentPage>(
      `/intelligence/asset-assessments?table_id=${encodeURIComponent(tableId)}`,
    ),
  assetAssessment: (id: string) =>
    getJson<AssetAssessment>(
      `/intelligence/asset-assessments/${encodeURIComponent(id)}`,
    ),
};
