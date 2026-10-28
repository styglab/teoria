import { useEffect, useMemo, useRef, useState } from "react";

type Row = Record<string, unknown>;
const rows = (value: unknown): Row[] =>
  Array.isArray(value)
    ? (value.filter((v) => v && typeof v === "object") as Row[])
    : [];
const label = (value: unknown) =>
  value == null
    ? "—"
    : typeof value === "object"
      ? JSON.stringify(value)
      : String(value);
const kindNames: Record<string, string> = {
  equipment: "장비",
  software: "소프트웨어",
  activity: "작업",
  group: "묶음",
  document: "문서",
  unknown: "유형 미확정",
};
const relationNames: Record<string, string> = {
  component_of: "구성품",
  physical_part_of: "내부 부품",
  specification_for: "상세 규격 대상",
  in_procurement_scope: "구매 범위",
  service_for: "작업 대상",
  compatible_with: "호환",
  sends_data_to: "데이터 전달",
  same_target_as: "동일 대상 후보",
};
function refs(item: Row): string[] {
  const evidence = item.evidence;
  if (Array.isArray(evidence))
    return [...new Set(evidence.map((e) => String(e.node_id)).filter(Boolean))];
  const reference = evidence as Row | undefined;
  const ids = Array.isArray(reference?.source_node_ids)
    ? reference.source_node_ids.map(String)
    : [];
  if (reference?.node_id) ids.push(String(reference.node_id));
  return [...new Set(ids)];
}

/** Only evidence-backed explicit composition forms the tree; other relations remain visible separately. */
export function composition(document: Row) {
  const entities = rows(document.entities);
  const ids = new Set(entities.map((e) => String(e.id)));
  const candidates = rows(document.relations).filter(
    (r) =>
      ["component_of", "physical_part_of"].includes(String(r.kind)) &&
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
}: {
  value: Row;
  normalization?: Row | null;
  mappingStatus?: MappingStatus;
}) {
  const documents = rows(value.documents);
  const [documentIndex, setDocumentIndex] = useState(0);
  const [showRaw, setShowRaw] = useState(false);
  const document = documents[documentIndex] || documents[0];
  if (!document)
    return (
      <div>
        <p>이 산출물에는 구성품 분석 데이터가 없습니다.</p>
        <details>
          <summary>산출물 원문</summary>
          <pre>{JSON.stringify(value, null, 2)}</pre>
        </details>
      </div>
    );
  return (
    <section className="analysis-explorer">
      <label className="analysis-document">
        분석 문서
        <select
          value={documentIndex}
          onChange={(e) => setDocumentIndex(Number(e.target.value))}
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
      <DocumentAnalysis
        key={`${documentIndex}-${String(document.document_id)}`}
        document={document}
        normalization={normalization}
        mappingStatus={mappingStatus}
      />
      <details onToggle={(event) => setShowRaw(event.currentTarget.open)}>
        <summary>전체 JSON 산출물</summary>
        {showRaw && <pre>{JSON.stringify(value, null, 2)}</pre>}
      </details>
    </section>
  );
}
function DocumentAnalysis({
  document,
  normalization,
  mappingStatus,
}: {
  document: Row;
  normalization?: Row | null;
  mappingStatus: MappingStatus;
}) {
  const graph = useMemo(() => composition(document), [document]);
  const [selected, setSelected] = useState(
    String(graph.roots[0]?.id || graph.unclassified[0]?.id || ""),
  );
  const [query, setQuery] = useState("");
  const [closed, setClosed] = useState<Set<string>>(new Set());
  const [focused, setFocused] = useState("");
  const [sourceOpen, setSourceOpen] = useState(false);
  const [selectedAttribute, setSelectedAttribute] = useState("");
  const [sourceTitle, setSourceTitle] = useState("");
  const [view, setView] = useState("source");
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
  const unassigned = rows(document.attributes).filter(
    (a) =>
      !Array.isArray(a.subject_ids) ||
      !a.subject_ids.some((id) => graph.entities.some((e) => e.id === id)),
  );
  const quantities = rows(document.declared_quantities).filter(
    (q) => q.entity_id === selected,
  );
  const relations = rows(document.relations).filter(
    (r) => r.source_id === selected || r.target_id === selected,
  );
  const held = rows(document.held_relations);
  const ancestry: Row[] = [];
  let ancestor = selected;
  const parentOf = new Map(
    [...graph.children].flatMap(([parent, children]) =>
      children.map((child) => [child, parent] as const),
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
    setFocused(refs(a)[0] || "");
    setSourceOpen(true);
  };
  const choose = (id: string) => {
    setSelected(id);
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
            setSourceTitle(label(item.name || "연결 관계"));
          }
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
  const itemRow = (id: string, depth = 0) => {
    const item = graph.entities.find((e) => String(e.id) === id)!;
    const children = graph.children.get(id);
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
            문서 분석 결과
          </button>
          <button
            aria-pressed={view === "mapping"}
            onClick={() => setView("mapping")}
          >
            표준 매핑 비교
          </button>
        </div>
        <span className="analysis-status">AI 추출 · 검토 전</span>
      </div>
      {view === "mapping" && (
        <p className="analysis-mapping-notice" role="status">
          {mappingStatus === "loading"
            ? "표준 매핑 결과를 조회하고 있습니다."
            : mappingStatus === "error"
              ? "표준 매핑 결과를 조회하지 못했습니다. 미매핑으로 판단하지 않습니다."
              : mappingStatus === "missing"
                ? "이 실행에는 표준 매핑 결과가 없습니다."
                : `적용 표준: ${label(normalization?.standard_version)} · 자동 매핑 결과이며 사람의 검토·승인 상태를 나타내지 않습니다.`}
        </p>
      )}
      <div
        className={`analysis-layout ${sourceOpen ? "has-source" : ""}`}
        data-mobile-detail={mobileDetail}
        data-view={view}
      >
        <aside className="analysis-tree" aria-label="구성품 탐색">
          <h3>
            구성품 구조 <small>{graph.entities.length}개 대상</small>
          </h3>
          <input
            aria-label="구성품 검색"
            placeholder="구성품 이름 검색"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <div className="analysis-tree-tools">
            <button onClick={() => setClosed(new Set())}>전체 펼치기</button>
            <button onClick={() => setClosed(new Set(graph.children.keys()))}>
              전체 접기
            </button>
          </div>
          {query ? (
            <>
              <h4>검색 결과</h4>
              {graph.entities
                .filter((e) =>
                  label(e.name).toLowerCase().includes(query.toLowerCase()),
                )
                .map((e) => itemRow(String(e.id)))}
              {!graph.entities.some((e) =>
                label(e.name).toLowerCase().includes(query.toLowerCase()),
              ) && <p>일치하는 구성품이 없습니다.</p>}
            </>
          ) : (
            <>
              {visible.map(({ id, depth }) => itemRow(id, depth))}
              {!graph.roots.length && (
                <p className="operations-note">확인된 구성 계층이 없습니다.</p>
              )}
              {!!graph.unclassified.length && (
                <>
                  <h4>미분류 항목 · {graph.unclassified.length}</h4>
                  <p className="operations-note">
                    구성 관계가 확인되지 않은 구매 대상·작업·문서 등을
                    포함합니다.
                  </p>
                  {graph.unclassified.map((e) => itemRow(String(e.id)))}
                </>
              )}
            </>
          )}
        </aside>
        <section className="analysis-properties" aria-label="구성품 상세">
          <button
            type="button"
            className="analysis-mobile-back operations-link"
            onClick={() => setMobileDetail(false)}
          >
            ← 구성품 목록
          </button>
          {entity ? (
            <>
              <nav className="analysis-breadcrumb" aria-label="구성품 경로">
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
              <p className="operations-note">
                {kindNames[String(entity.kind)] || label(entity.kind)} · 검토 전
                관찰
              </p>
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
              <div className="observation-evidence-links">
                {nodeButton(entity)}
              </div>
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
                      {mappingStatus === "available" ? unmapped.length : "—"})
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
                          {a.operator_raw ? `${label(a.operator_raw)} ` : ""}
                          {label(a.value_raw ?? a.value ?? a.raw_value)}
                          {Array.isArray(a.qualifiers_raw) &&
                            a.qualifiers_raw.length > 0 && (
                              <p className="operations-note">
                                조건: {a.qualifiers_raw.map(label).join(" · ")}
                              </p>
                            )}
                        </td>
                        <td>{label(a.unit_raw)}</td>
                        {view === "mapping" && (
                          <>
                            <td>
                              {rows(mappingFor(a)?.facts).map((fact, index) => (
                                <div key={index}>
                                  {label(
                                    fact.property_label ||
                                      fact.property_stable_key ||
                                      fact.property_id ||
                                      fact.property_concept_id,
                                  )}
                                </div>
                              ))}
                              {!rows(mappingFor(a)?.facts).length && "—"}
                            </td>
                            <td>
                              <span className="analysis-status">
                                {mappingLabel(a)}
                              </span>
                              {mappingFor(a)?.reason ? (
                                <details
                                  onClick={(event) => event.stopPropagation()}
                                >
                                  <summary>보류 사유</summary>
                                  <code>{label(mappingFor(a)?.reason)}</code>
                                </details>
                              ) : null}
                            </td>
                          </>
                        )}
                        <td>
                          {refs(a).length ? (
                            nodeButton(a, true)
                          ) : (
                            <span className="operations-note">근거 없음</span>
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
                  이 대상에 연결된 속성이 없습니다. 다른 구성품을 선택하거나
                  대상 미지정 속성을 확인하세요.
                </p>
              )}
              {!!relations.length && (
                <details>
                  <summary>연결 관계 · {relations.length}</summary>
                  {relations.map((r, i) => (
                    <div key={i} className="analysis-relation">
                      <span>
                        {label(
                          graph.entities.find((e) => e.id === r.source_id)
                            ?.name || r.source_id,
                        )}{" "}
                        →{" "}
                        {label(
                          graph.entities.find((e) => e.id === r.target_id)
                            ?.name || r.target_id,
                        )}{" "}
                        · {relationNames[String(r.kind)] || label(r.kind)} ·{" "}
                        {r.basis === "explicit"
                          ? "명시"
                          : r.basis === "interpreted"
                            ? "해석"
                            : "불명확"}
                      </span>
                      {nodeButton(r)}
                    </div>
                  ))}
                </details>
              )}
            </>
          ) : (
            <p>표시할 구성 대상이 없습니다.</p>
          )}
          {!!unassigned.length && (
            <details>
              <summary>대상 미지정 속성 · {unassigned.length}</summary>
              {unassigned.map((a, i) => (
                <div key={i}>
                  {label(a.property_raw || a.property_key)}:{" "}
                  {label(a.value_raw)} {nodeButton(a)}
                </div>
              ))}
            </details>
          )}
          {!!held.length && (
            <details>
              <summary>보류 관계 · {held.length}</summary>
              <p>보류 관계는 구성품 트리에 반영하지 않습니다.</p>
              <pre>{JSON.stringify(held, null, 2)}</pre>
            </details>
          )}
        </section>
        {sourceOpen && (
          <section
            ref={sourcePanel}
            className="analysis-source"
            aria-label="선택한 원문 근거"
          >
            <div className="analysis-source-heading">
              <h4>원문 근거</h4>
              <button
                className="operations-link"
                onClick={() => {
                  setSourceOpen(false);
                  setSelectedAttribute("");
                }}
              >
                근거 닫기
              </button>
            </div>
            <p>{sourceTitle}</p>
            <div className="analysis-source-tabs">
              {(selectedAttribute
                ? refs(
                    attributes.find(
                      (a) =>
                        String(a.id ?? attributes.indexOf(a)) ===
                        selectedAttribute,
                    ) || {},
                  )
                : [focused]
              ).map((id) => (
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
          </section>
        )}
      </div>
    </>
  );
}
