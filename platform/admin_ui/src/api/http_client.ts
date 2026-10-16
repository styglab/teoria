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

async function responseError(response: Response): Promise<AdminApiError> {
  let message = `Admin API 요청 실패 (${response.status})`;
  let code: string | null = null;
  try {
    const payload = (await response.json()) as {
      detail?: string | { message?: string; code?: string };
    };
    const detail = payload.detail;
    if (typeof detail === "string") message = detail;
    else if (detail && typeof detail === "object") {
      if (typeof detail.code === "string") code = detail.code;
      if (typeof detail.message === "string") message = detail.message;
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
