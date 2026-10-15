import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { ChevronDown, Play, Search } from "lucide-react";
import { adminApi, type AssessmentScope, type AssetAssessment, type MetadataTableDetail } from "../../api/admin";
import { useAdminAccess } from "../access/AdminAccess";
import "./asset_assessment.css";

const scopes: Array<[AssessmentScope,string]> = [
  ["metadata_enrichment","메타데이터 정비"], ["semantic_alignment","업무 의미 연결"], ["disclosure_assessment","개방 적합성 진단"],
];
const scopeDescriptions:Record<AssessmentScope,string>={metadata_enrichment:"테이블·컬럼 설명 보완",semantic_alignment:"기존 업무 개념과 연결",disclosure_assessment:"법령 근거와 개방 조건 검토"};
const labels = {queued:"대기 중",running:"진단 중",completed:"진단 완료",partial:"일부 확인 필요",failed:"진단 실패"};
const recommendations:Record<string,string>={review_required:"추가 검토 필요",withhold_raw:"원문 개방 보류 권고",transform_and_reassess:"가공 후 재검토 권고",candidate:"개방 후보 (최종 검토 필요)"};
const errors:Record<string,string> = {
  asset_assessment_not_configured:"진단 모델과 Worker 설정이 필요합니다.",
  stale_evidence:"진단 중 원천 자산이 변경됐습니다. 최신 자산으로 다시 진단하세요.",
  model_unavailable:"진단 모델에 연결하지 못했습니다.", model_output_invalid:"모델 결과가 제안 형식에 맞지 않습니다.",
  select_up_to_30_columns:"첫 버전은 한 번에 30개 컬럼까지 진단합니다. 대상 컬럼을 선택하세요.",
};

export function AssetAssessmentPanel({detail}:{detail:MetadataTableDetail}) {
  const {principal,requestLogin}=useAdminAccess();
  const [selected,setSelected]=useState<AssessmentScope[]>(["metadata_enrichment","semantic_alignment"]);
  const [columns,setColumns]=useState<string[]>([]);
  const [columnQuery,setColumnQuery]=useState("");
  const [disclosureContext,setDisclosureContext]=useState<"public_release"|"restricted_sharing">("public_release");
  const [items,setItems]=useState<AssetAssessment[]>([]);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState<string|null>(null);
  const requestVersion=useRef(0);
  const hasActive=items.some(item=>item.status==="queued"||item.status==="running");
  useEffect(()=>{
    if(!principal)return;
    let active=true;
    let timer:ReturnType<typeof setTimeout>;
    const load=async()=>{
      const version=requestVersion.current;
      try {
        const result=await adminApi.assetAssessments(detail.reference.entity_id);
        if(!active||version!==requestVersion.current)return;
        setItems(result.items);
        if(result.items.some(item=>item.status==="queued"||item.status==="running"))timer=setTimeout(load,3000);
      } catch(reason){if(active)setError((reason as Error).message)}
    };
    void load();
    return()=>{active=false;clearTimeout(timer)};
  },[principal?.actor,detail.reference.entity_id,hasActive]);

  const start=async()=>{
    if(!principal){requestLogin();return}
    setBusy(true);setError(null);
    requestVersion.current+=1;
    try {
      const item=await adminApi.createAssetAssessment({table_fqn:detail.reference.fully_qualified_name!,
        scopes:selected,column_names:columns,disclosure_context:disclosureContext});
      setItems(previous=>[item,...previous.filter(old=>old.assessment_id!==item.assessment_id)].slice(0,10));
    }catch(reason){
      const message=(reason as Error).message;
      setError(Object.entries(errors).find(([key])=>message.includes(key))?.[1]||message);
    }finally{setBusy(false)}
  };
  const visibleColumns=detail.columns.filter(column=>column.name.toLocaleLowerCase().includes(columnQuery.trim().toLocaleLowerCase()));
  return <section className="assessment-panel" aria-label="자동 자산 진단">
    <p className="assessment-intro">선택한 항목을 진단해 변경안을 제안합니다. 검토·승인 후 반영됩니다.</p>
    <fieldset className="assessment-scopes" disabled={busy}><legend>진단 항목</legend><div className="assessment-scope-grid">{scopes.map(([id,label])=><label className={`assessment-scope${selected.includes(id)?" is-selected":""}`} key={id}>
      <input type="checkbox" aria-label={label} checked={selected.includes(id)} onChange={event=>setSelected(previous=>event.target.checked?[...previous,id]:previous.filter(value=>value!==id))}/><span><strong>{label}</strong><small>{scopeDescriptions[id]}</small></span>
    </label>)}</div></fieldset>
    <details className="assessment-column-picker"><summary><span>대상 컬럼 선택 <small>최대 30개</small></span><span className="assessment-picker-count">{columns.length?`${columns.length}개 선택`:detail.columns.length>30?"선택 필요":"전체 컬럼"}</span><ChevronDown size={15} aria-hidden="true"/></summary>
      <div className="assessment-picker-body"><div className="assessment-picker-toolbar"><label className="assessment-column-search"><Search size={15} aria-hidden="true"/><input aria-label="진단 대상 컬럼 검색" placeholder="컬럼 이름 검색" value={columnQuery} onChange={event=>setColumnQuery(event.target.value)}/></label><button type="button" disabled={!columns.length||busy} onClick={()=>setColumns([])}>선택 초기화</button></div>
      <div className="assessment-column-options" role="group" aria-label="대상 컬럼">{visibleColumns.map(column=><label key={column.name}>
        <input type="checkbox" aria-label={column.name} checked={columns.includes(column.name)} disabled={busy||(!columns.includes(column.name)&&columns.length>=30)} onChange={event=>setColumns(previous=>event.target.checked?[...previous,column.name]:previous.filter(name=>name!==column.name))}/><span>{column.name}</span>
      </label>)}{!visibleColumns.length&&<p>검색 결과가 없습니다.</p>}</div><p className="assessment-note">미선택 시 전체 컬럼을 진단합니다. 원본 샘플 데이터는 사용하지 않습니다.</p></div>
    </details>
    {selected.includes("disclosure_assessment")&&<div className="assessment-disclosure"><label>개방 상황<select value={disclosureContext} onChange={event=>setDisclosureContext(event.target.value as typeof disclosureContext)}><option value="public_release">일반 공개</option><option value="restricted_sharing">제한된 대상에게 제공</option></select></label><p>법령 근거를 포함한 검토 초안이며, 태그는 자동 적용되지 않습니다.</p></div>}
    <div className="assessment-run-row"><p className="assessment-note">{!columns.length&&detail.columns.length>30?"진단할 컬럼을 선택하세요. 한 번에 최대 30개까지 가능합니다.":`${selected.length}개 진단 항목 · ${columns.length||detail.columns.length}개 컬럼`}</p><button className="assessment-run-button" disabled={busy||!selected.length||columns.length>30||(!columns.length&&detail.columns.length>30)} onClick={start}><Play size={14} aria-hidden="true"/>{busy?"진단 요청 중…":"진단 실행"}</button></div>
    {error&&<p className="assessment-error" role="alert">{error}</p>}
    {!!items.length&&<div className="assessment-results"><h4 className="assessment-results-title">최근 진단</h4>{items.map(item=><article className="assessment-result" key={item.assessment_id}>
      <header><h4>{labels[item.status]} · 제안 {item.suggestion_ids.length}건</h4><span className="assessment-status" data-status={item.status}>{labels[item.status]}</span></header>
      <p className="assessment-result-meta">{new Date(item.created_at).toLocaleString()} · {item.model_name}{item.assessment_date&&` · 평가 기준일 ${item.assessment_date}`}</p>
      {item.error_code&&<p className="assessment-error" role="alert">{errors[item.error_code]||`진단을 완료하지 못했습니다 (${item.error_code}). 새 진단을 요청할 수 있습니다.`}</p>}
      {!!item.suggestion_ids.length&&<div className="assessment-result-links">{item.suggestion_ids.map(id=><Link key={id} to={`/admin/changes/review?suggestion=${encodeURIComponent(id)}`}>변경 제안 검토 · {id.slice(0,8)}</Link>)}</div>}
      {item.findings.map((finding,index)=><details className="assessment-finding" key={index}><summary><span>{finding.column_name||"검토 사항"}</span><ChevronDown size={14} aria-hidden="true"/></summary><div className="assessment-finding-body"><p>{finding.summary}</p>
        {finding.information_type&&<p>정보 유형 후보: {finding.information_type}</p>}
        {finding.internal_processing&&<p>내부 처리: {finding.internal_processing==="review_required"?"처리 근거 검토 필요":"평가하지 않음"}</p>}
        {finding.disclosure_recommendation&&<p>외부 개방: {recommendations[finding.disclosure_recommendation]||"추가 검토 필요"} · AI 검토 초안</p>}
        {finding.protection_recommendation&&<p>보호조치 권고: {finding.protection_recommendation}</p>}
        {!!finding.tag_candidates?.length&&<p>미검증 태그 후보: {finding.tag_candidates.join(", ")}</p>}
        {finding.evidence?.map((evidence,i)=><p key={i}><code>{evidence.source_ref}</code>{evidence.provenance?.law_name&&` · ${evidence.provenance.law_name} · 시행일 ${evidence.provenance.effective_date}`}</p>)}
      </div></details>)}
    </article>)}</div>}
  </section>;
}
