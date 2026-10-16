import { getJson, postJson } from "./http_client";
import type { SemanticBinding } from "./binding";
import type { MetadataTableDetail } from "./metadata";

export type IntelligenceSuggestion = {
  suggestion_id: string;
  target_type: string;
  target_ref: string;
  suggestion_type: string;
  proposed_value: {
    description?: string;
    column_name?: string;
    ontology_stable_key?: string;
    alternatives?: Array<{ stable_key: string; score: number }>;
    [key: string]: unknown;
  };
  confidence: number;
  rationale: string | null;
  risk_level: "low" | "medium" | "high";
  model_provider: string;
  model_name: string;
  policy_version: string;
  submitted_by?: string;
  status:
    | "pending"
    | "approved"
    | "rejected"
    | "changes_requested"
    | "applied"
    | "failed";
  created_at: string;
  evidence: Array<{
    evidence_id: string;
    evidence_type: string;
    source_ref: string;
    excerpt: string | null;
    provenance: { score?: number; source_version?: string | null };
  }>;
  resulting_binding?: SemanticBinding;
  application?: {
    status: string;
    target_system: string;
    attempts: number;
    error_code: string | null;
    attempted_at: string | null;
    applied_at: string | null;
    lease_active: boolean;
    effect_started_at: string | null;
    effect_succeeded_at: string | null;
    external_change_ref: string | null;
  } | null;
  next_action?: "none" | "wait" | "retry" | "reconcile" | "reanalyze";
};

export type SuggestionPage = {
  items: IntelligenceSuggestion[];
  next_cursor: string | null;
};

export type ApplicationAttempt = {
  attempt_id: string;
  actor: string;
  target_system: string;
  started_at: string;
  finished_at: string | null;
  outcome: "applied" | "failed" | "superseded" | "reconciled" | null;
  error_code: string | null;
};

export type ApplicationAttemptPage = {
  items: ApplicationAttempt[];
  next_cursor: string | null;
};

export const suggestionApi = {
  intelligenceSuggestion: (id: string) =>
    getJson<IntelligenceSuggestion>(
      `/intelligence/suggestions/${encodeURIComponent(id)}`,
    ),
  suggestionTarget: (id: string) =>
    getJson<MetadataTableDetail>(
      `/intelligence/suggestions/${encodeURIComponent(id)}/target`,
    ),
  suggestionAttempts: (id: string, after?: string) =>
    getJson<ApplicationAttemptPage>(
      `/intelligence/suggestions/${encodeURIComponent(id)}/applications/attempts${after ? `?after=${encodeURIComponent(after)}` : ""}`,
    ),
  intelligenceSuggestions: (status?: string) =>
    getJson<{ items: IntelligenceSuggestion[] }>(
      `/intelligence/suggestions${status ? `?status=${encodeURIComponent(status)}` : ""}`,
    ),
  suggestionPage: (status?: string, after?: string, tableId?: string) => {
    const params = new URLSearchParams();
    if (status) params.set("status", status);
    if (after) params.set("after", after);
    if (tableId) params.set("table_id", tableId);
    return getJson<SuggestionPage>(
      `/intelligence/suggestions${params.size ? `?${params}` : ""}`,
    );
  },
  retrySuggestionApplication: (id: string) =>
    postJson<IntelligenceSuggestion>(
      `/intelligence/suggestions/${encodeURIComponent(id)}/applications/retry`,
      {},
    ),
  reconcileSuggestionApplication: (id: string) =>
    postJson<IntelligenceSuggestion>(
      `/intelligence/suggestions/${encodeURIComponent(id)}/applications/reconcile`,
      {},
    ),
  reviewSuggestion: (id: string, decision: "approve" | "reject") =>
    postJson<IntelligenceSuggestion>(
      `/intelligence/suggestions/${encodeURIComponent(id)}/reviews`,
      { decision },
    ),
  suggestDescriptionChange: (
    tableId: string,
    description: string,
    columnName?: string,
  ) =>
    postJson<IntelligenceSuggestion>("/intelligence/description-suggestions", {
      table_id: tableId,
      description,
      ...(columnName ? { column_name: columnName } : {}),
    }),
  suggestColumnBinding: (tableId: string, columnName: string) =>
    postJson<IntelligenceSuggestion>("/intelligence/binding-suggestions", {
      table_id: tableId,
      column_name: columnName,
    }),
};
