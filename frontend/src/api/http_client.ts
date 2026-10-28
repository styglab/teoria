const API_ROOT = "/admin-api/v1/admin";

export class AdminApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code: string | null = null,
  ) {
    super(message);
    this.name = "AdminApiError";
  }
}

const requestMessages: Record<string, string> = {
  prefect_unavailable:
    "실행 관리 서비스에 연결하지 못했습니다. 잠시 후 다시 조회하세요.",
  mlflow_unavailable:
    "모델 저장소에 연결하지 못했습니다. 연결 상태를 확인하고 다시 조회하세요.",
  openmetadata_unavailable:
    "메타데이터 원천에 연결하지 못했습니다. 잠시 후 다시 조회하세요.",
  processing_results_unavailable:
    "규격서 처리 이력을 조회하지 못했습니다. 연결 상태를 확인하세요.",
  artifact_preview_requires_local_storage:
    "현재 화면은 파일 저장소의 산출물을 미리 볼 수 있습니다. 이 산출물은 외부 객체 저장소에서 확인하세요.",
  artifact_preview_too_large:
    "이 산출물은 미리보기 크기(5MB)를 초과합니다. 산출물 저장 참조에서 확인하세요.",
  artifact_checksum_mismatch:
    "저장된 산출물의 checksum이 일치하지 않습니다. 원본과 실행 이력을 확인하세요.",
};

async function responseError(response: Response): Promise<AdminApiError> {
  let message = `Admin API 요청 실패 (${response.status})`;
  let code: string | null = null;
  try {
    const payload = (await response.json()) as {
      detail?: string | { message?: string; code?: string };
    };
    const detail = payload.detail;
    if (typeof detail === "string") {
      code = requestMessages[detail] ? detail : null;
      message = requestMessages[detail] || detail;
    } else if (detail && typeof detail === "object") {
      if (typeof detail.code === "string") code = detail.code;
      if (typeof detail.message === "string") message = detail.message;
      else if (code && requestMessages[code]) message = requestMessages[code];
    }
  } catch {
    // Keep the status-based fallback for non-JSON gateway responses.
  }
  return new AdminApiError(message, response.status, code);
}

export async function getJson<T>(path: string): Promise<T> {
  const token = window.sessionStorage.getItem("teoria-admin-token");
  const response = await fetch(`${API_ROOT}${path}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    cache: "no-store",
  });
  if (!response.ok) throw await responseError(response);
  return response.json() as Promise<T>;
}

export async function postJson<T>(path: string, body: unknown): Promise<T> {
  const token = window.sessionStorage.getItem("teoria-admin-token");
  const response = await fetch(`${API_ROOT}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw await responseError(response);
  return response.json() as Promise<T>;
}

export async function patchJson<T>(path: string, body: unknown): Promise<T> {
  const token = window.sessionStorage.getItem("teoria-admin-token");
  const response = await fetch(`${API_ROOT}${path}`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw await responseError(response);
  return response.json() as Promise<T>;
}
