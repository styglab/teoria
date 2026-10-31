import { Link, useSearchParams } from "react-router-dom";
import {
  documentCatalogApi,
  type DocumentResult,
} from "../../api/specification_processing";
import {
  resultRows,
  resultLabel,
  requirementValue,
  requirementContext,
} from "./document_results";
import { authority, standardSnapshot } from "./result_authority";
import { useCatalogQuery } from "./catalog_queries";
import { Button } from "../../components/ui/button";
type ComparisonCell = { label: string; values: string[]; attributeId: string };
export function comparisonRows(documents: DocumentResult[]) {
  const matrix = new Map<
    string,
    {
      label: string;
      context: string;
      property: string;
      snapshot: string;
      targets: string;
      role: string;
      scope: string;
      unit: string;
      cells: ComparisonCell[][];
    }
  >();
  documents.forEach((document, index) => {
    const result = document.result;
    const norm = result?.normalization;
    if (!norm) return;
    // Never equate IDs across standard snapshots, target scopes, roles or units.
    const snapshot = standardSnapshot(document);
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
              fact.property_label ||
                resultRows(extracted?.attributes).find(
                  (a) => a.id === attribute.attribute_id,
                )?.property_raw ||
                "표준 속성명 미제공",
            ),
            property: String(property),
            snapshot,
            targets: concepts.join(","),
            role: String(fact.role || ""),
            scope: String(fact.semantic_scope || ""),
            unit: String(value.unit || ""),
            context: [requirementContext(fact), resultLabel(value.unit)]
              .filter(Boolean)
              .join(" · "),
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
                requirementValue(fact),
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
  const key = ids.join(",");
  const valid =
    ids.length >= 2 && ids.length <= 4 && new Set(ids).size === ids.length;
  const query = useCatalogQuery(valid ? `comparison:${key}` : null, (signal) =>
    Promise.all(ids.map((id) => documentCatalogApi.result(id, signal))),
  );
  const data = query.data;
  const error = !valid
    ? "서로 다른 규격서 2–4개를 선택하세요."
    : query.error ||
      (data &&
      (data.some((d) => !d.result) ||
        new Set(data.map((d) => d.document.classification_code)).size !== 1)
        ? "같은 분류에서 결과가 있는 규격서를 선택하세요."
        : "");
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
        <div role="alert" className="spec-query-error">
          {error}
          {valid && (
            <Button variant="outline" onClick={query.retry}>
              다시 조회
            </Button>
          )}
        </div>
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
                        <small>
                          표준 버전{" "}
                          {resultLabel(
                            d.result?.normalization?.standard_version,
                          )}
                        </small>
                        <details className="spec-comparison-standard">
                          <summary>비교 기준</summary>
                          <p>{standardSnapshot(d)}</p>
                        </details>
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
                      <details>
                        <summary>표준 식별자</summary>
                        <code>{row.property}</code>
                      </details>
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
                          : comparisonGap(row, j, matrix)}
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

export function comparisonGap(
  row: ReturnType<typeof comparisonRows>[number],
  column: number,
  matrix: ReturnType<typeof comparisonRows>,
) {
  const candidates = matrix.filter(
    (other) => other.property === row.property && other.cells[column].length,
  );
  if (!candidates.length) return "표준 속성 매핑 없음";
  if (candidates.every((other) => other.snapshot !== row.snapshot))
    return "적용 표준 다름";
  const same = candidates.filter((other) => other.snapshot === row.snapshot);
  if (same.every((other) => other.unit !== row.unit)) return "단위 다름";
  if (same.every((other) => other.scope !== row.scope)) return "적용 범위 다름";
  if (same.every((other) => other.role !== row.role)) return "속성 역할 다름";
  if (same.every((other) => other.targets !== row.targets))
    return "대상 개념 다름·미확정";
  return "비교 기준 미확정";
}
