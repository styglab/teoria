import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { adminApi, type IntelligenceSuggestion, type MetadataTableDetail } from "../../api/admin";

export function SuggestionComparison({ item, table }: { item: IntelligenceSuggestion; table: MetadataTableDetail | null }) {
  const [target, setTarget] = useState<MetadataTableDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const supported = ["description", "glossary_term_assignment", "binding"].includes(item.suggestion_type);
  useEffect(() => {
    let active = true;
    setTarget(null); setError(null);
    if (!supported || !item.proposed_value.table_id) { setLoading(false); return; }
    setLoading(true);
    adminApi.suggestionTarget(item.suggestion_id)
      .then(value => { if (active) setTarget(value); })
      .catch(() => { if (active) setError("최신 값을 조회하지 못했습니다. 새로고침 후 다시 확인하세요."); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [item, supported]);
  if (!supported) return null;
  const currentTable = item.proposed_value.table_id ? target : table;
  const fqn = String(item.proposed_value.column_fqn || item.proposed_value.fully_qualified_name || item.target_ref.replace(/^openmetadata:\/\/(column|table)\//, ""));
  const column = currentTable?.columns.find(value => value.fullyQualifiedName === fqn || `${currentTable.reference.fully_qualified_name}.${value.name}` === fqn);
  const tableTarget = currentTable?.reference.fully_qualified_name === fqn || item.target_ref === `openmetadata://table/${currentTable?.reference.entity_id}`;
  const matched = currentTable && (column || tableTarget);
  let current = "최신 값 조회에 필요한 자산 참조가 없습니다.";
  if (loading) current = "최신 값을 조회하고 있습니다…";
  else if (error) current = error;
  else if (currentTable && !matched) current = "현재 자산에서 제안 대상을 찾지 못했습니다. 대상 변경 여부를 확인하세요.";
  else if (matched) {
    if (item.suggestion_type === "description") current = String((column ? column.description : currentTable.description) || "설명 없음");
    else if (item.suggestion_type === "glossary_term_assignment") {
      const tags = (column?.tags || currentTable.tags) as Array<{ tagFQN?: string; source?: string }>;
      current = tags.filter(tag => tag.source === "Glossary").map(tag => tag.tagFQN).join(", ") || "연결된 용어 없음";
    } else current = "업무 의미 탭에서 기존 승인·초안 연결과 비교하세요.";
  }
  const proposed = String(item.proposed_value.description ?? item.proposed_value.glossary_term_fqn ?? item.proposed_value.ontology_stable_key ?? JSON.stringify(item.proposed_value));
  const hasSnapshot = item.suggestion_type === "description" && Object.hasOwn(item.proposed_value, "source_description");
  const version = item.proposed_value.source_version;
  const changed = !!matched && version != null && currentTable.reference.version != null && Number(version) !== currentTable.reference.version;
  return <section aria-label="변경 비교">
    <div className="suggestion-comparison">
      <div><span>현재 값 · 조회 시점 기준</span><p>{current}</p>{matched && currentTable.reference.version != null && <small>현재 버전 {currentTable.reference.version}</small>}</div>
      <div><span>제안 값</span><p>{proposed}</p></div>
      {hasSnapshot && <div><span>제안 당시 값 · 근거</span><p>{String(item.proposed_value.source_description || "설명 없음")}</p>{version != null && <small>근거 버전 {String(version)}</small>}</div>}
    </div>
    {changed && <p className="review-error" role="status">제안 생성 후 자산 버전이 변경됐습니다. 현재 값과 근거를 다시 검토하세요. 승인 시 서버에서 최신 상태를 재검증합니다.</p>}
    <p className="review-scope-note">현재 값은 조회 시점의 정보입니다. 제안 당시 근거와 구분해 검토하세요.</p>
    {currentTable?.reference.fully_qualified_name && <Link to={`/admin/data-catalog/assets/${encodeURIComponent(currentTable.reference.fully_qualified_name)}?tab=governance`}>최신 자산 확인·재분석</Link>}
  </section>;
}
