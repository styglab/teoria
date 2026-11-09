import type { ReactNode } from "react";
import { attributeName } from "./AttributeValue";
import {
  resultLabel as label,
  type ResultRecord as Row,
  resultRows as rows,
} from "./document_results";

const reasons: Record<string, string> = {
  no_suitable_context_concept: "선택한 게시 개념에서 연결을 찾지 못했습니다",
  conflicts_with_approved_mapping: "기존 승인 연결과 달라 검토가 필요합니다",
  property_owner_mismatch: "속성의 소유 대상이 다릅니다",
  owner_unresolved: "속성의 대상 개념을 먼저 확인해야 합니다",
  relation_endpoints_unresolved: "관계 양쪽의 대상 개념이 확인되지 않았습니다",
  relation_endpoint_or_direction_mismatch: "관계의 대상 또는 방향이 다릅니다",
  unit_not_allowed_by_publication: "게시된 속성의 허용 단위와 다릅니다",
  value_type_mismatch: "게시된 속성의 값 유형과 다릅니다",
  source_role_or_scope_unresolved: "원문의 역할·적용 범위가 불명확합니다",
  alignment_model_failed: "연결 제안을 생성하지 못했습니다",
};

export function OntologyAlignmentResults({
  document,
  normalization,
  sourceButton,
}: {
  document: Row;
  normalization?: Row | null;
  sourceButton: (observation: Row) => ReactNode;
}) {
  const report = normalization?.ontology_alignment as Row | undefined;
  if (!report) return null;
  const observations = rows(report.observations).filter(
    (row) => row.document_id === document.document_id,
  );
  const lookup = new Map<string, Row>();
  const entities = new Map(
    rows(document.entities).map((row) => [String(row.id), label(row.name)]),
  );
  for (const [kind, collection] of [
    ["entity", "entities"],
    ["attribute", "attributes"],
    ["relation", "relations"],
  ])
    for (const observation of rows(document[collection]))
      lookup.set(`${kind}:${observation.id}`, observation);
  return (
    <details
      className="validation-rejections"
      aria-label="Ontology 의미 연결 비교"
    >
      <summary>Ontology 의미 연결 비교 · {observations.length}건</summary>
      <p>
        게시된 개념을 참고한 검토 제안입니다. 원문 관찰·기존 승인 연결·프로파일
        적용 결과는 유지됩니다. 연결되지 않은 내용도 보존하며, 이 건수는 정확도
        점수가 아닙니다.
      </p>
      <p>
        미연결 항목은 개념 범위를 넓힐지, Ontology 변경이 필요한지 검토하는
        후보입니다.
      </p>
      {!!rows(report.ontologies).length && (
        <p>
          참고한 게시 버전:{" "}
          {rows(report.ontologies)
            .map((o) => `${label(o.namespace)} ${label(o.version)}`)
            .join(", ")}
        </p>
      )}
      <table>
        <thead>
          <tr>
            <th>관찰</th>
            <th>기존 승인 연결</th>
            <th>새 연결 제안</th>
            <th>검토 상태</th>
            <th>근거</th>
          </tr>
        </thead>
        <tbody>
          {observations.map((row) => {
            const original = lookup.get(`${row.kind}:${row.observation_id}`);
            const name = original
              ? row.kind === "attribute"
                ? attributeName(original)
                : row.kind === "relation"
                  ? `${entities.get(String(original.source_id)) || "대상"} → ${entities.get(String(original.target_id)) || "대상"}`
                  : label(original.name)
              : "관찰 항목";
            return (
              <tr key={`${row.kind}:${row.observation_id}`}>
                <td>{name}</td>
                <td>
                  {row.baseline
                    ? label(row.baseline_concept_label || "승인 연결 있음")
                    : "없음"}
                </td>
                <td>{label(row.concept_label || "연결 제안 없음")}</td>
                <td>
                  {row.status === "proposed"
                    ? "연결 검토 제안"
                    : reasons[String(row.reason)] ||
                      "근거와 개념을 검토해야 합니다"}
                </td>
                <td>{original && sourceButton(original)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </details>
  );
}
