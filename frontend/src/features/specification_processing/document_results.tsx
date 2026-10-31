import type { ReactNode } from "react";

export type ResultRecord = Record<string, unknown>;
export const resultRows = (value: unknown): ResultRecord[] =>
  Array.isArray(value)
    ? value.filter(
        (item): item is ResultRecord => !!item && typeof item === "object",
      )
    : [];
export const resultLabel = (value: unknown): string =>
  value == null
    ? "—"
    : typeof value === "object"
      ? JSON.stringify(value)
      : String(value);
export function resultRefs(item: ResultRecord): string[] {
  const evidence = Array.isArray(item.evidence)
    ? resultRows(item.evidence)
    : [item.evidence as ResultRecord | undefined];
  return [
    ...new Set(
      evidence
        .flatMap((reference) => [
          reference?.node_id,
          ...(Array.isArray(reference?.source_node_ids)
            ? reference.source_node_ids
            : []),
        ])
        .filter((id): id is string => typeof id === "string" && !!id.trim()),
    ),
  ];
}
const relationNames: Record<string, string> = {
  component_of: "구성품",
  physical_part_of: "내부 부품",
  specification_for: "상세 규격 대상",
  in_procurement_scope: "구매 범위",
  service_for: "작업 대상",
  software_for: "소프트웨어 구성 대상",
  document_for: "문서 대상",
  ingredient_of: "원재료 구성",
  material_of: "재질",
  packaging_for: "포장재",
  pack_unit_of: "포장 단위",
  installed_on: "설치 대상",
  firmware_for: "펌웨어 대상",
  depends_on: "의존 대상",
  supports: "지원 대상",
  compatible_with: "호환",
  sends_data_to: "데이터 전달",
  same_target_as: "동일 대상 후보",
};
export function RelationResults({
  relations,
  entities,
  onChoose,
  evidence,
  showReasons = true,
}: {
  relations: ResultRecord[];
  entities: ResultRecord[];
  onChoose: (id: string) => void;
  evidence: (record: ResultRecord) => ReactNode;
  showReasons?: boolean;
}) {
  const endpoint = (id: unknown) => {
    const entity = entities.find((item) => item.id === id);
    return entity ? (
      <button
        type="button"
        className="operations-link"
        onClick={() => onChoose(String(id))}
      >
        {resultLabel(entity.name || id)}
      </button>
    ) : (
      <span>{resultLabel(id)} · 대상 없음</span>
    );
  };
  if (!relations.length)
    return (
      <p className="operations-note">이 엔티티에 연결된 관계가 없습니다.</p>
    );
  return (
    <div className="result-relations">
      {relations.map((relation, index) => (
        <article key={String(relation.id ?? index)} className="result-relation">
          <p>
            {endpoint(relation.source_id)} <span aria-label="관계 방향">→</span>{" "}
            {endpoint(relation.target_id)}
          </p>
          <p>
            {relationNames[String(relation.kind)] || resultLabel(relation.kind)}{" "}
            ·{" "}
            {relation.review_status === "held"
              ? "보류"
              : relation.basis === "explicit"
                ? "명시"
                : relation.basis === "interpreted"
                  ? "해석"
                  : "근거 유형 미확정"}
          </p>
          {showReasons && Array.isArray(relation.reasons) && (
            <p>사유: {relation.reasons.map(resultLabel).join(" · ")}</p>
          )}
          <div className="observation-evidence-links">
            {resultRefs(relation).length ? (
              evidence(relation)
            ) : (
              <span>원문 근거 없음</span>
            )}
          </div>
        </article>
      ))}
    </div>
  );
}

export type UnresolvedResult = {
  id: string;
  title: string;
  reasons: string[];
  record: ResultRecord;
  attribute?: ResultRecord;
  relation?: ResultRecord;
  entityId?: string;
};
export function unresolvedResults(
  document: ResultRecord,
  _mappings: ResultRecord[],
  _mappingAvailable: boolean,
): UnresolvedResult[] {
  const entities = resultRows(document.entities),
    attributes = resultRows(document.attributes);
  const ids = new Set(entities.map((item) => item.id));
  const nodes = new Map(
    resultRows(
      (document.parsed_document as ResultRecord | undefined)?.nodes,
    ).map((node) => [node.node_id, node]),
  );
  const hasEvidence = (record: ResultRecord) =>
    resultRefs(record).some((id) => String(nodes.get(id)?.text || "").trim());
  const results: UnresolvedResult[] = [];
  for (const [index, attribute] of attributes.entries()) {
    const reasons: string[] = [];
    if (
      !Array.isArray(attribute.subject_ids) ||
      !attribute.subject_ids.length ||
      attribute.subject_ids.some((id) => !ids.has(id))
    )
      reasons.push(
        "속성이 연결될 엔티티가 없거나 일부 대상 참조를 찾지 못했습니다.",
      );
    if (!hasEvidence(attribute))
      reasons.push("이 산출물에서 연결된 원문 근거를 찾지 못했습니다.");
    if (reasons.length)
      results.push({
        id: `attribute_${index}`,
        title: `${resultLabel(attribute.property_raw || attribute.property_key)}: ${resultLabel(attribute.value_raw)}`,
        reasons,
        record: attribute,
        attribute,
      });
  }
  resultRows(document.held_relations).forEach((relation, index) =>
    results.push({
      id: `held_${index}`,
      title: "보류 관계",
      reasons: Array.isArray(relation.reasons)
        ? relation.reasons.map(resultLabel)
        : ["구성 계층에 반영되지 않은 관계입니다."],
      record: relation,
      relation,
    }),
  );
  resultRows(document.relations).forEach((relation, index) => {
    const reasons = [];
    if (!ids.has(relation.source_id) || !ids.has(relation.target_id))
      reasons.push("관계의 출발 또는 도착 엔티티를 찾지 못했습니다.");
    if (!hasEvidence(relation))
      reasons.push("관계의 원문 근거를 찾지 못했습니다.");
    if (reasons.length)
      results.push({
        id: `relation_${index}`,
        title: "관계 연결·근거 미확정",
        reasons,
        record: relation,
        relation,
      });
  });
  const extraction = document.unresolved_extraction as ResultRecord | undefined;
  for (const [key, title] of [
    ["failed_chunks", "추출에 실패한 구간"],
    ["uncovered_spec_fragments", "속성으로 연결되지 않은 원문 구간"],
  ]) {
    const count = extraction?.[key];
    if (typeof count === "number" && count > 0)
      results.push({
        id: key,
        title: `${title} · ${count}개`,
        reasons: [
          "추출 범위가 완전하지 않을 수 있습니다. 원문과 실행 정보를 함께 확인하세요.",
        ],
        record: {},
      });
  }
  const semantic = extraction?.semantic_resolution as ResultRecord | undefined;
  for (const [key, title] of [
    ["unresolved", "의미 연결 미해결"],
    ["unresolved_scope", "적용 범위 미확정"],
  ]) {
    const count = semantic?.[key];
    if (typeof count === "number" && count > 0)
      results.push({
        id: `semantic_${key}`,
        title: `${title} · ${count}개`,
        reasons: ["이 실행에서 해당 의미나 범위를 확정하지 못했습니다."],
        record: {},
      });
  }
  if (document.extraction_status === "partial" && !results.length)
    results.push({
      id: "partial",
      title: "일부 추출",
      reasons: [
        "부분 완료로 기록된 문서입니다. 이 산출물에는 상세 미해결 위치가 제공되지 않았습니다.",
      ],
      record: {},
    });
  return results;
}
export function UnresolvedResults({
  items,
  entities,
  onChoose,
  onAttribute,
  evidence,
}: {
  items: UnresolvedResult[];
  entities: ResultRecord[];
  onChoose: (id: string) => void;
  onAttribute: (attribute: ResultRecord) => void;
  evidence: (record: ResultRecord) => ReactNode;
}) {
  return (
    <section className="result-unresolved" aria-label="문서 미해결 항목">
      <h4>미해결 항목 · {items.length}</h4>
      {!items.length && <p>이 산출물에 기록된 미해결 항목이 없습니다.</p>}
      {items.map((item) => (
        <article className="result-issue" key={item.id}>
          <h5>{item.title}</h5>
          <ul>
            {item.reasons.map((reason, index) => (
              <li key={index}>{reason}</li>
            ))}
          </ul>
          {item.relation ? (
            <RelationResults
              showReasons={false}
              relations={[item.relation]}
              entities={entities}
              onChoose={onChoose}
              evidence={evidence}
            />
          ) : item.attribute ? (
            <button
              type="button"
              className="operations-link"
              onClick={() => onAttribute(item.attribute!)}
            >
              속성 원문 확인
            </button>
          ) : (
            evidence(item.record)
          )}
        </article>
      ))}
    </section>
  );
}
export function normalizedResultValue(fact: ResultRecord): string {
  const value = fact.value;
  if (value == null) return "값 미기재";
  if (typeof value !== "object") return resultLabel(value);
  const record = value as ResultRecord;
  const unit = record.unit || record.unit_text || record.unit_raw;
  if (record.decimal != null)
    return [record.decimal, unit]
      .filter((item) => item != null)
      .map(resultLabel)
      .join(" ");
  if (record.min_decimal != null && record.max_decimal != null)
    return `${resultLabel(record.min_decimal)}–${resultLabel(record.max_decimal)}${unit ? ` ${resultLabel(unit)}` : ""}`;
  return resultLabel(record.text ?? record.raw_text ?? value);
}
