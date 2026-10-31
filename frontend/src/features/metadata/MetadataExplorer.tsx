import { useEffect, useState } from "react";
import {
  ChevronRight,
  Database,
  Folder,
  RefreshCw,
  Table2,
} from "lucide-react";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";
import {
  metadataApi,
  type MetadataEntity,
  type MetadataStatus,
} from "../../api/metadata";

import { CatalogPagination } from "../../components/workspace/CatalogPagination";
import {
  CatalogLayout,
  FilterTabs,
  PageHeader,
  SearchField,
} from "../../components/workspace/WorkspaceLayout";

import { AdminApiError } from "../../api/http_client";
import { useAdminAccess } from "../access/AdminAccess";
import type { CatalogCounts } from "../../api/metadata";

type Filter = "all" | "description" | "owner" | "tags";
const filters: Array<{ id: Filter; label: string }> = [
  { id: "all", label: "전체" },
  { id: "description", label: "설명 없음" },
  { id: "owner", label: "소유자 미지정" },
  { id: "tags", label: "태그·용어 없음" },
];
export function MetadataExplorer() {
  const { principal, requestLogin } = useAdminAccess();
  const navigate = useNavigate();
  const location = useLocation();
  const [params, setParams] = useSearchParams();
  const query = params.get("q") || "";
  const schema = params.get("schema") || "";
  const filter = filters.some((item) => item.id === params.get("filter"))
    ? (params.get("filter") as Filter)
    : "all";
  const sort = params.get("sort") === "desc" ? "desc" : "asc";
  const page = Math.min(
    params.get("size") === "50" ? 199 : 399,
    Math.max(0, Math.floor(Number(params.get("page")) || 0)),
  );
  const pageSize = params.get("size") === "50" ? 50 : 25;
  const [status, setStatus] = useState<MetadataStatus | null>(null);
  const [tables, setTables] = useState<MetadataEntity[]>([]);
  const [schemas, setSchemas] = useState<MetadataEntity[]>([]);
  const [total, setTotal] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [counts, setCounts] = useState<CatalogCounts | null>(null);
  const [countsError, setCountsError] = useState(false);
  const [unauthorized, setUnauthorized] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [schemaError, setSchemaError] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0);
  const update = (values: Record<string, string>) =>
    setParams(
      (previous) => {
        const next = new URLSearchParams(previous);
        if (!("page" in values)) next.delete("page");
        Object.entries(values).forEach(([key, value]) =>
          value ? next.set(key, value) : next.delete(key),
        );
        return next;
      },
      { replace: true },
    );
  useEffect(() => {
    let active = true;
    setError(null);
    setStatus(null);
    setUnauthorized(false);
    metadataApi
      .metadataStatus()
      .then((value) => {
        if (active) setStatus(value);
      })
      .catch((reason) => {
        if (active) {
          setUnauthorized(
            reason instanceof AdminApiError && reason.status === 401,
          );
          setError((reason as Error).message);
        }
      });
    return () => {
      active = false;
    };
  }, [refresh, principal?.actor]);
  useEffect(() => {
    if (!status?.available) return;
    let active = true;
    const load = async () => {
      const all: MetadataEntity[] = [];
      const visited = new Set<string>();
      let cursor: string | undefined;
      try {
        do {
          const result = await metadataApi.metadataSchemas(cursor);
          if (!active) return;
          all.push(...result.items);
          cursor = result.after || undefined;
          if (cursor) {
            if (visited.has(cursor))
              throw new Error("스키마 페이지가 반복됩니다.");
            visited.add(cursor);
          }
        } while (cursor);
        if (active) {
          setSchemas(all);
          setSchemaError(null);
        }
      } catch {
        if (active)
          setSchemaError(
            "스키마 목록을 조회하지 못했습니다. 전체 자산은 계속 확인할 수 있습니다.",
          );
      }
    };
    load();
    return () => {
      active = false;
    };
  }, [status?.available, refresh]);
  useEffect(() => {
    if (!status?.available) return;
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    setTables([]);
    setTotal(null);
    const timer = setTimeout(() => {
      metadataApi
        .searchTables(
          {
            databaseSchema: schema || undefined,
            query,
            missing: filter,
            sort,
            offset: page * pageSize,
            limit: pageSize,
          },
          controller.signal,
        )
        .then((result) => {
          if (controller.signal.aborted) return;
          setTables(result.items);
          setTotal(result.total);
          if (page > 0 && page * pageSize >= result.total) update({ page: "" });
        })
        .catch((reason) => {
          if (controller.signal.aborted) return;
          setUnauthorized(
            reason instanceof AdminApiError && reason.status === 401,
          );
          setError((reason as Error).message);
        })
        .finally(() => {
          if (!controller.signal.aborted) setLoading(false);
        });
    }, 250);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [
    schema,
    query,
    filter,
    sort,
    page,
    pageSize,
    status?.available,
    refresh,
    principal?.actor,
  ]);
  useEffect(() => {
    if (!status?.available) return;
    const controller = new AbortController();
    setCounts(null);
    setCountsError(false);
    const timer = setTimeout(() => {
      metadataApi
        .tableCounts(
          { databaseSchema: schema || undefined, query },
          controller.signal,
        )
        .then((value) => {
          if (!controller.signal.aborted) setCounts(value);
        })
        .catch(() => {
          if (!controller.signal.aborted) setCountsError(true);
        });
    }, 250);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [schema, query, status?.available, refresh, principal?.actor]);
  const openTable = (table: MetadataEntity) => {
    if (!table.reference.fully_qualified_name) return;
    const back = location.pathname + location.search;
    navigate(
      `/admin/data-catalog/assets/${encodeURIComponent(table.reference.fully_qualified_name)}?${new URLSearchParams({ returnTo: back })}`,
    );
  };
  if (unauthorized)
    return (
      <div className="metadata-empty">
        <Database size={28} />
        <h3>관리자 인증이 필요합니다</h3>
        <p>관리자 연결 후 데이터 자산을 다시 조회합니다.</p>
        <button onClick={requestLogin}>관리자 연결</button>
      </div>
    );

  if (!status && !error)
    return (
      <div className="loading-state">자산 연결 상태를 확인하고 있습니다…</div>
    );
  if (status && !status.enabled)
    return (
      <div className="metadata-empty">
        <Database size={28} />
        <h3>OpenMetadata가 설정되지 않았습니다</h3>
      </div>
    );
  if (status && !status.available)
    return (
      <div className="metadata-empty">
        <Database size={28} />
        <h3>OpenMetadata에 연결할 수 없습니다</h3>
        <p>{status.reason}</p>
        <button onClick={() => setRefresh((value) => value + 1)}>
          다시 시도
        </button>
      </div>
    );
  return (
    <CatalogLayout
      label="스키마 탐색"
      sidebar={
        <>
          <h2>데이터 자산</h2>
          <nav
            className="catalog-saved-views"
            aria-label="메타데이터 누락 필터"
          >
            <h3>저장된 보기</h3>
            {filters
              .filter((item) => item.id !== "all")
              .map((item) => (
                <button
                  key={item.id}
                  aria-pressed={filter === item.id}
                  onClick={() =>
                    update({ filter: filter === item.id ? "" : item.id })
                  }
                >
                  {item.label}
                  <small>{counts?.[item.id] ?? "—"}</small>
                </button>
              ))}
          </nav>
          <h3 className="catalog-schema-title">스키마</h3>
          <button
            className={!schema ? "selected" : ""}
            onClick={() => update({ schema: "" })}
          >
            <Database size={16} />
            <span>전체 자산</span>
          </button>
          {schemas.map((item) => (
            <button
              key={item.reference.entity_id}
              className={
                schema === item.reference.fully_qualified_name ? "selected" : ""
              }
              title={item.reference.fully_qualified_name || item.name}
              onClick={() =>
                update({ schema: item.reference.fully_qualified_name || "" })
              }
            >
              <Folder size={16} />
              <span>
                <strong>{item.display_name || item.name}</strong>
                <small>{item.reference.fully_qualified_name}</small>
              </span>
            </button>
          ))}
          {schema &&
            !schemas.some(
              (item) => item.reference.fully_qualified_name === schema,
            ) && <p className="selected-schema">선택: {schema}</p>}
          {schemaError && <p role="alert">{schemaError}</p>}
        </>
      }
    >
      <PageHeader
        title={
          schemas.find((item) => item.reference.fully_qualified_name === schema)
            ?.name || (schema ? "선택한 스키마" : "전체 자산")
        }
        description={
          loading
            ? "자산을 조회하고 있습니다…"
            : error
              ? "조회 실패"
              : `${tables.length}개 표시 · 검색 결과 ${total ?? 0}개`
        }
        actions={
          <button
            className="page-icon-button"
            aria-label="자산 새로고침"
            disabled={loading}
            onClick={() => setRefresh((value) => value + 1)}
          >
            <RefreshCw size={16} />
          </button>
        }
      />
      <SearchField
        label="전체 자산 검색"
        placeholder="이름, 설명, 태그, 소유자 검색"
        value={query}
        onChange={(value) => update({ q: value })}
      />
      <div className="page-controls">
        <span className="workspace-muted">
          {filters.find((item) => item.id === filter)?.label} ·{" "}
          {loading ? "확인 중" : `${total ?? 0}개`}
        </span>
        <label>
          정렬
          <select
            value={sort}
            onChange={(event) => update({ sort: event.target.value })}
          >
            <option value="asc">이름 오름차순</option>
            <option value="desc">이름 내림차순</option>
          </select>
        </label>
      </div>
      {error && (
        <div role="alert" className="workspace-error">
          자산 조회 실패: {error}{" "}
          <button onClick={() => setRefresh((value) => value + 1)}>
            다시 시도
          </button>
        </div>
      )}
      <div className="asset-catalog-table-wrap" aria-busy={loading}>
        <table className="asset-catalog-table">
          <thead>
            <tr>
              <th>자산</th>
              <th>설명</th>
              <th>태그·용어</th>
              <th>소유자</th>
              <th>
                <span className="sr-only">열기</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {tables.map((table) => (
              <tr
                key={table.reference.entity_id}
                onClick={() => openTable(table)}
                tabIndex={0}
                onKeyDown={(event) => {
                  if (event.key === "Enter") openTable(table);
                }}
              >
                <td>
                  <div className="asset-name-cell">
                    <Table2 size={18} />
                    <span>
                      <strong>{table.display_name || table.name}</strong>
                      <code title={table.reference.fully_qualified_name || ""}>
                        {table.reference.fully_qualified_name}
                      </code>
                    </span>
                  </div>
                </td>
                <td>
                  <p
                    className={
                      table.description
                        ? "asset-description"
                        : "asset-value-missing"
                    }
                    title={table.description || ""}
                  >
                    {table.description || "설명 없음"}
                  </p>
                </td>
                <td>
                  <div className="asset-labels">
                    {table.tags.slice(0, 2).map((tag, index) => (
                      <span
                        key={index}
                        title={String(tag.tagFQN || tag.name || "")}
                      >
                        {String(
                          tag.displayName || tag.name || tag.tagFQN || "태그",
                        )}
                      </span>
                    ))}
                    {table.tags.length > 2 && (
                      <small>+{table.tags.length - 2}</small>
                    )}
                    {!table.tags.length && (
                      <span className="asset-value-missing">없음</span>
                    )}
                  </div>
                </td>
                <td>
                  <span
                    className={
                      table.owners.length
                        ? "asset-owner"
                        : "asset-value-missing"
                    }
                  >
                    {table.owners
                      .map((owner) =>
                        String(owner.displayName || owner.name || owner.id),
                      )
                      .join(", ") || "미지정"}
                  </span>
                </td>
                <td>
                  <ChevronRight size={16} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {loading ? (
          <div className="asset-catalog-empty" role="status">
            자산을 불러오고 있습니다…
          </div>
        ) : (
          !error &&
          !tables.length && (
            <div className="asset-catalog-empty">
              {query || filter !== "all"
                ? "조건에 맞는 자산이 없습니다."
                : "등록된 자산이 없습니다."}
              {(query || filter !== "all") && (
                <button onClick={() => update({ q: "", filter: "" })}>
                  검색·필터 초기화
                </button>
              )}
            </div>
          )
        )}
      </div>
      {countsError && (
        <p role="status">
          누락 항목 집계를 조회하지 못했습니다. 자산 목록은 계속 사용할 수
          있습니다.
        </p>
      )}
      {(total ?? 0) > 10000 && (
        <p role="status">
          검색 결과 중 첫 10,000개까지 탐색할 수 있습니다. 검색어나 스키마로
          범위를 좁히세요.
        </p>
      )}
      <CatalogPagination
        page={page}
        pageSize={pageSize}
        total={Math.min(total ?? 0, 10000)}
        loading={loading}
        error={!!error}
        onPageChange={(value) => update({ page: String(value) })}
        onPageSizeChange={(value) => update({ size: String(value) })}
      />
    </CatalogLayout>
  );
}
