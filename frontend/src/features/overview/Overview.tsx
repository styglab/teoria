import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { metadataApi, type MetadataStatus } from "../../api/metadata";
import { suggestionApi, type IntelligenceSuggestion } from "../../api/suggestions";
import { PageHeader } from "../../components/workspace/WorkspaceLayout";
import { useAdminAccess } from "../access/AdminAccess";
export function Overview() {
 const [status,setStatus]=useState<MetadataStatus|null>(null);
 const [total,setTotal]=useState<number|null>(null);
 const [items,setItems]=useState<IntelligenceSuggestion[]|null>(null);
 const [errors,setErrors]=useState<string[]>([]);
 const {principal,requestLogin}=useAdminAccess();
 useEffect(()=>{
  let active=true;
  const fail=(label:string)=>{if(active)setErrors(values=>[...values,label])};
  metadataApi.metadataStatus().then(value=>{if(active)setStatus(value)}).catch(()=>fail("메타데이터 연결 상태 조회 실패"));
  metadataApi.metadataTables({limit:1}).then(value=>{if(active)setTotal(value.total)}).catch(()=>fail("자산 수 조회 실패"));
  return()=>{active=false};
 },[]);
 useEffect(()=>{
  let active=true;setItems(null);
  if(principal)suggestionApi.intelligenceSuggestions().then(value=>{if(active)setItems(value.items)}).catch(()=>{if(active)setErrors(values=>[...values,"검토 이력 조회 실패"])});
  return()=>{active=false};
 },[principal]);
 const pending=items?.filter(item=>item.status==="pending");
 const failed=items?.filter(item=>item.status==="failed");
 return <div className="workspace-page">
 <PageHeader title="현황" description="메타데이터 연결 상태와 검토할 작업을 한눈에 확인합니다." actions={<Link className="page-primary-link" to="/admin/data-catalog">데이터 자산 탐색 →</Link>}/>
 <div className="overview-grid">
 <Link to="/admin/operations" className="overview-stat"><span>메타데이터 연결</span><strong>{status?status.available?"정상":status.enabled?"연결 확인 필요":"미설정":"확인 중"}</strong><small>OpenMetadata 실시간 상태</small></Link>
 <Link to="/admin/data-catalog" className="overview-stat"><span>등록된 데이터 자산</span><strong>{total===null?"—":total.toLocaleString("ko-KR")}</strong><small>OpenMetadata 테이블</small></Link>
 <Link to="/admin/changes/review" className="overview-stat"><span>검토 대기</span><strong>{pending?.length??"—"}</strong><small>{principal?"조회된 제안 기준":"관리자 연결 후 확인"}</small></Link>
 <Link to="/admin/changes/review?status=failed" className="overview-stat"><span>적용 실패</span><strong>{failed?.length??"—"}</strong><small>{principal?"조회된 제안 기준":"관리자 연결 후 확인"}</small></Link>
 </div>
 {errors.map(message=><p role="alert" className="workspace-error" key={message}>{message}</p>)}
 <div className="overview-columns"><section className="workspace-card"><h3>주요 작업</h3><Link to="/admin/data-catalog"><strong>데이터 자산 확인</strong><span>기술·운영·의미·거버넌스 메타데이터 조회</span></Link><Link to="/admin/semantic-model/ontology"><strong>의미 모델 관리</strong><span>업무 개념과 관계를 검토하고 버전으로 게시</span></Link><Link to="/admin/governance"><strong>메타데이터 공백 확인</strong><span>설명·소유자·분류가 필요한 자산 확인</span></Link><Link to="/admin/changes/review"><strong>제안 검토 및 적용</strong><span>대상과 근거를 확인하고 변경 승인</span></Link></section>
 <section className="workspace-card"><h3>최근 변경 제안</h3>{!principal?<><p>관리자 연결 후 검토·적용 이력을 확인할 수 있습니다.</p><button onClick={requestLogin}>관리자 연결</button></>:items===null?<p>이력을 조회하고 있습니다…</p>:!items.length?<p>등록된 제안이 없습니다.</p>:[...items].sort((a,b)=>b.created_at.localeCompare(a.created_at)).slice(0,5).map(item=><Link key={item.suggestion_id} to={`/admin/changes/review?suggestion=${encodeURIComponent(item.suggestion_id)}`}><strong>{item.target_ref}</strong><span>{item.suggestion_type} · {item.status} · {new Date(item.created_at).toLocaleString("ko-KR")}</span></Link>)}</section></div>
 </div>;
}
export function OperationsSettings() {
 const {principal,requestLogin}=useAdminAccess();
 const [status,setStatus]=useState<MetadataStatus|null>(null);
 const [error,setError]=useState<string|null>(null);
 useEffect(()=>{let active=true;metadataApi.metadataStatus().then(value=>{if(active)setStatus(value)}).catch(reason=>{if(active)setError((reason as Error).message)});return()=>{active=false}},[]);
 return <div className="workspace-page"><PageHeader title="연결 및 수집" description="메타데이터 연결과 수집 실행 상태를 확인합니다."/><div className="overview-columns">
 <section className="workspace-card"><h3>메타데이터 연결</h3>{error?<p role="alert">{error}</p>:<><p>OpenMetadata · {status?status.available?"정상 연결":"연결 확인 필요":"확인 중"}</p><p>데이터 서비스: {status?.database_service||"—"}</p>{status?.reason&&<p>{status.reason}</p>}</>}<p>자산·설명·소유자·태그·용어의 원천은 OpenMetadata입니다.</p><a href={`${window.location.protocol}//${window.location.hostname}:8585`} target="_blank" rel="noreferrer">OpenMetadata 열기 ↗</a></section>
 <section className="workspace-card"><h3>수집 운영</h3><p>스케줄·실행·실패 로그는 Prefect에서 확인합니다.</p><p>Teoria 자산 상세에는 연결된 파이프라인의 적재 기록을 표시합니다.</p><a href="/prefect/" target="_blank" rel="noreferrer">Prefect 열기 ↗</a></section>
 <section className="workspace-card"><h3>현재 접근</h3><p>{principal?`관리자: ${principal.actor}`:"조회 모드 · 메타데이터 조회 가능"}</p>{principal?<p>역할: {principal.roles.join(", ")}</p>:<button onClick={requestLogin}>관리자 연결</button>}</section></div></div>;
}
