import { getJson } from "./http_client";

export const authApi = {
  session: () => getJson<{ actor: string; roles: string[] }>("/auth/session"),
};
