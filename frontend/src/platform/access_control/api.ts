import { getJson } from "../../api/http_client";

export const authApi = {
  session: (signal?: AbortSignal) =>
    getJson<{ actor: string; roles: string[] }>("/auth/session", signal),
};
