import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useServerQuery } from "../../../api/server_queries";
import { CatalogPagination } from "../../../components/workspace/CatalogPagination";
import { SelectionCatalog } from "../../../components/workspace/SelectionCatalog";
import {
  PageHeader,
  PageState,
} from "../../../components/workspace/WorkspaceLayout";
import { goodsDictionaryApi, type DictionaryRecord } from "./api";

import { ClassificationSelector } from "./ClassificationSelector";
import { MappingEditor } from "./MappingEditor";
import { OntologyDraftImport } from "./OntologyDraftImport";
import "./goods_dictionary.css";

const labels: Record<string, string> = {
  draft: "검토 대기",
  approved: "승인",
  rejected: "거절",
  deprecated: "중단",
};
const idOf = (row: DictionaryRecord) =>
  row.mapping_id || row.revision_id || row.entry_id || row.concept_id || "";
export function GoodsDictionary() {
  const [params, setParams] = useSearchParams();
  const classification = params.get("classification") || "";
  const library = classification === "all";
  const historical = params.get("history") === "1";
  const requestedTab =
    params.get("tab") ||
    (params.get("kind") === "source"
      ? "source"
      : params.get("kind") === "mapping"
        ? "mapping"
        : "types");
  const tab = (library
    ? ["types", "attributes"]
    : ["types", "attributes", "source", "mapping", "review"]
  ).includes(requestedTab)
    ? requestedTab
    : "types";
  const kind = ["types", "attributes"].includes(tab)
    ? "concept"
    : tab === "mapping"
      ? "mapping"
      : "source";
  const query = params.get("q") || "";
  const status = params.get("status") || "";
  const page = Math.max(0, Math.floor(Number(params.get("page")) || 0));
  const pageSize = params.get("size") === "50" ? 50 : 25;

  const [selected, setSelected] = useState("");
  const [actionError, setError] = useState("");

  const [revision, setRevision] = useState(0);

  const [actionDetailError, setDetailError] = useState("");
  const [rationale, setRationale] = useState("");
  const [busy, setBusy] = useState(false);
  const [editor, setEditor] = useState<"mapping" | null>(null);
  const update = (values: Record<string, string>) => {
    setEditor(null);
    setSelected("");
    setParams((old) => {
      const next = new URLSearchParams(old);
      Object.entries(values).forEach(([k, v]) =>
        v ? next.set(k, v) : next.delete(k),
      );
      next.delete("page");
      return next;
    });
  };
  const catalogQuery = useServerQuery(
    [
      "goods",
      "dictionary",
      kind,
      query,
      status,
      page,
      pageSize,
      classification,
      tab,
      historical,
      library,
    ],
    (signal) =>
      goodsDictionaryApi.catalog(
        new URLSearchParams({
          kind,
          ...(historical && kind !== "source" ? { historical: "true" } : {}),
          query,
          status,
          ...(library ? {} : { classification }),
          ...(tab === "types"
            ? { concept_kind: "item_type" }
            : tab === "attributes"
              ? { concept_kind: "characteristic" }
              : {}),
          ...(tab === "review" ? { unresolved: "true" } : {}),
          offset: String(page * pageSize),
          limit: String(pageSize),
        }),
        signal,
      ),
    { enabled: !!classification, refresh: revision },
  );
  const data = catalogQuery.data ?? { items: [], total: 0 };
  const loading = catalogQuery.loading;
  const error = actionError || catalogQuery.error;
  useEffect(() => {
    if (catalogQuery.data)
      setSelected((previous) =>
        data.items.some((row) => idOf(row) === previous)
          ? previous
          : idOf(data.items[0] || ({} as DictionaryRecord)),
      );
  }, [catalogQuery.data]);
  const row = data.items.find((r) => idOf(r) === selected);
  const auditQuery = useServerQuery(
    ["goods", "audit", kind, selected],
    (signal) => goodsDictionaryApi.audit(kind, selected, signal),
    { enabled: !!row, refresh: revision },
  );
  const evidenceQuery = useServerQuery(
    ["goods", "evidence", selected],
    (signal) => goodsDictionaryApi.evidence(selected, signal),
    { enabled: !!row && kind === "source", refresh: revision },
  );
  const impactQuery = useServerQuery(
    ["goods", "impact", kind, selected],
    () =>
      goodsDictionaryApi.impact(
        kind === "concept"
          ? { concept_ids: [row!.concept_id!] }
          : { source_entry_ids: [row!.source_entry_id || row!.entry_id!] },
      ),
    { enabled: !!row, refresh: revision },
  );
  const events = auditQuery.data?.items ?? [];
  const evidence = evidenceQuery.data?.items ?? [];
  const documents = impactQuery.data?.documents ?? [];
  const detailError =
    actionDetailError ||
    auditQuery.error ||
    evidenceQuery.error ||
    impactQuery.error;
  useEffect(() => {
    setDetailError("");
    setRationale("");
  }, [selected, kind]);
  const saved = () => {
    setEditor(null);
    setRevision((v) => v + 1);
  };
  const decide = async (action: string) => {
    if (!row) return;
    setBusy(true);
    setDetailError("");
    try {
      await goodsDictionaryApi.decide(kind, selected, action, rationale);
      saved();
    } catch (e) {
      setDetailError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const tabs = (
    <nav className="dictionary-tabs" aria-label="사전 보기">
      {[
        ["types", "물품·구성 유형"],
        ["attributes", "속성 정의"],
        ...(!library
          ? [
              ["source", "원문 표현"],
              ["mapping", "원문 표현 연결"],
              ["review", "검토 대기"],
            ]
          : []),
      ].map(([key, label]) => (
        <button
          key={key}
          aria-current={tab === key ? "page" : undefined}
          onClick={() => update({ tab: key, kind: "", q: "", status: "" })}
        >
          {label}
        </button>
      ))}
    </nav>
  );
  const selectScope = (code: string) =>
    update({ classification: code, tab: "types", kind: "", q: "", status: "" });
  const scopeControls = (
    <>
      <ClassificationSelector value={classification} onSelect={selectScope} />
      <button type="button" onClick={() => selectScope(library ? "" : "all")}>
        {library ? "품목별 사전으로" : "온톨로지 정의 조회"}
      </button>
    </>
  );
  if (!classification)
    return (
      <div className="workspace-page">
        <PageHeader
          title="물품 사전"
          description="품목코드를 선택해 유형·속성·원문 표현의 적용 범위를 확인하세요."
        />
        {scopeControls}
        <p>
          정의는 온톨로지에서 관리합니다. 품목별 적용 범위는 근거가 있는 원문
          표현 연결을 검토해 승인합니다.
        </p>
      </div>
    );
  return (
    <div className="goods-dictionary-catalog">
      <SelectionCatalog
        title={
          library
            ? "공통 정의"
            : classification === "unclassified"
              ? "품목 미확인"
              : `품목 ${classification}`
        }
        search={query}
        onSearch={(q) => update({ q })}
        selected={selected}
        onSelect={(id) => {
          setSelected(id);
          setEditor(null);
        }}
        items={data.items.map((r) => ({
          id: idOf(r),
          title:
            r.display_name ||
            r.preferred_name ||
            r.source_name ||
            r.content?.preferred_name ||
            r.concept_key ||
            "이름 없음",
          subtitle: r.kind === "item_type" ? "물품 유형" : "특성",
          status:
            kind === "concept" ? `정의 ${labels[r.status]}` : labels[r.status],
        }))}
        controls={
          <>
            {scopeControls}
            <label>
              상태
              <select
                value={status}
                onChange={(e) => update({ status: e.target.value })}
              >
                <option value="">전체</option>
                {Object.entries(labels).map(([k, v]) => (
                  <option key={k} value={k}>
                    {v}
                  </option>
                ))}
              </select>
            </label>
          </>
        }
        footer={
          <CatalogPagination
            page={page}
            pageSize={pageSize}
            total={data.total}
            loading={loading}
            onPageChange={(p) =>
              setParams((old) => {
                const next = new URLSearchParams(old);
                next.set("page", String(p));
                return next;
              })
            }
            onPageSizeChange={(size) => update({ size: String(size) })}
          />
        }
      >
        <PageHeader
          title={
            library
              ? "공통 정의"
              : `물품 사전 · ${classification === "unclassified" ? "품목 미확인" : classification}`
          }
          description={
            library
              ? "게시된 온톨로지 정의를 조회합니다. 새 의미는 온톨로지에서 작성합니다."
              : "선택 품목의 유형·속성·원문 표현과 승인된 연결을 관리합니다."
          }
        />
        {tabs}
        <p className="operations-note">
          의미 정의는 온톨로지가 관리하고, 사전은 원문 표현과 게시된 개념을
          연결합니다. 원문 등록만으로 의미가 확정되지는 않습니다.
        </p>
        {error && (
          <p role="alert">
            {error}{" "}
            <button onClick={() => setRevision((v) => v + 1)}>다시 조회</button>
          </p>
        )}
        <p>
          <Link to="/admin/semantic-model/ontology">
            온톨로지에서 정의 작성·검토
          </Link>
        </p>
        {kind !== "source" && (
          <button onClick={() => update({ history: historical ? "" : "1" })}>
            {historical
              ? "현재 온톨로지 연결 보기"
              : "과거 사전 정의·연결 이력"}
          </button>
        )}
        {historical && kind !== "source" && (
          <p role="note">
            과거 사전 이력입니다. 새 처리에서는 게시된 온톨로지 연결을
            사용합니다.
          </p>
        )}
        {!loading && !error && !data.items.length && (
          <PageState
            title={
              tab === "review"
                ? "이 품목에서 의미를 확정하지 못한 원문 표현이 없습니다"
                : "조건에 맞는 사전 항목이 없습니다"
            }
          />
        )}
        {!library && kind === "concept" && (
          <p>
            <button onClick={() => selectScope("all")}>
              온톨로지 정의 조회
            </button>
            에서 게시된 개념을 확인하고, 이 품목의 원문 표현과 연결하세요.
          </p>
        )}
        {loading && <PageState loading title="사전을 조회하고 있습니다…" />}
        {editor === "mapping" && row && (
          <MappingEditor
            key={selected}
            source={row}
            classification={
              classification === "unclassified" ? "" : classification
            }
            onSaved={saved}
            onCancel={() => setEditor(null)}
          />
        )}
        {row && !editor && (
          <article className="dictionary-detail" aria-label="선택한 사전 항목">
            <h3>
              {row.display_name ||
                row.preferred_name ||
                row.source_name ||
                row.content.preferred_name}
            </h3>
            <p>
              {kind === "concept"
                ? `공통 정의 ${labels[row.status]}`
                : labels[row.status]}
              {row.revision ? ` · 개정 ${row.revision}` : ""} ·{" "}
              {row.kind === "item_type" ? "물품 유형" : "특성"}
            </p>
            <p>{row.content.definition}</p>
            {kind !== "source" && (
              <dl>
                <dt>대표 이름</dt>
                <dd>{row.content.preferred_name}</dd>
                <dt>값 종류</dt>
                <dd>{row.content.value_kind || "해당 없음"}</dd>
                <dt>단위 정책</dt>
                <dd>
                  {row.content.canonical_unit || "없음"} ·{" "}
                  {row.content.allowed_units?.join(", ")}
                </dd>
                <dt>정의 근거</dt>
                <dd>
                  {row.content.references?.map((ref) => (
                    <p key={ref}>{ref}</p>
                  ))}
                </dd>
              </dl>
            )}
            {kind === "mapping" && (
              <>
                <p>
                  연결 정의: {row.concept_key} ·{" "}
                  {row.relation === "equivalent" ? "같은 의미" : "관련 의미"}
                </p>
                <p>
                  분류:{" "}
                  {row.classification_code ||
                    (row.scope_mode === "independent"
                      ? "분류 독립"
                      : "미분류 문맥")}{" "}
                  · {row.rationale}
                </p>
                {row.evidence?.map((e, i) => (
                  <blockquote key={i}>
                    {e.quote}
                    <small>
                      {e.document_id} · {e.locator}
                    </small>
                  </blockquote>
                ))}
              </>
            )}
            {row.ontology && (
              <p>
                온톨로지: {row.ontology.namespace} · {row.ontology.version}
              </p>
            )}
            {row.requires_review && (
              <p role="note">
                이전 온톨로지 버전의 연결입니다. 새 처리에는 재검토가
                필요합니다.
              </p>
            )}
            {historical && kind === "concept" && row.revision_id && (
              <OntologyDraftImport
                key={row.revision_id}
                revisionId={row.revision_id}
              />
            )}
            {kind === "source" && (
              <>
                {evidence.slice(0, 50).map((e, i) => (
                  <blockquote key={i}>
                    {e.quote}
                    <small>
                      {e.document_id} · {e.locator}
                    </small>
                  </blockquote>
                ))}
                <p>
                  원문 등록 방식: {row.approval_mode || "확인 필요"} ·{" "}
                  {row.approved_by || ""}
                </p>
                <button onClick={() => setEditor("mapping")}>
                  원문 표현 연결 제안
                </button>
              </>
            )}
            {kind === "mapping" &&
              !historical &&
              ["draft", "approved"].includes(row.status) && (
                <form
                  className="dictionary-form"
                  onSubmit={(e) => e.preventDefault()}
                >
                  <label>
                    검토 사유
                    <textarea
                      required
                      minLength={10}
                      maxLength={4000}
                      value={rationale}
                      onChange={(e) => setRationale(e.target.value)}
                    />
                  </label>
                  <div className="dictionary-actions">
                    {(row.status === "draft"
                      ? [
                          ["approve", "승인"],
                          ["reject", "거절"],
                        ]
                      : [["deprecate", "사용 중단"]]
                    ).map(([action, label]) => (
                      <button
                        key={action}
                        type="button"
                        disabled={busy || rationale.trim().length < 10}
                        onClick={() => decide(action)}
                      >
                        {label}
                      </button>
                    ))}
                  </div>
                </form>
              )}
            {detailError && <p role="alert">{detailError}</p>}
            <section>
              <h4>영향 문서</h4>
              <p>연결 근거로 조회된 {documents.length}건</p>
              {documents.slice(0, 25).map((d, i) => (
                <p key={i}>
                  {d.document_id} · {d.operation_id}
                </p>
              ))}
            </section>
            <section>
              <h4>검토 이력</h4>
              {events.length ? (
                events.map((e) => (
                  <p key={e.event_id}>
                    {e.action} · {e.actor} ·{" "}
                    {new Date(e.created_at).toLocaleString("ko-KR")}
                    <br />
                    {e.rationale || e.reason}
                  </p>
                ))
              ) : (
                <p>기록된 검토가 없습니다.</p>
              )}
            </section>
          </article>
        )}
      </SelectionCatalog>
    </div>
  );
}
