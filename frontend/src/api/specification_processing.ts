import { getJson } from "./http_client";
export type ProcessingRun = {
  run_id: string;
  mode: string;
  status: string;
  classification_code: string | null;
  summary: Record<string, unknown>;
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
};
export const processingApi = {
  status: () =>
    getJson<{ uploads_enabled: boolean; results_enabled: boolean }>(
      "/specification-processing/status",
    ),
  runs: (page = 0, size = 25) =>
    getJson<{ items: ProcessingRun[]; total: number }>(
      `/specification-processing/runs?offset=${page * size}&limit=${size}`,
    ),
  detail: (id: string) =>
    getJson<ProcessingDetail>(
      `/specification-processing/runs/${encodeURIComponent(id)}`,
    ),
  artifact: (id: string, key: string) =>
    getJson<Record<string, unknown>>(
      `/specification-processing/runs/${encodeURIComponent(id)}/artifact?${new URLSearchParams({ key })}`,
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
    if (!response.ok)
      throw new Error(
        response.status === 413
          ? "파일은 40MB 이하로 선택하세요."
          : `문서를 등록하지 못했습니다 (${response.status}). 파일 형식과 연결 상태를 확인하세요.`,
      );
    return response.json();
  },
};
