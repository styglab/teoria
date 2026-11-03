import { useEffect, useMemo, useRef, useState } from "react";

import {
  type ResultRecord as Row,
  resultRows as rows,
  resultLabel as label,
  resultRefs as refs,
  RelationResults,
  UnresolvedResults,
  unresolvedResults,
} from "./document_results";
import "./document_results.css";
import { AttributeValue, attributeName } from "./AttributeValue";

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
const COMPOSITION_DISPLAY_LEVELS = 3;
function isGoodsTarget(entity: Row) {
  return (
    !["activity", "document"].includes(String(entity.kind)) &&
    !(
      Array.isArray(entity.document_roles) &&
      entity.document_roles.some((role) => ["existing_target", "work_scope_target"].includes(String(role)))
    )
  );
}

/** Preserve grounded parent proposals; interpreted links stay visibly under review. */
export function composition(
  document: Row,
  mode = "composition",
  primaryOnly = false,
) {
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
  const related = new Set(
    entities.filter((e) => !isGoodsTarget(e)).map((e) => String(e.id)),
  );
  // A component of an existing asset is not a newly supplied component by default.
  let changed = true;
  while (changed) {
    changed = false;
    for (const r of rows(document.relations)) {
      if (
        ["component_of", "physical_part_of"].includes(String(r.kind)) &&
        related.has(String(r.target_id)) &&
        !related.has(String(r.source_id))
      ) {
        const child = entities.find((e) => e.id === r.source_id);
        if (
          Array.isArray(child?.document_roles) &&
          child.document_roles.includes("supply_target")
        )
          continue;
        related.add(String(r.source_id));
        changed = true;
      }
    }
  }
  const candidates = rows(document.relations).filter(
    (r) =>
      (!primaryOnly ||
        (!related.has(String(r.source_id)) &&
          !related.has(String(r.target_id)))) &&
      (mode === "packaging"
        ? r.kind === "pack_unit_of"
        : ["component_of", "physical_part_of"].includes(String(r.kind))) &&
      ((physical(r.source_id) && physical(r.target_id)) ||
        (mode === "composition" &&
          r.kind === "component_of" &&
          software(r.source_id) &&
          software(r.target_id))) &&
      (r.basis === "explicit" ||
        (mode === "composition" &&
          r.kind === "component_of" &&
          r.basis === "interpreted")) &&
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
  const pendingParents = new Set<string>();
  for (const [child, targets] of parents) {
    if (targets.size !== 1) continue;
    const parent = [...targets][0];
    if (reaches(parent, child)) continue;
    children.set(parent, [...(children.get(parent) || []), child]);
    attached.add(child);
    if (!candidates.some((r) =>
      String(r.source_id) === child && String(r.target_id) === parent && r.basis === "explicit"))
      pendingParents.add(child);
  }
  const inventory = (document.composition_inventory || {}) as Row;
  const primaryIds = Array.isArray(inventory.item_ids)
    ? inventory.item_ids.map(String) : [];
  const anchor = mode === "composition" &&
    inventory.basis === "configuration_list" && inventory.integrated_scope === true &&
    ids.has(String(inventory.root_id)) ? String(inventory.root_id) : undefined;
  if (anchor && children.has(anchor)) {
    const order = new Map(primaryIds.map((id, index) => [id, index]));
    children.get(anchor)!.sort((a, b) =>
      (order.get(a) ?? Infinity) - (order.get(b) ?? Infinity));
  }
  // A withheld parent link must never promote a descendant into a new top-level goods target.
  const proposedChildren = new Set(
    [...rows(document.relations), ...rows(document.held_relations)]
      .filter((r) => mode === "packaging" ? r.kind === "pack_unit_of"
        : ["component_of", "physical_part_of"].includes(String(r.kind)))
      .map((r) => String(r.source_id)),
  );
  // Purchase evidence chooses anchors; category codes and titles never invent a product.
  const supplyBasis = mode === "composition" && inventory.basis === "supply_list";
  const explicitlyPurchased = entities.filter((e) =>
    Array.isArray(e.document_roles) && e.document_roles.includes("supply_target"));
  const purchaseIds = new Set<string>(mode === "composition" ? [
    ...(anchor ? [anchor] : []),
    ...explicitlyPurchased.filter((e) => String(e.id) === String(inventory.root_id)).map((e) => String(e.id)),
    ...(supplyBasis ? primaryIds : []),
    ...explicitlyPurchased.map((e) => String(e.id)),
  ] : []);
  const purchaseAnchored = mode === "composition" && (purchaseIds.size > 0 || !!document.composition_inventory);
  const inferredRoots = purchaseAnchored
    ? [...purchaseIds].map((id) => entities.find((e) => String(e.id) === id))
        .filter((e): e is Row => !!e && isGoodsTarget(e) && !related.has(String(e.id)) &&
          ![...(parents.get(String(e.id)) || [])].some((parent) => !related.has(parent)) &&
          ![...rows(document.relations), ...rows(document.held_relations)].some((r) =>
            r.source_id === e.id && ["component_of", "physical_part_of"].includes(String(r.kind)) &&
            !related.has(String(r.target_id))))
    : entities.filter((e) =>
        (!primaryOnly || !related.has(String(e.id))) && children.has(String(e.id)) &&
        !attached.has(String(e.id)) && !proposedChildren.has(String(e.id)));
  const hierarchy = (document.composition_hierarchy || {}) as Row;
  const hasHierarchy = mode === "composition" && hierarchy.schema_version === 1 &&
    hierarchy.max_primary_levels === COMPOSITION_DISPLAY_LEVELS &&
    Array.isArray(hierarchy.root_ids) && Array.isArray(hierarchy.primary_entity_ids) &&
    Array.isArray(hierarchy.detail_entity_ids);
  const roots = hasHierarchy
    ? (hierarchy.root_ids as string[]).flatMap((id) => entities.filter((e) => String(e.id) === id))
    : inferredRoots;
  const treeIds = new Set<string>();
  const depths = new Map<string, number>();
  const pending = roots.map((e) => ({ id: String(e.id), level: 1 }));
  while (pending.length) {
    const { id, level } = pending.pop()!;
    if (treeIds.has(id)) continue;
    treeIds.add(id);
    depths.set(id, level);
    pending.push(...(children.get(id) || []).map((child) => ({ id: child, level: level + 1 })));
  }
  // Keep the full source graph for details and ancestry; bound only the default composition view.
  const primaryIdsFromPipeline = new Set(hasHierarchy ? hierarchy.primary_entity_ids as string[] : []);
  const detailIdsFromPipeline = new Set(hasHierarchy ? hierarchy.detail_entity_ids as string[] : []);
  if (hasHierarchy) {
    for (const [id, level] of Object.entries((hierarchy.levels || {}) as Row))
      if (typeof level === "number") depths.set(id, level);
  }
  const displayChildren = new Map([...children].filter(([id]) =>
    mode !== "composition" || (depths.get(id) ?? Infinity) < COMPOSITION_DISPLAY_LEVELS)
    .map(([id, children]): [string, string[]] => [id, hasHierarchy ? children.filter((child) => primaryIdsFromPipeline.has(child)) : children])
    .filter(([, children]) => children.length));
  const detailTargets = entities.filter((e) =>
    hasHierarchy ? detailIdsFromPipeline.has(String(e.id))
      : mode === "composition" && (depths.get(String(e.id)) ?? 0) > COMPOSITION_DISPLAY_LEVELS);
  const scopes = entities.filter((e) => !treeIds.has(String(e.id)) && !purchaseIds.has(String(e.id)) &&
    !related.has(String(e.id)) && !explicitlyPurchased.some((item) => item.id === e.id) &&
    Array.isArray(e.document_roles) && e.document_roles.includes("procurement_scope"));
  return {
    entities,
    supplyBasis,
    purchaseAnchored,
    scopes,
    children,
    displayChildren,
    detailTargets,
    depths,
    roots,
    treeIds,
    pendingParents,
    unclassified: entities.filter(
      (e) =>
        (!primaryOnly || !related.has(String(e.id))) &&
        !treeIds.has(String(e.id)) && !scopes.some((scope) => scope.id === e.id),
    ),
    related: entities.filter((e) => related.has(String(e.id))),
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
        왼쪽에서 물품·구성품을 선택하고, 속성 행을 누르면 오른쪽에서 원문을 대조할 수 있습니다.
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
    composition(document, "composition", true).roots.length ? "composition" : "list",
  );
  const inventoryAssessment = (document.inventory_assessment || {}) as Row;
  const inventoryStatusNames: Record<string, string> = {
    confirmed: "기준 목록 확인",
    detail_fallback: "목록 미확인 · 상세 사양 기준",
    reading_failed: "기준 목록 판독 확인 필요",
    reading_uncertain: "기준 목록 확인 필요",
    unresolved: "기준 목록 미확정",
  };
  const [scopeFilter, setScopeFilter] = useState("goods");
  const [kindFilter, setKindFilter] = useState("all");
  const availableKinds = Object.entries(kindNames).filter(([kind]) =>
    rows(document.entities).some((entity) => String(entity.kind ?? "unknown") === kind),
  );
  const graph = useMemo(
    () => composition(document, navigation, scopeFilter === "goods"),
    [document, navigation, scopeFilter],
  );
  const entitiesById = useMemo(
    () => new Map(graph.entities.map((entity) => [String(entity.id), entity])),
    [graph.entities],
  );
  const attributeCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const attribute of rows(document.attributes)) {
      if (Array.isArray(attribute.subject_ids))
        for (const id of new Set(attribute.subject_ids.map(String)))
          counts.set(id, (counts.get(id) || 0) + 1);
    }
    return counts;
  }, [document]);
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
  const [view, setView] = useState("source");
  const [filter, setFilter] = useState("all");
  const mappings = rows(normalization?.attributes).filter(
    (a) => a.document_id === document.document_id,
  );
  const mappingsById = new Map(
    mappings.map((mapping) => [mapping.attribute_id, mapping]),
  );
  const mappingFor = (a: Row) =>
    a.id != null ? mappingsById.get(a.id) : undefined;
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
    const panel = sourcePanel.current;
    if (panel && sourceOpen) {
      panel.scrollTop = 0;
      const passage = panel.querySelector(".evidence-node.is-selected mark") ||
        panel.querySelector(".evidence-node.is-selected");
      if (passage) {
        const top = passage.getBoundingClientRect().top - panel.getBoundingClientRect().top;
        if (top > panel.clientHeight - 100) panel.scrollTop = Math.max(0, top - 100);
      }
    }
    if (focused && window.innerWidth <= 1100)
      sourcePanel.current?.scrollIntoView?.({
        block: "nearest",
        behavior: "smooth",
      });
  }, [focused, sourceOpen, selectedAttribute]);
  const [mobileDetail, setMobileDetail] = useState(false);
  const entity = entitiesById.get(selected);
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
  const coreUnresolved = unresolved.filter((item) => !item.supplementary);
  const supplementaryUnresolved = unresolved.filter(
    (item) => item.supplementary,
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
    (kindFilter === "all" || String(e.kind ?? "unknown") === kindFilter) &&
    (scopeFilter === "all" ||
      (scopeFilter === "goods"
        ? !graph.related.some((item) => item.id === e.id)
        : inPurchaseScope(e)));

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
      r.category !== "description" &&
      !isOther(r) &&
      Array.isArray(r.subject_ids) &&
      r.subject_ids.includes(selected),
  );
  const otherRows = rows(document.requirements).filter(isOther);
  const descriptions = rows(document.requirements).filter((r) => r.category === "description" &&
    Array.isArray(r.subject_ids) && r.subject_ids.includes(selected));
  const unassignedDescriptions = rows(document.requirements).filter((r) => r.category === "description" &&
    (!Array.isArray(r.subject_ids) || !r.subject_ids.length));
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
    const item = entitiesById.get(ancestor);
    if (item) ancestry.unshift(item);
    ancestor = parentOf.get(ancestor) || "";
  }
  const nodes = rows((document.parsed_document as Row | undefined)?.nodes);
  const node = nodes.find((n) => n.node_id === focused);
  const selectedObservation = attributes.find((a, index) =>
    String(a.id ?? index) === selectedAttribute);
  const sourceExcerpt = (a: Row) => {
    const evidence = (a.evidence || {}) as Row;
    return refs(a).map((id) => {
      const original = nodes.find((n) => n.node_id === id);
      let text = String(original?.text || "").trim();
      if (evidence.node_id === id && typeof evidence.char_start === "number" &&
          typeof evidence.char_end === "number" && evidence.char_start >= 0 &&
          evidence.char_end > evidence.char_start && evidence.char_end <= String(original?.text || "").length)
        text = String(original?.text || "").slice(evidence.char_start, evidence.char_end).trim();
      return text;
    }).filter(Boolean).join(" · ");
  };
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
  const unnamed = attributes.filter((a) => attributeName(a) === "속성명 확인 필요");
  const shownAttributes =
    filter === "evidence"
      ? missingEvidence
      : filter === "unmapped"
        ? unmapped
        : filter === "unnamed" ? unnamed : attributes;
  const openAttribute = (a: Row, index: number) => {
    setSelectedAttribute(String(a.id ?? attributes.indexOf(a) ?? index));
    setSourceTitle(attributeName(a));
    setSourceReferences(refs(a));
    setFocused(refs(a)[0] || "");
    setSourceOpen(true);
  };
  const choose = (id: string) => {
    setSelected(id);
    setRelationScope("selected");
    setMobileDetail(true);
  };
  const nodeButton = (item: Row) => {
    const references = refs(item);
    if (!references.length) return null;
    return <button className="operations-link" type="button" onClick={(event) => {
      event.stopPropagation();
      setSelectedAttribute("");
      setSourceTitle(label(item.name || item.text ||
        (item.source_id && item.target_id
          ? `${label(entitiesById.get(String(item.source_id))?.name)} → ${label(entitiesById.get(String(item.target_id))?.name)}`
          : "선택한 항목")));
      setSourceReferences(references);
      setFocused(references[0]);
      setSourceOpen(true);
    }}>
      원문 보기{references.length > 1 ? ` · ${references.length}곳` : ""}
    </button>;
  };
  const visible: { id: string; depth: number }[] = [];
  const pending = graph.roots
    .map((e) => ({ id: String(e.id), depth: 0 }))
    .reverse();
  while (pending.length) {
    const next = pending.pop()!;
    visible.push(next);
    if (!closed.has(next.id))
      pending.push(
        ...(graph.displayChildren.get(next.id) || [])
          .map((id) => ({ id, depth: next.depth + 1 }))
          .reverse(),
      );
  }
  const treeCandidates =
    navigation === "list" || query || (scopeFilter === "purchase" || kindFilter !== "all")
      ? graph.entities.filter(matches).map((e) => String(e.id))
      : [
          ...visible.map((e) => e.id),
          ...graph.unclassified.map((e) => String(e.id)),
          ...graph.detailTargets.map((e) => String(e.id)),
        ];
  const itemRow = (id: string, depth = 0) => {
    const item = entitiesById.get(id)!;
    const children =
      navigation === "list" || query || (scopeFilter === "purchase" || kindFilter !== "all")
        ? undefined
        : graph.treeIds.has(id)
          ? graph.displayChildren.get(id)
          : undefined;
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
            graph.detailTargets[0]?.id === id || (scopeFilter === "goods" && (graph.related[0]?.id === id || graph.scopes[0]?.id === id))
              ? 0
              : id ===
                  (treeCandidates.includes(treeFocus)
                    ? treeFocus
                    : treeCandidates[0])
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
            {attributeCounts.get(id) || 0}개 속성
            {kindNames[String(item.kind)]
              ? ` · ${kindNames[String(item.kind)]}`
              : ""}
            {navigation === "composition" &&
            graph.treeIds.has(id) && graph.pendingParents.has(id)
              ? " · 구성 관계 검토 중"
              : ""}
            {Array.isArray(item.document_roles) &&
            item.document_roles.includes("existing_target")
              ? " · 기존 대상"
              : ""}
            {Array.isArray(item.document_roles) && item.document_roles.includes("work_scope_target")
              ? " · 작업 대상 묶음" : ""}
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
            onClick={() => { setView("source"); setFilter("all"); }}
          >
            추출 결과
          </button>
          <button
            aria-pressed={view === "mapping"}
            onClick={() => setView("mapping")}
          >
            표준 매핑
          </button>
        </div>
        <span className="analysis-status">
          {document.extraction_status === "partial"
            ? "일부 추출 · 미해결 항목 있음"
            : document.extraction_status === "extracted" ? "추출 완료" : "추출 결과"}
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
          대상 <strong>{graph.entities.length}</strong>
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
          미해결 항목 <strong>{coreUnresolved.length}</strong>
        </button>
        {!!supplementaryUnresolved.length && (
          <span>
            부가 관계 검토 <strong>{supplementaryUnresolved.length}</strong>
          </span>
        )}
        {view === "mapping" && mappingStatus === "available" && (
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
            물품·구성 <small>{graph.entities.length}개 대상</small>
          </h3>
          {inventoryStatusNames[String(inventoryAssessment.status)] && (
            <p className="operations-note" aria-label="구매 기준 확인 상태">
              {inventoryStatusNames[String(inventoryAssessment.status)]}
            </p>
          )}
          <input
            aria-label="분석 대상 검색"
            placeholder="대상 이름 검색"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <label>
            조회 범위
            <select
              aria-label="조회 범위"
              value={scopeFilter}
              onChange={(event) => {
                setScopeFilter(event.target.value);
                setKindFilter("all");
              }}
            >
              <option value="goods">물품·구성</option>
              <option value="all">전체</option>
              <option value="purchase">구매 범위 항목</option>
            </select>
          </label>
          <details className="analysis-type-filter">
            <summary>세부 유형 필터</summary>
            <label>
              대상 유형
              <select
                aria-label="대상 유형"
                value={kindFilter}
                onChange={(event) => setKindFilter(event.target.value)}
              >
                <option value="all">전체 유형</option>
                {availableKinds.map(([key, name]) => (
                  <option key={key} value={key}>{name}</option>
                ))}
              </select>
            </label>
          </details>
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
              <button onClick={() => setClosed(new Set(graph.displayChildren.keys()))}>
                전체 접기
              </button>
            </div>
          )}
          <div role="tree" aria-label="구성 대상">
            {navigation === "list" ||
            query ||
            (scopeFilter === "purchase" || kindFilter !== "all") ? (
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
                      : graph.purchaseAnchored ? "구매 물품·구성" : "구성 관계"}
                  </h4>
                )}
                {navigation === "composition" && !!visible.length && (
                  <p className="operations-note">최상위 물품 포함 3계층까지 표시합니다.</p>
                )}
                {visible.map(({ id, depth }) => itemRow(id, depth))}
                {!graph.roots.length && (
                  <p className="operations-note">
                    구매 물품과 상위 구성 연결을 확인할 수 없습니다.
                  </p>
                )}
                {!!graph.unclassified.length && (
                  <>
                    <h4>
                      상위 물품·구매 범위 확인 필요 · {graph.unclassified.length}
                    </h4>
                    {graph.unclassified.map((e) => itemRow(String(e.id)))}
                  </>
                )}
              </>
            )}
          </div>
          {navigation === "composition" && !query && kindFilter === "all" && scopeFilter !== "purchase" && !!graph.detailTargets.length && (
            <details className="analysis-scope-targets">
              <summary>세부 구성 · {graph.detailTargets.length}</summary>
              <p className="operations-note">
                4계층 이하의 구성입니다. 원래 관계와 속성·원문 근거를 유지합니다.
              </p>
              <div role="tree" aria-label="세부 구성">
                {graph.detailTargets.filter(matches).map((e) => (
                  <div key={String(e.id)}>
                    <p className="operations-note">
                      {graph.depths.get(String(e.id))}계층 · 상위 구성: {label(entitiesById.get(parentOf.get(String(e.id)) || "")?.name)}
                    </p>
                    {itemRow(String(e.id))}
                  </div>
                ))}
              </div>
            </details>
          )}
          {scopeFilter === "goods" && !!graph.scopes.length && (
            <details className="analysis-scope-targets">
              <summary>구매 범위·공통 규격 · {graph.scopes.length}</summary>
              <p className="operations-note">구매 전체의 범위와 공통 조건입니다. 구성품의 상위 물품으로 확정하지 않습니다.</p>
              <div role="tree" aria-label="구매 범위">
                {graph.scopes.filter((e) =>
                  (kindFilter === "all" || String(e.kind ?? "unknown") === kindFilter) &&
                  label(e.name).toLowerCase().includes(query.toLowerCase()),
                ).map((e) => itemRow(String(e.id)))}
              </div>
            </details>
          )}
          {scopeFilter === "goods" && !!graph.related.length && (
            <details className="analysis-related-targets">
              <summary>
                관련 대상·설치 지원·문서 · {graph.related.length}
              </summary>
              <div role="tree" aria-label="관련 대상">
                {graph.related.filter((e) =>
                  (kindFilter === "all" || String(e.kind ?? "unknown") === kindFilter) &&
                  label(e.name).toLowerCase().includes(query.toLowerCase()),
                ).map((e) => itemRow(String(e.id)))}
              </div>
            </details>
          )}
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
            <>
              <UnresolvedResults
                items={coreUnresolved}
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
              {!!supplementaryUnresolved.length && (
                <details>
                  <summary>
                    부가 관계 검토 · {supplementaryUnresolved.length}
                  </summary>
                  <p>
                    통신·호환·의존·지원 관계의 보류입니다. 물품 구성·속성 추출의
                    미해결 항목과 별도로 확인합니다.
                  </p>
                  <UnresolvedResults
                    supplementary
                    items={supplementaryUnresolved}
                    entities={graph.entities}
                    onChoose={(id) => {
                      choose(id);
                      setDetailTab("relations");
                    }}
                    evidence={(record) => nodeButton(record)}
                  />
                </details>
              )}
            </>
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
                          구매 기준 수량:{" "}
                          <strong>
                            {label(q.value_raw)}{" "}
                            {q.unit_raw ? label(q.unit_raw) : ""}
                          </strong>
                        </div>
                      ))}
                    </div>
                  )}
                  {inventoryAssessment.status && !quantities.length && (
                    <p className="operations-note">구매 기준 수량: 별도 기재 없음</p>
                  )}
                  <div className="analysis-attribute-toolbar">
                    <h4>추출 속성 · {attributes.length}</h4>
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
                        <option value="unnamed">이름 확인 필요 ({unnamed.length})</option>
                        {view === "mapping" && <option
                          value="unmapped"
                          disabled={mappingStatus !== "available"}
                        >
                          보류·미매핑 (
                          {mappingStatus === "available"
                            ? unmapped.length
                            : "—"}
                          )
                        </option>}
                      </select>
                    </label>
                  </div>
                  <div className="page-table-wrap">
                    <table className="page-table">
                      <thead>
                        <tr>
                          <th>속성</th>
                          <th>
                            {view === "mapping"
                              ? "요구값·단위·조건"
                              : "요구값·조건"}
                          </th>
                          {view !== "mapping" && <th>단위</th>}
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
                            <td data-label="속성">
                              <span className="analysis-property-name">
                                {label(
                                  (view === "mapping" &&
                                    rows(mappingFor(a)?.facts).find(
                                      (fact) => fact.property_label,
                                    )?.property_label) ||
                                    attributeName(a),
                                )}
                              </span>
                              {view === "mapping" &&
                              rows(mappingFor(a)?.facts).some(
                                (fact) =>
                                  fact.property_label &&
                                  fact.property_label !== a.property_raw,
                              ) &&
                              a.property_raw ? (
                                <details
                                  className="analysis-internal-key"
                                  onClick={(event) => event.stopPropagation()}
                                >
                                  <summary>원문 속성명</summary>
                                  <span>{label(a.property_raw)}</span>
                                </details>
                              ) : null}
                              {view === "mapping" && (
                                <>
                                  <span className="analysis-status">
                                    {mappingLabel(a)}
                                  </span>
                                  {mappingFor(a)?.reason ? (
                                    <details
                                      className="analysis-internal-key"
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
                                </>
                              )}
                            </td>
                            <td
                              data-label={
                                view === "mapping"
                                  ? "요구값·단위·조건"
                                  : "요구값·조건"
                              }
                            >
                              <AttributeValue
                                attribute={a}
                                mapping={mappingFor(a)}
                                standard={view === "mapping"}
                              />
                            </td>
                            {view !== "mapping" && (
                              <td data-label="단위">{label(a.unit_raw)}</td>
                            )}
                            <td data-label="원문 근거">
                              {sourceExcerpt(a) && <p className="analysis-evidence-preview">
                                {sourceExcerpt(a).length > 150 ? `${sourceExcerpt(a).slice(0, 150)}…` : sourceExcerpt(a)}
                              </p>}
                              {refs(a).length ? (
                                <button className="operations-link" type="button"
                                  onClick={(event) => { event.stopPropagation(); openAttribute(a, i); }}>
                                  원문 보기{refs(a).length > 1 ? ` · ${refs(a).length}곳` : ""}
                                </button>
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
              {detailTab === "attributes" && !!descriptions.length && <details>
                <summary>물품 설명 · {descriptions.length}</summary>
                <p>개요·용도·작동 원리의 원문입니다. 규격 속성과 구분합니다.</p>
                {descriptions.map((clause, index) => <div key={String(clause.id ?? index)}>
                  <p>{label(clause.text)}</p>{nodeButton(clause)}
                </div>)}
              </details>}
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
          {detailTab === "attributes" && !!unassignedDescriptions.length && <details>
            <summary>문서 설명 · 대상 미지정 · {unassignedDescriptions.length}</summary>
            {unassignedDescriptions.map((clause, index) => <div key={String(clause.id ?? index)}>
              <p>{label(clause.text)}</p>{nodeButton(clause)}
            </div>)}
          </details>}
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
          {sourceOpen && <p className="operations-note">
            {(document.parser as Row | undefined)?.ocr ? "OCR로 읽은 문서 텍스트입니다." : "문서에서 읽어낸 원문 텍스트입니다."}
          </p>}
          {!sourceOpen ? (
            <p className="operations-note">
              엔티티·관계·속성의 원문 근거를 선택하면 해당 위치와 내용을
              표시합니다.
            </p>
          ) : (
            <>
              {!selectedObservation && <p>{sourceTitle}</p>}
              {selectedObservation && <div className="analysis-source-selection">
                <strong>{label(entity?.name)} · {attributeName(selectedObservation)}</strong>
                <div><AttributeValue attribute={selectedObservation} mapping={undefined} standard={false} />
                  {selectedObservation.unit_raw ? ` ${label(selectedObservation.unit_raw)}` : ""}</div>
                {!selectedObservation.property_raw && <small>
                  {selectedObservation.property_label_origin === "model_suggestion"
                    ? "속성명은 AI가 해석한 추출명입니다. 원문 명칭이나 승인된 표준명과 구분합니다."
                    : "속성명은 추출 분류에 따른 표시명입니다. 아래 원문과 대조하세요."}
                </small>}
              </div>}
              <div className="analysis-source-tabs">
                {sourceReferences.map((id, index) => (
                  <button
                    key={id}
                    aria-pressed={id === focused}
                    onClick={() => setFocused(id)}
                  >
                    근거 {index + 1}
                  </button>
                ))}
              </div>
              {sourceReferences.map((id, index) => {
                const source = nodes.find((n) => n.node_id === id);
                if (!source) return <p key={id} className="operations-note">이 산출물에서 해당 원문 노드를 찾지 못했습니다.</p>;
                const text = String(source.text || "");
                const evidence = (selectedObservation?.evidence || {}) as Row;
                const start = evidence.char_start, end = evidence.char_end;
                const highlight = evidence.node_id === id && typeof start === "number" &&
                  typeof end === "number" && start >= 0 && end > start && end <= text.length;
                return <article key={id} className={`evidence-node ${id === focused ? "is-selected" : ""}`}>
                  <small>근거 {index + 1}{source.page != null ? ` · ${label(source.page)}쪽` : ""}</small>
                  <p>{highlight ? <>{text.slice(0, start as number)}<mark>{text.slice(start as number, end as number)}</mark>{text.slice(end as number)}</> : text}</p>
                </article>;
              })}
              {!sourceReferences.length && (
                <p className="operations-note">
                  {focused
                    ? "이 산출물에서 해당 원문 노드를 찾지 못했습니다."
                    : "이 속성에는 원문 근거 참조가 없습니다."}
                </p>
              )}
              {node && <details className="analysis-source-context">
                <summary>앞뒤 원문 함께 보기</summary>
                {nodes.slice(Math.max(0, nodes.indexOf(node) - 2), nodes.indexOf(node) + 3)
                  .filter((n) => !sourceReferences.includes(String(n.node_id)) && String(n.text || "").trim()).map((n) => <p key={String(n.node_id)}
                    className={n.node_id === focused ? "is-selected" : ""}>{label(n.text)}</p>)}
              </details>}
              <details className="analysis-internal-key">
                <summary>추출 정보</summary>
                {selectedObservation?.property_key ? <p>내부 식별자: <code>{label(selectedObservation.property_key)}</code></p> : null}
                <p>원문 참조: {sourceReferences.join(", ") || "없음"}</p>
              </details>
            </>
          )}
        </section>
      </div>
    </>
  );
}
