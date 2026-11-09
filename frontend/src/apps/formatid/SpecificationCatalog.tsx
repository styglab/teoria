import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { CatalogPagination } from "../../components/workspace/CatalogPagination";
import { AnalysisExplorer } from "./AnalysisExplorer";
import { documentCatalogApi, type CatalogDocument } from "./api";
import {
  readCatalogView,
  saveCatalogView,
  useCatalogQuery,
} from "./catalog_queries";
import { resultLabel } from "./document_results";
import "./specification_catalog.css";
export { comparisonRows, DocumentComparison } from "./document_comparison";
export { authority } from "./result_authority";

const statuses: Record<string, string> = {
  running: "처리 중",
  extracted: "추출 완료",
  partial: "일부 완료",
  failed: "실패",
  excluded: "대상 제외",
};
const date = (value: string) => new Date(value).toLocaleString("ko-KR");
export function SpecificationCatalog() {
  const [params, setParams] = useSearchParams();
  const [groupQuery, setGroupQuery] = useState("");
  const [debouncedGroupQuery, setDebouncedGroupQuery] = useState("");
  const [groupPage, setGroupPage] = useState(0);
  const viewKey = params.toString();
  const [selection, setSelection] = useState<CatalogDocument[]>(
    () => readCatalogView(viewKey)?.selection || [],
  );
  const root = useRef<HTMLElement>(null);
  const selectedRef = useRef(selection);
  selectedRef.current = selection;
  const restored = useRef<string | null>(null);
  const viewReady = useRef(false);
  const [compact, setCompact] = useState(
    () => window.matchMedia?.("(max-width: 700px)").matches || false,
  );
  const [filtersOpen, setFiltersOpen] = useState(!compact);
  useEffect(() => {
    const media = window.matchMedia?.("(max-width: 700px)");
    if (!media) return;
    const changed = () => {
      setCompact(media.matches);
      setFiltersOpen(!media.matches);
    };
    media.addEventListener("change", changed);
    return () => media.removeEventListener("change", changed);
  }, []);
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedGroupQuery(groupQuery), 250);
    return () => clearTimeout(timer);
  }, [groupQuery]);
  useLayoutEffect(() => {
    const element = root.current;
    viewReady.current = false;
    return () => {
      if (element && viewReady.current)
        saveCatalogView(viewKey, {
          scroll: element.scrollTop,
          selection: selectedRef.current,
        });
    };
  }, [viewKey]);
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
  const groupResult = useCatalogQuery(
    `classifications:${debouncedGroupQuery}:${groupPage}`,
    (signal) =>
      documentCatalogApi.classifications(
        debouncedGroupQuery,
        groupPage * 100,
        signal,
      ),
    { keepPrevious: true, refresh },
  );
  const groups = groupResult.data;
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
  const list = useCatalogQuery(
    `documents:${request}`,
    (signal) => documentCatalogApi.documents(request, signal),
    { keepPrevious: true, refresh },
  );
  const data = list.data,
    error = list.error;
  useEffect(() => {
    if (!data || list.loading || list.previous || restored.current === viewKey)
      return;
    restored.current = viewKey;
    const previous = readCatalogView(viewKey);
    if (root.current) root.current.scrollTop = previous?.scroll || 0;
    viewReady.current = true;
  }, [data, list.loading, list.previous, viewKey]);
  const canSelect = (doc: CatalogDocument) =>
    doc.result_available &&
    !list.loading &&
    !list.previous &&
    selection.length < 4 &&
    (!selection.length ||
      selection[0].classification_code === doc.classification_code);
  const toggle = (doc: CatalogDocument) =>
    setSelection((previous) =>
      previous.some((d) => d.catalog_id === doc.catalog_id)
        ? previous.filter((d) => d.catalog_id !== doc.catalog_id)
        : [...previous, doc],
    );
  useEffect(() => {
    setQuery(params.get("q") || "");
  }, [params]);
  return (
    <section className="spec-catalog" ref={root}>
      <header className="spec-catalog-heading">
        <div>
          <h1>규격서 탐색</h1>
          <p>
            규격서를 열어 물품·구성품과 속성이 원문에 맞게 추출됐는지
            확인합니다.
          </p>
        </div>
        <div>
          <Button asChild variant="outline">
            <Link
              to={`/admin/domains/goods/dictionary${classification ? `?classification=${encodeURIComponent(classification)}` : ""}`}
            >
              물품 사전
            </Link>
          </Button>
          <Button asChild variant="outline">
            <Link to="/admin/specifications/standards">처리 기준</Link>
          </Button>
          <Button asChild>
            <Link to="?new=1">규격서 등록</Link>
          </Button>
          <Button asChild variant="outline">
            <Link to="?view=runs">처리 이력</Link>
          </Button>
          <Button variant="outline" onClick={() => setRefresh((v) => v + 1)}>
            새로고침
          </Button>
        </div>
      </header>
      <div className="spec-catalog-layout">
        <aside aria-label="물품 분류">
          <h2>물품 분류</h2>
          <label>
            분류코드 검색
            <Input
              value={groupQuery}
              onChange={(e) => {
                setGroupQuery(e.target.value);
                setGroupPage(0);
              }}
              placeholder="10자리 분류코드"
            />
          </label>
          <Button
            variant="outline"
            aria-pressed={!classification}
            onClick={() => update({ class: "" })}
          >
            전체 규격서 {groups?.documents ?? ""}
          </Button>
          {groupResult.error && (
            <div className="spec-query-error" role="alert">
              분류 목록: {groupResult.error}
              <Button variant="outline" onClick={groupResult.retry}>
                분류 다시 조회
              </Button>
            </div>
          )}
          {groupResult.loading && <p role="status">분류 갱신 중</p>}
          {groups?.items.map((group) => (
            <Button
              variant="outline"
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
            </Button>
          ))}
          {groups && groups.total > 100 && (
            <div>
              <Button
                variant="outline"
                disabled={groupPage === 0}
                onClick={() => setGroupPage((v) => v - 1)}
              >
                이전 분류
              </Button>
              <Button
                variant="outline"
                disabled={(groupPage + 1) * 100 >= groups.total}
                onClick={() => setGroupPage((v) => v + 1)}
              >
                다음 분류
              </Button>
            </div>
          )}
        </aside>
        <section className="spec-catalog-content" aria-label="규격서 목록">
          <details
            className="spec-filter-panel"
            open={filtersOpen}
            onToggle={(event) => setFiltersOpen(event.currentTarget.open)}
          >
            <summary>검색·필터</summary>
            <form
              className="spec-filters"
              onSubmit={(e) => {
                e.preventDefault();
                update({ q: query });
              }}
            >
              <label>
                파일명·공고번호
                <Input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="규격서 검색"
                />
              </label>
              <Button variant="outline" type="submit">
                검색
              </Button>
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
                <Input
                  type="date"
                  value={params.get("since") || ""}
                  onChange={(e) => update({ since: e.target.value })}
                />
              </label>
              <label>
                처리 종료일
                <Input
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
          </details>
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
              <Button variant="outline" onClick={() => setSelection([])}>
                선택 해제
              </Button>
              <small>같은 분류의 결과가 있는 문서 2–4개를 선택하세요.</small>
            </div>
          )}
          {error && (
            <div className="spec-query-error" role="alert">
              문서 목록: {error}
              <Button variant="outline" onClick={list.retry}>
                문서 다시 조회
              </Button>
            </div>
          )}
          {list.loading && data && (
            <p role="status" className="spec-refresh-note">
              기존 목록을 유지하며 새 결과를 조회하고 있습니다.
            </p>
          )}
          {list.previous && !list.loading && (
            <p className="spec-refresh-note">
              이전 조회 조건의 결과입니다. 다시 조회해 최신 조건을 적용하세요.
            </p>
          )}
          {!data && list.loading ? (
            <p role="status">규격서를 불러오는 중입니다.</p>
          ) : !data ? null : !data.items.length ? (
            <p>조건에 맞는 규격서가 없습니다.</p>
          ) : compact ? (
            <div
              className="spec-document-cards"
              aria-label="규격서 카드 목록"
              aria-busy={list.loading}
            >
              {data.items.map((doc) => (
                <article className="spec-document-card" key={doc.catalog_id}>
                  <header>
                    <Link to={link({ document: doc.catalog_id })}>
                      {doc.filename}
                    </Link>
                    <Input
                      type="checkbox"
                      aria-label={`${doc.filename} 비교 선택`}
                      checked={selection.some(
                        (d) => d.catalog_id === doc.catalog_id,
                      )}
                      disabled={
                        !selection.some(
                          (d) => d.catalog_id === doc.catalog_id,
                        ) && !canSelect(doc)
                      }
                      onChange={() => toggle(doc)}
                    />
                  </header>
                  <dl>
                    <div>
                      <dt>물품 분류</dt>
                      <dd>{doc.classification_code || "미분류"}</dd>
                    </div>
                    <div>
                      <dt>추출 결과</dt>
                      <dd>
                        {statuses[
                          doc.result_available ? doc.status : doc.latest_status
                        ] || doc.latest_status}
                      </dd>
                    </div>
                    <div>
                      <dt>조회 결과</dt>
                      <dd>
                        {doc.result_available
                          ? doc.run_id !== doc.latest_run_id
                            ? "이전 정상 결과 유지"
                            : "최신 결과"
                          : "조회 결과 없음"}
                      </dd>
                    </div>
                  </dl>
                  <p>
                    {doc.notice_number ? `공고 ${doc.notice_number} · ` : ""}
                    {doc.attempt_count}회 처리 · {date(doc.latest_started_at)}
                  </p>
                </article>
              ))}
            </div>
          ) : (
            <div className="spec-table-scroll" aria-busy={list.loading}>
              <table>
                <caption className="sr-only">분류별 규격서 목록</caption>
                <thead>
                  <tr>
                    <th>비교</th>
                    <th>규격서</th>
                    <th>물품 분류</th>
                    <th>추출 결과</th>
                    <th>최근 처리 시각</th>
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
                          <Input
                            type="checkbox"
                            aria-label={`${doc.filename} 비교 선택`}
                            checked={checked}
                            disabled={!checked && !canSelect(doc)}
                            onChange={() => toggle(doc)}
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
                          {statuses[
                            doc.result_available
                              ? doc.status
                              : doc.latest_status
                          ] || doc.latest_status}
                          {doc.run_id !== doc.latest_run_id && (
                            <small>
                              최근 처리:{" "}
                              {statuses[doc.latest_status] || doc.latest_status}{" "}
                              · <span>이전 정상 결과 유지</span>
                            </small>
                          )}
                        </td>
                        <td>
                          {date(doc.latest_started_at)}
                          {!doc.result_available && (
                            <small>조회 결과 없음</small>
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
            loading={list.loading}
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
        </section>
      </div>
    </section>
  );
}
export function CatalogDocumentView({ id }: { id: string }) {
  const [params] = useSearchParams();
  const [historyPage, setHistoryPage] = useState(0);
  const [historyOpen, setHistoryOpen] = useState(false);
  const document = useCatalogQuery(`result:${id}`, (signal) =>
    documentCatalogApi.result(id, signal),
  );
  const historyResult = useCatalogQuery(
    historyOpen ? `history:${id}:${historyPage}` : null,
    (signal) => documentCatalogApi.history(id, historyPage, signal),
  );
  const data = document.data,
    error = document.error,
    history = historyResult.data,
    historyError = historyResult.error;
  const back = new URLSearchParams(params);
  back.delete("document");
  back.delete("attribute");
  back.delete("compare");
  return (
    <section className="spec-catalog spec-document">
      <Link to={`?${back}`}>← 규격서 목록</Link>
      {error ? (
        <div role="alert" className="spec-query-error">
          {error}
          <Button variant="outline" onClick={document.retry}>
            다시 조회
          </Button>
        </div>
      ) : !data ? (
        <p role="status">문서 결과를 불러오는 중입니다.</p>
      ) : (
        <>
          <header className="spec-catalog-heading">
            <div>
              <h1>{data.document.filename}</h1>
              <p>
                {data.document.classification_code || "미분류"} ·{" "}
                {statuses[data.document.status] || data.document.status} · 결과
                기준 {date(data.document.started_at)}
              </p>
            </div>
            <Button
              variant="outline"
              aria-expanded={historyOpen}
              onClick={() => setHistoryOpen((v) => !v)}
            >
              처리 이력 {data.document.attempt_count}회
            </Button>
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
            <section className="spec-history" aria-label="문서 처리 이력">
              {historyError ? (
                <div role="alert" className="spec-query-error">
                  {historyError}
                  <Button variant="outline" onClick={historyResult.retry}>
                    이력 다시 조회
                  </Button>
                </div>
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
                  <Button
                    variant="outline"
                    disabled={!historyPage}
                    onClick={() => setHistoryPage((v) => v - 1)}
                  >
                    이전 이력
                  </Button>
                  <Button
                    variant="outline"
                    disabled={(historyPage + 1) * 25 >= history.total}
                    onClick={() => setHistoryPage((v) => v + 1)}
                  >
                    다음 이력
                  </Button>
                </>
              )}
            </section>
          )}
          {data.result ? (
            <AnalysisExplorer
              runId={data.document.run_id}
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
