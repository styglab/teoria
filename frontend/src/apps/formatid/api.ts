import { expireSession, getJson } from "../../api/http_client";
export type ProcessingStageOutcome = {
  status:
    | "completed"
    | "partial"
    | "failed"
    | "excluded"
    | "not_requested"
    | "not_applicable"
    | "review_required"
    | "resolved";
  counts: Record<string, number>;
};
export type ProcessingStages = {
  schema_version: 1;
  extraction: ProcessingStageOutcome;
  expression_registration: ProcessingStageOutcome;
  meaning: ProcessingStageOutcome;
  application: ProcessingStageOutcome & {
    basis: "pinned_profile" | "fixed_extraction_rules" | "extraction_draft";
  };
};
export type ProcessingRun = {
  run_id: string;
  mode: string;
  status: string;
  classification_code: string | null;
  summary: Record<string, unknown> & { processing_stages?: ProcessingStages };
  started_at: string;
  finished_at: string | null;
  error_code: string | null;
};
export type ProcessingDetail = {
  run: ProcessingRun;
  documents: Array<{
    document_id: string;
    status: string;
    source_sha256: string;
    result_summary: Record<string, unknown>;
  }>;
  artifacts: Array<{
    key: string;
    uri: string;
    sha256: string;
    size_bytes: number;
    media_type: string;
  }>;
};
export type InputDocument = {
  document_id: string;
  filename: string;
  source_uri: string;
  sha256: string;
  notice_number?: string | null;
};
export type RuntimeRequirementsResult = {
  objects: Array<{
    properties: { view_version: string; total: number; deferred_count: number };
    semantic_observations?: Array<{
      observation_id: string;
      concept_id: string;
      operator: string;
      scope: string;
      information_kind: string;
      value: { decimal?: string; text?: string; unit?: string };
      value_raw: unknown;
      unit_raw: string | null;
      source: { attribute_id: string; evidence?: { node_id?: string } };
    }>;
  }>;
  outcome?: {
    concepts: Record<string, string>;
    subjects?: Record<string, string>;
    compositions?: Array<{
      composition_id: string;
      parent_ref: string;
      child_ref: string;
      inclusion_role: "required" | "optional" | "excluded";
      quantity: { value: string; unit_raw: string; operator: string; scope: string };
      evidence: Array<{ quote: string }>;
    }>;
  };
};
export const processingApi = {
  runtimeRequirements: (
    runId: string,
    documentId: string,
    offset: number,
    signal?: AbortSignal,
  ) =>
    getJson<RuntimeRequirementsResult>(
      `/specification-processing/runtime-requirements?${new URLSearchParams({ run_id: runId, document_id: documentId, offset: String(offset) })}`,
      signal,
    ),
  reproduceValidation: (
    run: string,
    document: string,
    attribute: string,
    signal?: AbortSignal,
  ) =>
    getJson<{ verdict: string; code: string | null; model_called: boolean }>(
      `/specification-processing/runs/${encodeURIComponent(run)}/validation/${encodeURIComponent(document)}/${encodeURIComponent(attribute)}`,
      signal,
    ),
  operations: (signal?: AbortSignal) =>
    getJson<{
      days: number;
      runs: Record<string, number>;
      documents: Record<string, number>;
      quality_evaluation: string;
      quality_versions?: Array<{
        processor_revision: string | null;
        model_requested: string | null;
        runs: number;
        measured_runs: number;
        approved: number;
        held: number;
        validation_errors: number;
        accepted_attributes: number;
        quarantined_attributes: number;
        applied_attributes: number;
        held_attributes: number;
      }>;
    }>("/specification-processing/operations", signal),
  status: (signal?: AbortSignal) =>
    getJson<{ uploads_enabled: boolean; results_enabled: boolean }>(
      "/specification-processing/status",
      signal,
    ),
  runs: (page = 0, size = 25, signal?: AbortSignal) =>
    getJson<{ items: ProcessingRun[]; total: number }>(
      `/specification-processing/runs?offset=${page * size}&limit=${size}`,
      signal,
    ),
  detail: (id: string, signal?: AbortSignal) =>
    getJson<ProcessingDetail>(
      `/specification-processing/runs/${encodeURIComponent(id)}`,
      signal,
    ),
  inputs: (id: string, failedOnly = false, signal?: AbortSignal) =>
    getJson<{
      source_run_id: string;
      documents: InputDocument[];
      classification_code: string | null;
    }>(
      `/specification-processing/runs/${encodeURIComponent(id)}/inputs${failedOnly ? "?failed_only=true" : ""}`,
      signal,
    ),
  artifact: (id: string, key: string, signal?: AbortSignal) =>
    getJson<Record<string, unknown>>(
      `/specification-processing/runs/${encodeURIComponent(id)}/artifact?${new URLSearchParams({ key })}`,
      signal,
    ),
  upload: async (file: File): Promise<InputDocument> => {
    const token = sessionStorage.getItem("teoria-admin-token");
    const response = await fetch(
      `/admin-api/v1/admin/specification-processing/documents?${new URLSearchParams({ filename: file.name })}`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/octet-stream",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: file,
      },
    );
    if (!response.ok) {
      expireSession(response, token);
      throw new Error(
        response.status === 413
          ? "파일은 40MB 이하로 선택하세요."
          : `문서를 등록하지 못했습니다 (${response.status}). 파일 형식과 연결 상태를 확인하세요.`,
      );
    }
    return response.json();
  },
};

export type CatalogDocument = {
  catalog_id: string;
  filename: string;
  classification_code: string | null;
  notice_number: string | null;
  source_sha256: string | null;
  run_id: string;
  document_id: string;
  status: string;
  latest_status: string;
  latest_run_status: string;
  latest_run_id: string;
  latest_started_at: string;
  started_at: string;
  attempt_count: number;
  result_available: boolean;
  result_summary: Record<string, unknown>;
};
export type DocumentResult = {
  document: CatalogDocument;
  result: null | {
    extracted: Record<string, unknown>;
    normalization: Record<string, unknown> | null;
    result_kind: string;
    document_id: string;
  };
};
const catalogRoot = "/specification-processing/catalog";
export const documentCatalogApi = {
  classifications: (query = "", offset = 0, signal?: AbortSignal) =>
    getJson<{
      items: Array<{
        classification_code: string | null;
        documents: number;
        results: number;
      }>;
      total: number;
      documents: number;
    }>(
      `${catalogRoot}/classifications?${new URLSearchParams({ query, offset: String(offset) })}`,
      signal,
    ),
  documents: (params: URLSearchParams, signal?: AbortSignal) =>
    getJson<{ items: CatalogDocument[]; total: number }>(
      `${catalogRoot}/documents?${params}`,
      signal,
    ),
  result: (id: string, signal?: AbortSignal) =>
    getJson<DocumentResult>(
      `${catalogRoot}/documents/${encodeURIComponent(id)}/result`,
      signal,
    ),
  history: (id: string, page = 0, signal?: AbortSignal) =>
    getJson<{
      items: Array<{ run_id: string; status: string; started_at: string }>;
      total: number;
    }>(
      `${catalogRoot}/documents/${encodeURIComponent(id)}/history?offset=${page * 25}&limit=25`,
      signal,
    ),
};
