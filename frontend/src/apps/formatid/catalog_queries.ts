import { AdminApiError, SESSION_EXPIRED_EVENT } from "../../api/http_client";
import { serverQueryClient, useServerQuery } from "../../api/server_queries";
import type { CatalogDocument } from "./api";

// A short, bounded cache belongs to document browsing. No artifact is persisted in browser storage.
let scope: string | null = null;
const views = new Map<
  string,
  { scroll: number; selection: CatalogDocument[] }
>();
export function readCatalogView(key: string) {
  principalScope();
  return views.get(key);
}
export function saveCatalogView(
  key: string,
  value: { scroll: number; selection: CatalogDocument[] },
) {
  if (scope !== sessionStorage.getItem("teoria-admin-token")) return;
  views.delete(key);
  views.set(key, value);
  while (views.size > 12) views.delete(views.keys().next().value!);
}
function principalScope() {
  const next = sessionStorage.getItem("teoria-admin-token");
  if (scope !== next) {
    serverQueryClient.removeQueries({
      predicate: (query) => query.queryKey[1] === "catalog",
    });
    views.clear();
    scope = next;
  }
  return next;
}
export function clearCatalogCache() {
  serverQueryClient.removeQueries({
    predicate: (query) => query.queryKey[1] === "catalog",
  });
  views.clear();
}
window.addEventListener(SESSION_EXPIRED_EVENT, clearCatalogCache);
export function catalogError(error: unknown): string {
  if (error instanceof AdminApiError) {
    if (error.status === 401)
      return "관리자 연결이 만료됐습니다. 다시 로그인한 뒤 조회하세요.";
    if (error.status === 403)
      return "이 결과를 조회할 권한이 없습니다. 관리자 연결의 권한을 확인하세요.";
    if (error.status === 413)
      return "결과가 화면 조회 한도를 초과했습니다. 실행 정보에서 산출물을 확인하세요.";
    if (error.code === "artifact_not_available" || error.status === 404)
      return "현재 저장소에서 결과를 찾을 수 없습니다. 실행 이력과 원래 산출물 저장소를 확인하세요.";
    if (error.status === 409)
      return "결과의 무결성 또는 문서 연결이 일치하지 않습니다. 실행 정보를 확인하세요.";
  }
  return "조회하지 못했습니다. 연결 상태를 확인하고 다시 시도하세요.";
}
export function useCatalogQuery<T>(
  key: string | null,
  load: (signal: AbortSignal) => Promise<T>,
  options: { keepPrevious?: boolean; refresh?: number } = {},
) {
  principalScope();
  const query = useServerQuery(key === null ? null : ["catalog", key], load, {
    ...options,
    staleTime: 30_000,
  });
  return { ...query, error: query.failure ? catalogError(query.failure) : "" };
}
