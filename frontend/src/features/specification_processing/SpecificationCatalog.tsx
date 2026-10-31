import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  documentCatalogApi,
  type CatalogDocument,
  type DocumentResult,
} from "../../api/specification_processing";
import { CatalogPagination } from "../../components/workspace/CatalogPagination";
import { AnalysisExplorer } from "./AnalysisExplorer";
import {
  resultRows,
  resultLabel,
  normalizedResultValue,
} from "./document_results";
import "./specification_catalog.css";

const statuses: Record<string, string> = {
  running: "처리 중",
  extracted: "추출 완료",
  partial: "일부 완료",
  failed: "실패",
  excluded: "대상 제외",
};
const date = (value: string) => new Date(value).toLocaleString("ko-KR");
export function authority(result: DocumentResult["result"]) {
  return result?.result_kind === "profile"
    ? "프로파일 표준 적용"
    : result?.result_kind === "extraction_standard"
      ? "추출용 표준 적용"
      : "원문 추출 결과";
}
export function SpecificationCatalog() {
  const [params, setParams] = useSearchParams();
  const [groups, setGroups] = useState<Awaited<
    ReturnType<typeof documentCatalogApi.classifications>
  > | null>(null);
  const [groupQuery, setGroupQuery] = useState("");
  const [groupPage, setGroupPage] = useState(0);
  const [data, setData] = useState<{
    items: CatalogDocument[];
    total: number;
  } | null>(null);
  const [error, setError] = useState("");
  const [selection, setSelection] = useState<CatalogDocument[]>([]);
  const [query, setQuery] = useState(params.get("q") || "");
  const [refresh, setRefresh] = useState(0);
  const page = Math.max(0, Math.floor(Number(params.get("page")) || 0));
  const size = params.get("size") === "50" ? 50 : 25;
  const classification = params.get("class") || "";
  const update = (changes: Record<string, string>) =>
    setParams((previous) => {
      const next = new URLSearchParams(previous);
      next.delete("page");
      Object.entries(changes).forEach(([key, value]) =>
        value ? next.set(key, value) : next.delete(key),
      );
      return next;
    });
  const link = (changes: Record<string, string>) => {
    const next = new URLSearchParams(params);
    Object.entries(changes).forEach(([key, value]) => next.set(key, value));
    return `?${next}`;
  };
  useEffect(() => {
    let active = true;
    documentCatalogApi
      .classifications(groupQuery, groupPage * 100)
      .then((v) => {
        if (active) setGroups(v);
      })
      .catch(() => {
        if (active) setError("분류 목록을 불러오지 못했습니다.");
      });
    return () => {
      active = false;
    };
  }, [groupQuery, groupPage, refresh]);
  useEffect(() => {
    let active = true;
    setData(null);
    setError("");
    const request = new URLSearchParams({
      classification,
      query: params.get("q") || "",
      status: params.get("status") || "all",
      sort: params.get("sort") || "recent",
      offset: String(page * size),
      limit: String(size),
    });
    ["since", "until"].forEach((key) => {
      if (params.get(key)) request.set(key, params.get(key)!);
    });
    documentCatalogApi
      .documents(request)
      .then((v) => {
        if (active) setData(v);
      })
      .catch(() => {
        if (active)
          setError(
            "규격서를 불러오지 못했습니다. 필터와 연결 상태를 확인하세요.",
          );
      });
    return () => {
      active = false;
    };
  }, [params, classification, page, size, refresh]);
  useEffect(() => {
    setQuery(params.get("q") || "");
  }, [params]);
  return (
    <section className="spec-catalog">
      <header className="spec-catalog-heading">
        <div>
          <h1>규격서 탐색</h1>
          <p>물품 분류별 구성품·관계·속성과 적용 표준을 확인합니다.</p>
        </div>
        <div>
          <Link to="?new=1">규격서 등록</Link>
          <Link to="?view=runs">처리 이력</Link>
          <button onClick={() => setRefresh((v) => v + 1)}>새로고침</button>
        </div>
      </header>
      <div className="spec-catalog-layout">
        <aside aria-label="물품 분류">
          <h2>물품 분류</h2>
          <label>
            분류코드 검색
            <input
              value={groupQuery}
              onChange={(e) => {
                setGroupQuery(e.target.value);
                setGroupPage(0);
              }}
              placeholder="10자리 분류코드"
            />
          </label>
          <button
            aria-pressed={!classification}
            onClick={() => update({ class: "" })}
          >
            전체 규격서 {groups?.documents ?? ""}
          </button>
          {groups?.items.map((group) => (
            <button
              key={group.classification_code || "unclassified"}
              aria-pressed={
                classification === (group.classification_code || "unclassified")
              }
              onClick={() =>
                update({ class: group.classification_code || "unclassified" })
              }
            >
              {group.classification_code || "미분류"}{" "}
              <span>{group.documents}건</span>
            </button>
          ))}
          {groups && groups.total > 100 && (
            <div>
              <button
                disabled={groupPage === 0}
                onClick={() => setGroupPage((v) => v - 1)}
              >
                이전 분류
              </button>
              <button
                disabled={(groupPage + 1) * 100 >= groups.total}
                onClick={() => setGroupPage((v) => v + 1)}
              >
                다음 분류
              </button>
            </div>
          )}
        </aside>
        <main>
          <form
            className="spec-filters"
            onSubmit={(e) => {
              e.preventDefault();
              update({ q: query });
            }}
          >
            <label>
              파일명·공고번호
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="규격서 검색"
              />
            </label>
            <button type="submit">검색</button>
            <label>
              최근 처리 상태
              <select
                value={params.get("status") || "all"}
                onChange={(e) => update({ status: e.target.value })}
              >
                <option value="all">전체</option>
                {Object.entries(statuses).map(([key, label]) => (
                  <option key={key} value={key}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              처리 시작일
              <input
                type="date"
                value={params.get("since") || ""}
                onChange={(e) => update({ since: e.target.value })}
              />
            </label>
            <label>
              처리 종료일
              <input
                type="date"
                value={params.get("until") || ""}
                onChange={(e) => update({ until: e.target.value })}
              />
            </label>
            <label>
              정렬
              <select
                value={params.get("sort") || "recent"}
                onChange={(e) => update({ sort: e.target.value })}
              >
                <option value="recent">최근 처리순</option>
                <option value="name">파일명순</option>
              </select>
            </label>
          </form>
          {selection.length > 0 && (
            <div className="spec-selection" role="status">
              비교할 규격서 {selection.length}/4{" "}
              <Link
                aria-disabled={selection.length < 2}
                to={
                  selection.length >= 2
                    ? link({
                        compare: selection.map((d) => d.catalog_id).join(","),
                      })
                    : "#"
                }
                onClick={(e) => {
                  if (selection.length < 2) e.preventDefault();
                }}
              >
                선택한 규격서 비교
              </Link>
              <button onClick={() => setSelection([])}>선택 해제</button>
              <small>같은 분류의 결과가 있는 문서 2–4개를 선택하세요.</small>
            </div>
          )}
          {error ? (
            <p role="alert">{error}</p>
          ) : !data ? (
            <p role="status">규격서를 불러오는 중입니다.</p>
          ) : !data.items.length ? (
            <p>조건에 맞는 규격서가 없습니다.</p>
          ) : (
            <div className="spec-table-scroll">
              <table>
                <caption className="sr-only">분류별 규격서 목록</caption>
                <thead>
                  <tr>
                    <th>비교</th>
                    <th>규격서</th>
                    <th>물품 분류</th>
                    <th>최근 처리</th>
                    <th>조회 결과</th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((doc) => {
                    const checked = selection.some(
                      (d) => d.catalog_id === doc.catalog_id,
                    );
                    return (
                      <tr key={doc.catalog_id}>
                        <td>
                          <input
                            type="checkbox"
                            aria-label={`${doc.filename} 비교 선택`}
                            checked={checked}
                            disabled={
                              !checked &&
                              (!doc.result_available ||
                                selection.length >= 4 ||
                                (selection.length > 0 &&
                                  selection[0].classification_code !==
                                    doc.classification_code))
                            }
                            onChange={() =>
                              setSelection((previous) =>
                                checked
                                  ? previous.filter(
                                      (d) => d.catalog_id !== doc.catalog_id,
                                    )
                                  : [...previous, doc],
                              )
                            }
                          />
                        </td>
                        <td>
                          <Link to={link({ document: doc.catalog_id })}>
                            {doc.filename}
                          </Link>
                          <small>
                            {doc.notice_number
                              ? `공고 ${doc.notice_number} · `
                              : ""}
                            {doc.attempt_count}회 처리 · 원문 버전{" "}
                            {doc.source_sha256?.slice(0, 8) || "미확인"}
                          </small>
                        </td>
                        <td>{doc.classification_code || "미분류"}</td>
                        <td>
                          {statuses[doc.latest_status] || doc.latest_status}
                          <small>{date(doc.latest_started_at)}</small>
                        </td>
                        <td>
                          {doc.result_available ? (
                            <>
                              {statuses[doc.status]}
                              <small>
                                {doc.run_id !== doc.latest_run_id
                                  ? "이전 정상 결과 유지"
                                  : "최신 결과"}
                              </small>
                            </>
                          ) : (
                            "조회 결과 없음"
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
          <CatalogPagination
            page={page}
            pageSize={size}
            total={data?.total || 0}
            loading={!data && !error}
            error={!!error}
            onPageChange={(v) =>
              setParams((previous) => {
                const next = new URLSearchParams(previous);
                next.set("page", String(v));
                return next;
              })
            }
            onPageSizeChange={(v) => update({ size: String(v) })}
          />
        </main>
      </div>
    </section>
  );
}
export function CatalogDocumentView({ id }: { id: string }) {
  const [params] = useSearchParams();
  const [data, setData] = useState<DocumentResult | null>(null);
  const [error, setError] = useState("");
  const [history, setHistory] = useState<Awaited<
    ReturnType<typeof documentCatalogApi.history>
  > | null>(null);
  const [historyPage, setHistoryPage] = useState(0);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [historyError, setHistoryError] = useState("");
  useEffect(() => {
    let active = true;
    setData(null);
    setError("");
    documentCatalogApi
      .result(id)
      .then((v) => {
        if (active) setData(v);
      })
      .catch(() => {
        if (active) setError("문서 결과를 불러오지 못했습니다.");
      });
    return () => {
      active = false;
    };
  }, [id]);
  useEffect(() => {
    if (!historyOpen) return;
    let active = true;
    setHistory(null);
    setHistoryError("");
    documentCatalogApi
      .history(id, historyPage)
      .then((v) => {
        if (active) setHistory(v);
      })
      .catch(() => {
        if (active) setHistoryError("처리 이력을 불러오지 못했습니다.");
      });
    return () => {
      active = false;
    };
  }, [id, historyOpen, historyPage]);
  const back = new URLSearchParams(params);
  back.delete("document");
  back.delete("attribute");
  back.delete("compare");
  return (
    <section className="spec-catalog spec-document">
      <Link to={`?${back}`}>← 규격서 목록</Link>
      {error ? (
        <p role="alert">{error}</p>
      ) : !data ? (
        <p role="status">문서 결과를 불러오는 중입니다.</p>
      ) : (
        <>
          <header className="spec-catalog-heading">
            <div>
              <h1>{data.document.filename}</h1>
              <p>
                {data.document.classification_code || "미분류"} ·{" "}
                {authority(data.result)} · 결과 기준{" "}
                {date(data.document.started_at)}
              </p>
            </div>
            <button
              aria-expanded={historyOpen}
              onClick={() => setHistoryOpen((v) => !v)}
            >
              처리 이력 {data.document.attempt_count}회
            </button>
          </header>
          {data.document.run_id !== data.document.latest_run_id && (
            <p className="spec-notice" role="status">
              최근 처리:{" "}
              {statuses[data.document.latest_status] ||
                data.document.latest_status}
              . 이전에 조회 가능한 결과를 표시합니다.
            </p>
          )}
          {data.result?.normalization && (
            <details className="spec-provenance">
              <summary>적용 기준과 결과 정보</summary>
              <p>
                표준 버전{" "}
                {resultLabel(data.result.normalization.standard_version)}
              </p>
              {data.result.result_kind === "profile" ? (
                <>
                  <p>
                    프로파일 revision{" "}
                    {resultLabel(data.result.normalization.profile_revision_id)}
                  </p>
                  <p>
                    Ontology {resultLabel(data.result.normalization.ontology)}
                  </p>
                </>
              ) : (
                <p>
                  추출에 사용한 표준 초안입니다. 게시된 Ontology와의 매핑을
                  의미하지 않습니다.
                </p>
              )}
              <p>원문 SHA-256 {data.document.source_sha256}</p>
              <Link
                to={`?view=runs&run=${encodeURIComponent(data.document.run_id)}`}
              >
                실행 정보
              </Link>
            </details>
          )}
          {historyOpen && (
            <section aria-label="문서 처리 이력">
              {historyError ? (
                <p role="alert">{historyError}</p>
              ) : !history ? (
                <p>이력 조회 중</p>
              ) : (
                <>
                  <ul>
                    {history.items.map((row) => (
                      <li key={row.run_id}>
                        <Link
                          to={`?view=runs&run=${encodeURIComponent(row.run_id)}`}
                        >
                          {date(row.started_at)} ·{" "}
                          {statuses[row.status] || row.status}
                        </Link>
                      </li>
                    ))}
                  </ul>
                  <button
                    disabled={!historyPage}
                    onClick={() => setHistoryPage((v) => v - 1)}
                  >
                    이전 이력
                  </button>
                  <button
                    disabled={(historyPage + 1) * 25 >= history.total}
                    onClick={() => setHistoryPage((v) => v + 1)}
                  >
                    다음 이력
                  </button>
                </>
              )}
            </section>
          )}
          {data.result ? (
            <AnalysisExplorer
              value={data.result.extracted}
              normalization={data.result.normalization}
              mappingStatus={
                data.result.normalization ? "available" : "missing"
              }
              documentId={data.document.document_id}
              initialAttributeId={params.get("attribute") || ""}
            />
          ) : (
            <p>
              이 문서에는 아직 조회 가능한 결과가 없습니다. 처리 이력에서 상태를
              확인하세요.
            </p>
          )}
        </>
      )}
    </section>
  );
}

type ComparisonCell = { label: string; values: string[]; attributeId: string };
export function comparisonRows(documents: DocumentResult[]) {
  const matrix = new Map<
    string,
    { label: string; context: string; cells: ComparisonCell[][] }
  >();
  documents.forEach((document, index) => {
    const result = document.result;
    const norm = result?.normalization;
    if (!norm) return;
    // Never equate IDs across standard snapshots, target scopes, roles or units.
    const ontology = norm.ontology as Record<string, unknown> | undefined;
    const standard = norm.standard_ref as Record<string, unknown> | undefined;
    const snapshot =
      result.result_kind === "profile"
        ? `ontology:${ontology?.version_id}:${ontology?.checksum}:${norm.package_checksum}`
        : standard?.sha256
          ? `draft:${standard.sha256}`
          : `document:${document.document.catalog_id}`;
    const extracted = resultRows(result.extracted.documents)[0];
    const entities = resultRows(extracted?.entities);
    const mappings = resultRows(norm.documents).find(
      (d) => d.document_id === result.document_id,
    );
    const entityMappings = resultRows(mappings?.entities);
    resultRows(norm.attributes)
      .filter(
        (a) => a.document_id === result.document_id && a.status === "applied",
      )
      .forEach((attribute) =>
        resultRows(attribute.facts).forEach((fact) => {
          const value = (fact.value || {}) as Record<string, unknown>;
          const targets = Array.isArray(fact.subject_ids)
            ? fact.subject_ids.map(String)
            : Array.isArray(fact.subject_observation_ids)
              ? fact.subject_observation_ids.map((observation) =>
                  String(
                    entityMappings.find((e) => e.observation_id === observation)
                      ?.source_entity_id || `unknown:${observation}`,
                  ),
                )
              : [];
          const concepts = targets
            .map(
              (id) =>
                entityMappings.find((e) => e.source_entity_id === id)
                  ?.concept_id || `local:${document.document.catalog_id}:${id}`,
            )
            .sort();
          const property =
            fact.property_concept_id ||
            fact.property_id ||
            fact.property_stable_key;
          if (!property) return;
          const key = JSON.stringify([
            snapshot,
            property,
            concepts,
            fact.role || "",
            fact.semantic_scope || "",
            value.unit || "",
            !targets.length ||
            !fact.role ||
            !fact.semantic_scope ||
            fact.semantic_scope === "unknown"
              ? document.document.catalog_id
              : "",
          ]);
          const row = matrix.get(key) || {
            label: resultLabel(
              fact.property_label || fact.property_stable_key || property,
            ),
            context: [
              resultLabel(fact.role),
              resultLabel(fact.semantic_scope),
              resultLabel(value.unit),
            ].join(" · "),
            cells: documents.map(() => []),
          };
          const targetNames =
            targets
              .map((id) =>
                resultLabel(entities.find((e) => e.id === id)?.name || id),
              )
              .join(", ") || "대상 미확인";
          row.cells[index].push({
            label: targetNames,
            attributeId: String(attribute.attribute_id || ""),
            values: [
              [
                fact.operator_raw || fact.operator,
                normalizedResultValue(fact),
                ...(Array.isArray(fact.qualifiers_raw)
                  ? fact.qualifiers_raw
                  : []),
              ]
                .filter(Boolean)
                .map(resultLabel)
                .join(" · "),
            ],
          });
          matrix.set(key, row);
        }),
      );
  });
  return [...matrix.values()];
}
export function DocumentComparison({ ids }: { ids: string[] }) {
  const [params] = useSearchParams();
  const [data, setData] = useState<DocumentResult[] | null>(null);
  const [error, setError] = useState("");
  const key = ids.join(",");
  useEffect(() => {
    let active = true;
    setData(null);
    setError("");
    if (ids.length < 2 || ids.length > 4 || new Set(ids).size !== ids.length) {
      setError("서로 다른 규격서 2–4개를 선택하세요.");
      return;
    }
    Promise.all(ids.map((id) => documentCatalogApi.result(id)))
      .then((v) => {
        if (!active) return;
        if (
          v.some((d) => !d.result) ||
          new Set(v.map((d) => d.document.classification_code)).size !== 1
        ) {
          setError("같은 분류에서 결과가 있는 규격서를 선택하세요.");
          return;
        }
        setData(v);
      })
      .catch(() => {
        if (active) setError("비교 결과를 불러오지 못했습니다.");
      });
    return () => {
      active = false;
    };
  }, [key]);
  const back = new URLSearchParams(params);
  back.delete("compare");
  const matrix = data ? comparisonRows(data) : [];
  return (
    <section className="spec-catalog">
      <Link to={`?${back}`}>← 규격서 목록</Link>
      <h1>규격서 표준 속성 비교</h1>
      <p>
        같은 표준 스냅샷·대상 개념·속성·역할·범위·단위가 확인된 값만 같은 행에
        배치합니다. 다른 구성품의 값은 합치지 않습니다.
      </p>
      {error ? (
        <p role="alert">{error}</p>
      ) : !data ? (
        <p role="status">비교 자료를 불러오는 중입니다.</p>
      ) : (
        <>
          <div className="spec-table-scroll">
            <table className="spec-comparison">
              <thead>
                <tr>
                  <th>표준 속성 / 범위</th>
                  {data.map((d) => {
                    const next = new URLSearchParams(back);
                    next.set("document", d.document.catalog_id);
                    return (
                      <th key={d.document.catalog_id}>
                        <Link to={`?${next}`}>{d.document.filename}</Link>
                        <small>{authority(d.result)}</small>
                      </th>
                    );
                  })}
                </tr>
              </thead>
              <tbody>
                {matrix.map((row, i) => (
                  <tr key={i}>
                    <th>
                      {row.label}
                      <small>{row.context}</small>
                    </th>
                    {row.cells.map((cell, j) => (
                      <td key={j}>
                        {cell.length
                          ? cell.map((item, k) => (
                              <div className="spec-comparison-value" key={k}>
                                <strong>{item.label}</strong>
                                <p>{item.values.join(" · ")}</p>
                                <Link
                                  to={`?${new URLSearchParams({ ...Object.fromEntries(back), document: data[j].document.catalog_id, ...(item.attributeId ? { attribute: item.attributeId } : {}) })}`}
                                >
                                  원문 확인
                                </Link>
                              </div>
                            ))
                          : "동일 기준의 매핑 값 없음"}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {!matrix.length && <p>비교 가능한 표준 매핑 속성이 없습니다.</p>}
          <p className="spec-notice">
            빈 셀은 요구사항이 없다는 뜻이 아닙니다. 미매핑 속성, 다른
            단위·범위·표준, 연결되지 않은 구성품은 각 규격서의 원문 결과에서
            확인하세요.
          </p>
        </>
      )}
    </section>
  );
}
