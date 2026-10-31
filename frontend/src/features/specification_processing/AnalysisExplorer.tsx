import { useEffect, useMemo, useRef, useState } from "react";

import {
  type ResultRecord as Row,
  resultRows as rows,
  resultLabel as label,
  resultRefs as refs,
  RelationResults,
  UnresolvedResults,
  unresolvedResults,
  normalizedResultValue,
} from "./document_results";
import "./document_results.css";

const kindNames: Record<string, string> = {
  product: "물품",
  material: "원재료·재질",
  equipment: "장비",
  software: "소프트웨어",
  activity: "작업",
  group: "묶음",
  document: "문서",
  unknown: "유형 미확정",
};
/** Only evidence-backed explicit composition forms the tree; other relations remain visible separately. */
export function composition(document: Row, mode = "composition") {
  const entities = rows(document.entities);
  const ids = new Set(entities.map((e) => String(e.id)));
  const physical = (id: unknown) => {
    const kind = entities.find((e) => e.id === id)?.kind;
    return (
      kind == null || ["product", "equipment", "group"].includes(String(kind))
    );
  };
  const software = (id: unknown) =>
    entities.find((e) => e.id === id)?.kind === "software";
  const candidates = rows(document.relations).filter(
    (r) =>
      (mode === "packaging"
        ? r.kind === "pack_unit_of"
        : ["component_of", "physical_part_of"].includes(String(r.kind))) &&
      ((physical(r.source_id) && physical(r.target_id)) ||
        (mode === "composition" &&
          r.kind === "component_of" &&
          software(r.source_id) &&
          software(r.target_id))) &&
      r.basis === "explicit" &&
      r.review_status !== "held" &&
      refs(r).length &&
      ids.has(String(r.source_id)) &&
      ids.has(String(r.target_id)) &&
      r.source_id !== r.target_id,
  );
  const parents = new Map<string, Set<string>>();
  for (const r of candidates) {
    const id = String(r.source_id);
    parents.set(id, new Set([...(parents.get(id) || []), String(r.target_id)]));
  }
  const reaches = (start: string, target: string) => {
    const pending = [start],
      seen = new Set<string>();
    while (pending.length) {
      const id = pending.pop()!;
      if (id === target) return true;
      if (seen.has(id)) continue;
      seen.add(id);
      pending.push(...(parents.get(id) || []));
    }
    return false;
  };
  const children = new Map<string, string[]>(),
    attached = new Set<string>();
  for (const [child, targets] of parents) {
    if (targets.size !== 1) continue;
    const parent = [...targets][0];
    if (reaches(parent, child)) continue;
    children.set(parent, [...(children.get(parent) || []), child]);
    attached.add(child);
  }
  return {
    entities,
    children,
    roots: entities.filter(
      (e) => !attached.has(String(e.id)) && children.has(String(e.id)),
    ),
    unclassified: entities.filter(
      (e) => !attached.has(String(e.id)) && !children.has(String(e.id)),
    ),
  };
}

export type MappingStatus = "missing" | "loading" | "available" | "error";
export function AnalysisExplorer({
  value,
  normalization,
  mappingStatus = "missing",
  documentId = "",
  onDocumentChange,
  initialAttributeId = "",
}: {
  value: Row;
  normalization?: Row | null;
  mappingStatus?: MappingStatus;
  documentId?: string;
  onDocumentChange?: (id: string) => void;
  initialAttributeId?: string;
}) {
  const available = rows(value.documents);
  const documents = [...available, ...rows(value.unavailable_documents)];
  const [selectedIndex, setDocumentIndex] = useState(0);
  const requestedIndex = documents.findIndex(
    (item) => item.document_id === documentId,
  );
  const documentIndex =
    requestedIndex >= 0
      ? requestedIndex
      : Math.min(selectedIndex, Math.max(0, documents.length - 1));
  const document = documents[documentIndex];
  if (!document)
    return (
      <div>
        <p>이 실행에는 규격서별 처리 결과가 없습니다.</p>
      </div>
    );
  return (
    <section className="analysis-explorer">
      {documents.length > 1 && (
        <label className="analysis-document">
          규격서 선택
          <select
            value={documentIndex}
            onChange={(event) => {
              const index = Number(event.target.value);
              setDocumentIndex(index);
              onDocumentChange?.(String(documents[index]?.document_id || ""));
            }}
          >
            {documents.map((d, i) => (
              <option key={i} value={i}>
                {label(
                  (d.source as Row | undefined)?.filename ||
                    (d.source as Row | undefined)?.original_name ||
                    d.document_id ||
                    `문서 ${i + 1}`,
                )}
              </option>
            ))}
          </select>
        </label>
      )}
      <p className="result-execution-note">
        해당 실행의 최종 처리 결과입니다. 문서에 남은 미해결 항목과 원문 근거를
        함께 표시합니다.
      </p>
      {documentIndex >= available.length ? (
        <section className="result-document-failure" role="status">
          <h3>이 규격서의 구조화 결과가 없습니다</h3>
          <p>
            처리 상태:{" "}
            {label(
              document.status || document.extraction_status || "처리하지 못함",
            )}
          </p>
          <p>
            {label(
              document.reason ||
                document.error_code ||
                document.failure_code ||
                "문서별 실행 정보에서 처리 원인을 확인하세요.",
            )}
          </p>
        </section>
      ) : (
        <DocumentAnalysis
          key={`${documentIndex}-${String(document.document_id)}`}
          document={document}
          initialAttributeId={initialAttributeId}
          normalization={normalization}
          mappingStatus={mappingStatus}
        />
      )}
    </section>
  );
}
function DocumentAnalysis({
  document,
  initialAttributeId = "",
  normalization,
  mappingStatus,
}: {
  document: Row;
  initialAttributeId?: string;
  normalization?: Row | null;
  mappingStatus: MappingStatus;
}) {
  const [navigation, setNavigation] = useState(() =>
    composition(document, "composition").children.size ? "composition" : "list",
  );
  const [kindFilter, setKindFilter] = useState("all");
  const graph = useMemo(
    () => composition(document, navigation),
    [document, navigation],
  );
  const initialAttribute = rows(document.attributes).find(
    (a) => a.id === initialAttributeId,
  );
  const [treeFocus, setTreeFocus] = useState("");
  const [selected, setSelected] = useState(
    String(
      (Array.isArray(initialAttribute?.subject_ids) &&
        initialAttribute.subject_ids[0]) ||
        (Array.isArray(document.inventory_ids) &&
          document.inventory_ids.find((id) =>
            rows(document.attributes).some(
              (a) => Array.isArray(a.subject_ids) && a.subject_ids.includes(id),
            ),
          )) ||
        graph.entities.find((entity) =>
          rows(document.attributes).some(
            (a) =>
              Array.isArray(a.subject_ids) && a.subject_ids.includes(entity.id),
          ),
        )?.id ||
        (Array.isArray(document.inventory_ids) && document.inventory_ids[0]) ||
        graph.entities[0]?.id ||
        "",
    ),
  );
  const [query, setQuery] = useState("");
  const [closed, setClosed] = useState<Set<string>>(new Set());
  const [focused, setFocused] = useState(
    initialAttribute ? refs(initialAttribute)[0] || "" : "",
  );
  const [sourceOpen, setSourceOpen] = useState(!!initialAttribute);
  const [selectedAttribute, setSelectedAttribute] = useState("");
  const [sourceReferences, setSourceReferences] = useState<string[]>(
    initialAttribute ? refs(initialAttribute) : [],
  );
  const [sourceTitle, setSourceTitle] = useState("");
  const [relationScope, setRelationScope] = useState("selected");
  const [detailTab, setDetailTab] = useState("attributes");
  const [view, setView] = useState(
    mappingStatus === "available" ? "mapping" : "source",
  );
  const [filter, setFilter] = useState("all");
  const mappings = rows(normalization?.attributes).filter(
    (a) => a.document_id === document.document_id,
  );
  const mappingFor = (a: Row) =>
    mappings.find((m) => a.id != null && m.attribute_id === a.id);
  const mappingLabel = (a: Row) => {
    if (mappingStatus === "loading") return "조회 중";
    if (mappingStatus === "error") return "조회 실패";
    if (mappingStatus !== "available") return "결과 없음";
    const mapping = mappingFor(a);
    if (!mapping) return "기록 없음";
    if (mapping.status === "applied" && rows(mapping.facts).length)
      return "연결됨";
    if (
      ["automatically_deferred", "pending_definition"].includes(
        String(mapping.status),
      )
    )
      return "보류·미매핑";
    return "상태 미확인";
  };
  const sourcePanel = useRef<HTMLElement>(null);
  useEffect(() => {
    if (focused && window.innerWidth <= 1100)
      sourcePanel.current?.scrollIntoView?.({
        block: "nearest",
        behavior: "smooth",
      });
  }, [focused]);
  const [mobileDetail, setMobileDetail] = useState(false);
  const entity = graph.entities.find((e) => String(e.id) === selected);
  const attributes = rows(document.attributes).filter(
    (a) => Array.isArray(a.subject_ids) && a.subject_ids.includes(selected),
  );
  const quantities = rows(document.declared_quantities).filter(
    (q) => q.entity_id === selected,
  );
  const relations = rows(document.relations).filter(
    (r) => r.source_id === selected || r.target_id === selected,
  );
  const unresolved = unresolvedResults(
    document,
    mappings,
    mappingStatus === "available",
  );
  const inPurchaseScope = (e: Row) =>
    (Array.isArray(document.inventory_ids) &&
      document.inventory_ids.includes(e.id)) ||
    (Array.isArray(e.document_roles) &&
      (e.document_roles.includes("supply_target") ||
        (e.document_roles.includes("procurement_scope") &&
          ["product", "equipment", "software"].includes(String(e.kind)))));
  const matches = (e: Row) =>
    [
      label(e.name),
      label(e.name_raw),
      ...rows(e.aliases).map((a) => label(a.name)),
    ]
      .join(" ")
      .toLowerCase()
      .includes(query.toLowerCase()) &&
    (kindFilter === "all" ||
      (kindFilter === "goods"
        ? !["activity", "document"].includes(String(e.kind))
        : kindFilter === "purchase"
          ? inPurchaseScope(e)
          : String(e.kind ?? "unknown") === kindFilter));
  const passageRoles = (
    (document.parsed_document as Row | undefined)?.document_assessment as
      | Row
      | undefined
  )?.node_roles as Row | undefined;
  const isOther = (r: Row) =>
    r.category === "other" ||
    r.observation_type === "obligation" ||
    refs(r).some((id) =>
      ["general_requirement", "delivery_requirement"].includes(
        String(passageRoles?.[id]),
      ),
    );
  const clauses = rows(document.requirements).filter(
    (r) =>
      r.observation_type === "source_clause" &&
      !isOther(r) &&
      Array.isArray(r.subject_ids) &&
      r.subject_ids.includes(selected),
  );
  const otherRows = rows(document.requirements).filter(isOther);
  const sourceClauseNodes = new Set(
    otherRows
      .filter((r) => r.observation_type === "source_clause")
      .flatMap(refs),
  );
  const otherRequirements = otherRows.filter(
    (r) =>
      r.observation_type !== "obligation" ||
      !refs(r).some((id) => sourceClauseNodes.has(id)),
  );
  const ancestry: Row[] = [];
  let ancestor = selected;
  const parentOf = new Map(
    (navigation === "list" ? [] : [...graph.children]).flatMap(
      ([parent, children]) => children.map((child) => [child, parent] as const),
    ),
  );
  while (ancestor) {
    const item = graph.entities.find((e) => String(e.id) === ancestor);
    if (item) ancestry.unshift(item);
    ancestor = parentOf.get(ancestor) || "";
  }
  const nodes = rows((document.parsed_document as Row | undefined)?.nodes);
  const node = nodes.find((n) => n.node_id === focused);
  useEffect(() => {
    setFocused("");
    setSourceOpen(false);
    setSelectedAttribute("");
  }, [selected]);
  const missingEvidence = attributes.filter(
    (a) =>
      !refs(a).some((id) =>
        nodes.some((n) => n.node_id === id && String(n.text || "").trim()),
      ),
  );
  const unmapped = attributes.filter((a) => mappingLabel(a) === "보류·미매핑");
  const shownAttributes =
    filter === "evidence"
      ? missingEvidence
      : filter === "unmapped"
        ? unmapped
        : attributes;
  const openAttribute = (a: Row, index: number) => {
    setSelectedAttribute(String(a.id ?? attributes.indexOf(a) ?? index));
    setSourceTitle(
      label(a.property_raw || a.property_name || "원문 명칭 미기재"),
    );
    setSourceReferences(refs(a));
    setFocused(refs(a)[0] || "");
    setSourceOpen(true);
  };
  const choose = (id: string) => {
    setSelected(id);
    setRelationScope("selected");
    setMobileDetail(true);
  };
  const nodeButton = (item: Row, attribute = false) =>
    refs(item).map((id) => (
      <button
        className="operations-link"
        type="button"
        key={id}
        onClick={(event) => {
          event.stopPropagation();
          if (attribute) openAttribute(item, attributes.indexOf(item));
          else {
            setSelectedAttribute("");
            setSourceTitle(
              label(item.name || item.text || item.kind || "원문 근거"),
            );
          }
          setSourceReferences(refs(item));
          setFocused(id);
          setSourceOpen(true);
        }}
      >
        원문 근거 {id}
      </button>
    ));
  const visible: { id: string; depth: number }[] = [];
  const pending = graph.roots
    .map((e) => ({ id: String(e.id), depth: 0 }))
    .reverse();
  while (pending.length) {
    const next = pending.pop()!;
    visible.push(next);
    if (!closed.has(next.id))
      pending.push(
        ...(graph.children.get(next.id) || [])
          .map((id) => ({ id, depth: next.depth + 1 }))
          .reverse(),
      );
  }
  const treeCandidates =
    navigation === "list" || query || !["all", "goods"].includes(kindFilter)
      ? graph.entities.filter(matches).map((e) => String(e.id))
      : [
          ...visible.map((e) => e.id),
          ...graph.unclassified.map((e) => String(e.id)),
        ];
  const itemRow = (id: string, depth = 0) => {
    const item = graph.entities.find((e) => String(e.id) === id)!;
    const children =
      navigation === "list" || query || !["all", "goods"].includes(kindFilter)
        ? undefined
        : graph.children.get(id);
    return (
      <div
        key={id}
        className="analysis-tree-row"
        style={{ paddingLeft: `${Math.min(depth, 8) * 14}px` }}
      >
        {children ? (
          <button
            type="button"
            className="analysis-expand"
            aria-label={`${label(item.name)} ${closed.has(id) ? "펼치기" : "접기"}`}
            aria-expanded={!closed.has(id)}
            onClick={() =>
              setClosed((previous) => {
                const next = new Set(previous);
                next.has(id) ? next.delete(id) : next.add(id);
                return next;
              })
            }
          >
            {closed.has(id) ? "▸" : "▾"}
          </button>
        ) : (
          <span className="analysis-expand" />
        )}
        <button
          type="button"
          aria-pressed={selected === id}
          role="treeitem"
          aria-selected={selected === id}
          aria-level={depth + 1}
          aria-expanded={children ? !closed.has(id) : undefined}
          tabIndex={
            id ===
            (treeCandidates.includes(treeFocus) ? treeFocus : treeCandidates[0])
              ? 0
              : -1
          }
          onFocus={() => setTreeFocus(id)}
          onKeyDown={(event) => {
            const buttons = Array.from(
              event.currentTarget
                .closest('[role="tree"]')
                ?.querySelectorAll<HTMLButtonElement>(".analysis-item") || [],
            );
            const index = buttons.indexOf(event.currentTarget);
            const move =
              event.key === "ArrowDown"
                ? index + 1
                : event.key === "ArrowUp"
                  ? index - 1
                  : event.key === "Home"
                    ? 0
                    : event.key === "End"
                      ? buttons.length - 1
                      : -1;
            if (move >= 0 && buttons[move]) {
              event.preventDefault();
              buttons[move].focus();
            }
            if (children && ["ArrowLeft", "ArrowRight"].includes(event.key)) {
              event.preventDefault();
              setClosed((previous) => {
                const next = new Set(previous);
                event.key === "ArrowLeft" ? next.add(id) : next.delete(id);
                return next;
              });
            }
          }}
          className="analysis-item"
          onClick={() => choose(id)}
        >
          {label(item.name || id)}
          <small>
            {
              rows(document.attributes).filter(
                (a) =>
                  Array.isArray(a.subject_ids) && a.subject_ids.includes(id),
              ).length
            }
            개 속성
            {kindNames[String(item.kind)]
              ? ` · ${kindNames[String(item.kind)]}`
              : ""}
          </small>
        </button>
      </div>
    );
  };
  return (
    <>
      <div className="analysis-view-toolbar">
        <div role="group" aria-label="분석 결과 보기">
          <button
            aria-pressed={view === "source"}
            onClick={() => setView("source")}
          >
            엔티티·관계·속성
          </button>
          <button
            aria-pressed={view === "mapping"}
            onClick={() => setView("mapping")}
          >
            표준 적용 결과
          </button>
        </div>
        <span className="analysis-status">
          {document.extraction_status === "partial"
            ? "일부 추출 · 미해결 항목 있음"
            : "실행 산출물"}
        </span>
      </div>
      {view === "mapping" && (
        <p className="analysis-mapping-notice" role="status">
          {mappingStatus === "loading"
            ? "표준 매핑 결과를 조회하고 있습니다."
            : mappingStatus === "error"
              ? "표준 매핑 결과를 조회하지 못했습니다. 미매핑으로 판단하지 않습니다."
              : mappingStatus === "missing"
                ? "이 실행에는 표준 매핑 결과가 없습니다."
                : `적용 표준: ${label(normalization?.standard_version)} · ${normalization?.artifact_kind === "goods_normalized_observations" && normalization?.profile_revision_id ? "프로파일 표준 적용" : "추출용 표준 초안"}`}
        </p>
      )}
      <div className="result-document-summary" aria-label="규격서 결과 요약">
        <span>
          엔티티 <strong>{graph.entities.length}</strong>
        </span>
        <button
          onClick={() => {
            setDetailTab("relations");
            setRelationScope("document");
            setMobileDetail(true);
          }}
        >
          관계 <strong>{rows(document.relations).length}</strong>
        </button>
        <span>
          속성 <strong>{rows(document.attributes).length}</strong>
        </span>
        <button
          onClick={() => {
            setDetailTab("unresolved");
            setMobileDetail(true);
          }}
        >
          미해결 항목 <strong>{unresolved.length}</strong>
        </button>
        {mappingStatus === "available" && (
          <span>
            표준 미매핑{" "}
            <strong>
              {
                mappings.filter((m) =>
                  ["automatically_deferred", "pending_definition"].includes(
                    String(m.status),
                  ),
                ).length
              }
            </strong>
          </span>
        )}
      </div>
      <div
        className={`analysis-layout ${sourceOpen ? "has-source" : ""}`}
        data-mobile-detail={mobileDetail}
        data-view={view}
      >
        <aside className="analysis-tree" aria-label="분석 대상 탐색">
          <h3>
            엔티티 <small>{graph.entities.length}개 대상</small>
          </h3>
          <input
            aria-label="분석 대상 검색"
            placeholder="대상 이름 검색"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <label>
            대상 유형
            <select
              aria-label="대상 유형"
              value={kindFilter}
              onChange={(event) => setKindFilter(event.target.value)}
            >
              <option value="goods">물품·구성</option>
              <option value="all">전체</option>
              <option value="purchase">구매 범위 항목</option>
              {Object.entries(kindNames).map(([key, name]) => (
                <option key={key} value={key}>
                  {name}
                </option>
              ))}
            </select>
          </label>
          <label>
            탐색 방식
            <select
              aria-label="탐색 방식"
              value={navigation}
              onChange={(event) => {
                setNavigation(event.target.value);
                setClosed(new Set());
              }}
            >
              <option value="list">대상 목록</option>
              <option value="composition">구성 관계</option>
              <option value="packaging">포장 단위 관계</option>
            </select>
          </label>
          {navigation !== "list" && (
            <div className="analysis-tree-tools">
              <button onClick={() => setClosed(new Set())}>전체 펼치기</button>
              <button onClick={() => setClosed(new Set(graph.children.keys()))}>
                전체 접기
              </button>
            </div>
          )}
          <div role="tree" aria-label="구성 대상">
            {navigation === "list" ||
            query ||
            !["all", "goods"].includes(kindFilter) ? (
              <>
                <h4>{query ? "검색 결과" : "대상 목록"}</h4>
                {graph.entities
                  .filter(matches)
                  .map((e) => itemRow(String(e.id)))}
                {!graph.entities.some(matches) && (
                  <p>일치하는 대상이 없습니다.</p>
                )}
              </>
            ) : (
              <>
                {!!visible.length && (
                  <h4>
                    {navigation === "packaging"
                      ? "포장 단위 관계"
                      : "구성 관계"}
                  </h4>
                )}
                {visible.map(({ id, depth }) => itemRow(id, depth))}
                {!graph.roots.length && (
                  <p className="operations-note">
                    확인된 구성 계층이 없습니다.
                  </p>
                )}
                {!!graph.unclassified.length && (
                  <>
                    <h4>
                      이 계층에 포함되지 않은 대상 · {graph.unclassified.length}
                    </h4>
                    {graph.unclassified.map((e) => itemRow(String(e.id)))}
                  </>
                )}
              </>
            )}
          </div>
        </aside>
        <section className="analysis-properties" aria-label="분석 대상 상세">
          <button
            type="button"
            className="analysis-mobile-back operations-link"
            onClick={() => setMobileDetail(false)}
          >
            ← 분석 대상 목록
          </button>
          <div
            className="result-detail-tabs"
            role="group"
            aria-label="결과 상세 보기"
          >
            <button
              aria-pressed={detailTab === "attributes"}
              onClick={() => setDetailTab("attributes")}
            >
              속성
            </button>
            <button
              aria-pressed={detailTab === "relations"}
              onClick={() => setDetailTab("relations")}
            >
              관계
            </button>
            <button
              aria-pressed={detailTab === "unresolved"}
              onClick={() => setDetailTab("unresolved")}
            >
              미해결 항목
            </button>
          </div>
          {detailTab === "unresolved" && (
            <UnresolvedResults
              items={unresolved}
              entities={graph.entities}
              onChoose={(id) => {
                choose(id);
                setDetailTab("relations");
              }}
              onAttribute={(attribute) => {
                setSelectedAttribute("");
                setSourceTitle(
                  label(attribute.property_raw || attribute.property_key),
                );
                setSourceReferences(refs(attribute));
                setFocused(refs(attribute)[0] || "");
                setSourceOpen(true);
              }}
              evidence={(record) => nodeButton(record)}
            />
          )}
          {entity && detailTab !== "unresolved" ? (
            <>
              <nav
                className="analysis-breadcrumb"
                aria-label="선택한 관계 경로"
              >
                {ancestry.map((item) => (
                  <button
                    key={String(item.id)}
                    onClick={() => choose(String(item.id))}
                  >
                    {label(item.name)}
                  </button>
                ))}
              </nav>
              <h3>{label(entity.name)}</h3>
              {(!!entity.name_raw ||
                rows(entity.aliases).length > 0 ||
                rows(entity.descriptions).length > 0) && (
                <details>
                  <summary>원문 명칭·다른 표현</summary>
                  {!!entity.name_raw && (
                    <p>원문 명칭: {label(entity.name_raw)}</p>
                  )}
                  {rows(entity.aliases).map((a, i) => (
                    <div key={i}>
                      {label(a.name)} {nodeButton(a)}
                    </div>
                  ))}
                  {rows(entity.descriptions).map((d, i) => (
                    <div key={i}>
                      {label(d.text)} {nodeButton(d)}
                    </div>
                  ))}
                </details>
              )}
              <p className="operations-note">
                {kindNames[String(entity.kind)] || label(entity.kind)} · 추출
                결과
              </p>
              <div className="observation-evidence-links">
                {nodeButton(entity)}
              </div>
              {detailTab === "attributes" && (
                <>
                  {!!quantities.length && (
                    <div className="analysis-quantities">
                      {quantities.map((q, i) => (
                        <div key={i}>
                          수량:{" "}
                          <strong>
                            {label(q.value_raw)}{" "}
                            {q.unit_raw ? label(q.unit_raw) : ""}
                          </strong>
                        </div>
                      ))}
                    </div>
                  )}
                  <div className="analysis-attribute-toolbar">
                    <h4>문서 속성 · {attributes.length}</h4>
                    <label>
                      속성 필터{" "}
                      <select
                        aria-label="속성 필터"
                        value={filter}
                        onChange={(e) => setFilter(e.target.value)}
                      >
                        <option value="all">전체 ({attributes.length})</option>
                        <option value="evidence">
                          근거 누락 ({missingEvidence.length})
                        </option>
                        <option
                          value="unmapped"
                          disabled={mappingStatus !== "available"}
                        >
                          보류·미매핑 (
                          {mappingStatus === "available"
                            ? unmapped.length
                            : "—"}
                          )
                        </option>
                      </select>
                    </label>
                  </div>
                  <div className="page-table-wrap">
                    <table className="page-table">
                      <thead>
                        <tr>
                          <th>문서 속성명</th>
                          <th>문서 값</th>
                          <th>단위</th>
                          {view === "mapping" && (
                            <>
                              <th>연결된 표준 식별자</th>
                              <th>매핑 상태</th>
                            </>
                          )}
                          <th>원문 근거</th>
                        </tr>
                      </thead>
                      <tbody>
                        {shownAttributes.map((a, i) => (
                          <tr
                            key={String(a.id ?? i)}
                            tabIndex={0}
                            aria-selected={
                              selectedAttribute ===
                              String(a.id ?? attributes.indexOf(a))
                            }
                            onClick={() => openAttribute(a, i)}
                            onKeyDown={(event) => {
                              if (event.target !== event.currentTarget) return;
                              if (event.key === "Enter" || event.key === " ") {
                                event.preventDefault();
                                openAttribute(a, i);
                              }
                            }}
                          >
                            <td>
                              {label(
                                a.property_raw ||
                                  a.property_name ||
                                  a.name ||
                                  "원문 명칭 미기재",
                              )}
                              {!!a.property_key && (
                                <details
                                  className="analysis-internal-key"
                                  onClick={(event) => event.stopPropagation()}
                                >
                                  <summary>내부 식별자</summary>
                                  <code>{label(a.property_key)}</code>
                                </details>
                              )}
                            </td>
                            <td>
                              {a.operator_raw
                                ? `${label(a.operator_raw)} `
                                : ""}
                              {label(a.value_raw ?? a.value ?? a.raw_value)}
                              {Array.isArray(a.qualifiers_raw) &&
                                a.qualifiers_raw.length > 0 && (
                                  <p className="operations-note">
                                    조건:{" "}
                                    {a.qualifiers_raw.map(label).join(" · ")}
                                  </p>
                                )}
                            </td>
                            <td>{label(a.unit_raw)}</td>
                            {view === "mapping" && (
                              <>
                                <td>
                                  {rows(mappingFor(a)?.facts).map(
                                    (fact, index) => (
                                      <div key={index}>
                                        {label(
                                          fact.property_label ||
                                            fact.property_stable_key ||
                                            fact.property_id ||
                                            fact.property_concept_id,
                                        )}
                                        <p className="analysis-normalized-value">
                                          {normalizedResultValue(fact)}
                                          <small>
                                            {[
                                              fact.operator_raw ||
                                                fact.operator,
                                              fact.role,
                                              fact.semantic_scope,
                                              ...(Array.isArray(
                                                fact.qualifiers_raw,
                                              )
                                                ? fact.qualifiers_raw
                                                : []),
                                            ]
                                              .filter(Boolean)
                                              .map(label)
                                              .join(" · ")}
                                          </small>
                                        </p>
                                      </div>
                                    ),
                                  )}
                                  {!rows(mappingFor(a)?.facts).length && "—"}
                                </td>
                                <td>
                                  <span className="analysis-status">
                                    {mappingLabel(a)}
                                  </span>
                                  {mappingFor(a)?.reason ? (
                                    <details
                                      onClick={(event) =>
                                        event.stopPropagation()
                                      }
                                    >
                                      <summary>보류 사유</summary>
                                      <code>
                                        {label(mappingFor(a)?.reason)}
                                      </code>
                                    </details>
                                  ) : null}
                                </td>
                              </>
                            )}
                            <td>
                              {refs(a).length ? (
                                nodeButton(a, true)
                              ) : (
                                <span className="operations-note">
                                  근거 없음
                                </span>
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  {!!attributes.length && !shownAttributes.length && (
                    <p className="operations-note">
                      이 필터에 해당하는 속성이 없습니다.
                    </p>
                  )}
                  {!attributes.length && (
                    <p className="operations-note">
                      이 대상에 연결된 속성이 없습니다. 다른 대상을 선택하거나
                      대상 미지정 속성을 확인하세요.
                    </p>
                  )}
                </>
              )}
              {detailTab === "relations" && (
                <section aria-label="선택한 엔티티 관계">
                  <h4>
                    연결 관계 ·{" "}
                    {relationScope === "document"
                      ? rows(document.relations).length
                      : relations.length}
                  </h4>
                  <label>
                    관계 범위{" "}
                    <select
                      aria-label="관계 범위"
                      value={relationScope}
                      onChange={(event) => setRelationScope(event.target.value)}
                    >
                      <option value="selected">선택한 엔티티</option>
                      <option value="document">규격서 전체</option>
                    </select>
                  </label>
                  <RelationResults
                    relations={
                      relationScope === "document"
                        ? rows(document.relations)
                        : relations
                    }
                    entities={graph.entities}
                    onChoose={choose}
                    evidence={(record) => nodeButton(record)}
                  />
                </section>
              )}
              {detailTab === "attributes" && !!clauses.length && (
                <details>
                  <summary>대상별 원문 요구조건 · {clauses.length}</summary>
                  <p>선택한 물품의 규격 원문입니다.</p>
                  {clauses.map((clause, index) => (
                    <div key={String(clause.id ?? index)}>
                      <p>{label(clause.text)}</p>
                      {nodeButton(clause)}
                    </div>
                  ))}
                </details>
              )}
            </>
          ) : detailTab !== "unresolved" ? (
            <p>표시할 엔티티가 없습니다.</p>
          ) : null}
          {detailTab === "attributes" && !!otherRequirements.length && (
            <details>
              <summary>기타 요구사항 · {otherRequirements.length}</summary>
              <p>납품·설치·보증·제출·일반 준수사항의 원문과 근거입니다.</p>
              {otherRequirements.map((clause, index) => (
                <div key={String(clause.id ?? index)}>
                  <p>{label(clause.text)}</p>
                  {nodeButton(clause)}
                </div>
              ))}
            </details>
          )}
        </section>
        <section
          ref={sourcePanel}
          className="analysis-source"
          aria-label={sourceOpen ? "선택한 원문 근거" : "원문 근거"}
          data-open={sourceOpen}
        >
          <div className="analysis-source-heading">
            <h4>원문 근거</h4>
            {sourceOpen && (
              <button
                className="operations-link"
                onClick={() => {
                  setSourceOpen(false);
                  setSelectedAttribute("");
                }}
              >
                근거 닫기
              </button>
            )}
          </div>
          {!sourceOpen ? (
            <p className="operations-note">
              엔티티·관계·속성의 원문 근거를 선택하면 해당 위치와 내용을
              표시합니다.
            </p>
          ) : (
            <>
              <p>{sourceTitle}</p>
              <div className="analysis-source-tabs">
                {sourceReferences.map((id) => (
                  <button
                    key={id}
                    aria-pressed={id === focused}
                    onClick={() => setFocused(id)}
                  >
                    {id}
                  </button>
                ))}
              </div>
              {node ? (
                <article className="evidence-node is-selected">
                  <small>
                    {focused}
                    {node.page != null ? ` · ${label(node.page)}쪽` : ""}
                  </small>
                  <p>{label(node.text)}</p>
                </article>
              ) : (
                <p className="operations-note">
                  {focused
                    ? "이 산출물에서 해당 원문 노드를 찾지 못했습니다."
                    : "이 속성에는 원문 근거 참조가 없습니다."}
                </p>
              )}
            </>
          )}
        </section>
      </div>
    </>
  );
}
