import type { IntelligenceSuggestion, MetadataTableDetail } from "../../api/admin";
export function SuggestionComparison({item,table}:{item:IntelligenceSuggestion;table:MetadataTableDetail|null}) {
 if(!["description","glossary_term_assignment","binding"].includes(item.suggestion_type))return null;
 const fqn=String(item.proposed_value.fully_qualified_name||item.target_ref.replace(/^openmetadata:\/\/(column|table)\//,""));
 const column=table?.columns.find(value=>value.fullyQualifiedName===fqn||`${table.reference.fully_qualified_name}.${value.name}`===fqn);
 const tableTarget=table?.reference.fully_qualified_name===fqn||item.target_ref===`openmetadata://table/${table?.reference.entity_id}`;
 let current="자산 상세에서 최신 값을 확인하세요.";
 if(table&&(column||tableTarget)) {
  if(item.suggestion_type==="description")current=String(column?column.description||"설명 없음":table.description||"설명 없음");
  else if(item.suggestion_type==="glossary_term_assignment") {
   const tags=(column?.tags||table.tags) as Array<{tagFQN?:string;source?:string}>;
   current=tags.filter(tag=>tag.source==="Glossary").map(tag=>tag.tagFQN).join(", ")||"연결된 용어 없음";
  } else current="업무 의미 탭에서 기존 승인·초안 연결과 비교하세요.";
 }
 const proposed=String(item.proposed_value.description||item.proposed_value.glossary_term_fqn||item.proposed_value.ontology_stable_key||JSON.stringify(item.proposed_value));
 return <section className="suggestion-comparison" aria-label="변경 비교"><div><span>현재 값 · 조회 시점 기준</span><p>{current}</p></div><div><span>제안 값</span><p>{proposed}</p></div></section>;
}
