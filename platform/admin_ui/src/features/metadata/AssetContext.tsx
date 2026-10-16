import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { metadataApi, type AssetContextResult } from "../../api/metadata";

const statuses: Record<string, string> = {completed:"완료", running:"실행 중", failed:"실패", approved:"승인", draft:"초안", deprecated:"사용 종료", rejected:"거절", pending:"검토 대기", applied:"적용 완료", changes_requested:"수정 요청", applying:"적용 중"};
const date = (value: unknown) => value ? new Date(String(value)).toLocaleString("ko-KR") : "기록 없음";
const state = (value: unknown) => value ? (statuses[String(value)] ?? String(value)) : "실행 기록 없음";
const missing = (status: string) => status === "not_linked" ? "명시적으로 연결된 수집 파이프라인이 없습니다." : status === "unconfigured" ? "조회 연결이 설정되지 않았습니다." : "원천 정보를 조회할 수 없습니다. 다른 영역은 계속 확인할 수 있습니다.";

export function AssetContext({ tableId, section = "all" }: { tableId: string; section?: string }) {
  const [context, setContext] = useState<AssetContextResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lineage, setLineage] = useState<Record<string, unknown> | null>(null);
  const [lineageError, setLineageError] = useState<string | null>(null);
  const lineageRequest = useRef(0);
  useEffect(() => {
    let active = true;
    setContext(null); setError(null);
    setLineage(null);
    setLineageError(null);
    metadataApi.assetContext(tableId).then(value => { if (active) setContext(value); }).catch(reason => { if (active) setError((reason as Error).message); });
    return () => { active = false; ++lineageRequest.current; };
  }, [tableId]);
  const loadLineage = async () => {
    const request = ++lineageRequest.current;
    setLineage(null); setLineageError(null);
    try { const value = await metadataApi.metadataLineage(tableId); if (request === lineageRequest.current) setLineage(value); }
    catch (reason) { if (request === lineageRequest.current) setLineageError((reason as Error).message); }
  };
  if (error) return <section className="asset-context"><p role="alert">통합 정보 조회 실패: {error}</p></section>;
  if (!context) return <section className="asset-context" aria-busy="true">통합 메타데이터를 조회하고 있습니다…</section>;
  const business = context.business.data;
  return <section className="asset-context">
    {section === "all" && <header><h3>통합 메타데이터</h3><small>조회 시각 {date(context.observed_at)}</small></header>}
    <div className={section === "all" ? "asset-context-grid" : "asset-context-single"}>
      {(section === "all" || section === "technical") && <article><h4>개요 · OpenMetadata</h4><p>{context.technical.columns.length}개 컬럼 · {String(context.technical.database_schema?.name ?? "스키마 정보 없음")}</p><p>{context.technical.description || "테이블 설명이 없습니다."}</p></article>}
      {(section === "all" || section === "operations") && <article><h4>운영 · 수집 적재 기록</h4>{context.operations.status !== "available" ? <p>{missing(context.operations.status)}</p> : context.operations.data?.map(run => <div className="asset-context-item" key={run.pipeline_id}><strong>{run.pipeline_id}</strong><p>{state(run.status)} · 마지막 성공 {date(run.last_success_at)}</p><p>최근 실행 범위 {run.window_start ?? "—"} ~ {run.window_end ?? "—"}</p><p>체크포인트 {run.cursor_date ?? "없음"} · 갱신 {date(run.checkpoint_updated_at)}</p>{run.error_code && <p>오류: {run.error_code}</p>}</div>)}<small>적재 기록은 전체 과거 수집의 완전성을 보장하지 않습니다. 스케줄·작업 로그는 Prefect에서 확인하세요.</small></article>}
      {(section === "all" || section === "business") && <article><h4>의미 · 용어와 온톨로지</h4><p>용어: {context.business.glossary_terms.join(" · ") || "연결된 용어 없음"}</p>{context.business.status !== "available" ? <p>{missing(context.business.status)}</p> : <>{business?.bindings.length ? business.bindings.map(binding => <div className="asset-context-item" key={binding.binding_id}><strong>{binding.namespace} · {binding.stable_key}</strong><p>{binding.fully_qualified_name} · {state(binding.status)}</p><small>{binding.entity_type === "glossaryTerm" ? "용어를 통한 의미 연결" : "자산 직접 의미 연결"}</small></div>) : <p>연결된 온톨로지 연결이 없습니다.</p>}{business?.bindings_truncated && <p>최근 50개 연결을 표시합니다.</p>}</>}<Link to={`/admin/semantic-model/bindings?${new URLSearchParams({asset:context.technical.reference.fully_qualified_name||"",assetId:tableId})}`}>의미 연결 관리</Link></article>}
      {(section === "all" || section === "governance") && <article><h4>거버넌스 · 소유자·태그·검토</h4><p>소유자: {context.technical.owners.map(o => String(o.displayName ?? o.name ?? o.id)).join(" · ") || "미지정"}</p><p>태그: {context.technical.tags.map(t => String(t.tagFQN)).join(" · ") || "없음"}</p>{context.business.status !== "available" ? <p>{missing(context.business.status)}</p> : business?.suggestions.length ? business.suggestions.map(s => <div className="asset-context-item" key={s.suggestion_id}><strong>{s.suggestion_type} · {state(s.status)}</strong><p>{s.target_ref}</p><small>최근 검토 {s.reviewer ?? "없음"} · {date(s.reviewed_at)}{s.application_status && ` · 적용 ${state(s.application_status)}`}</small></div>) : <p>이 자산에 대한 제안·검토 기록이 없습니다.</p>}{business?.suggestions_truncated && <p>최근 50개 제안을 표시합니다.</p>}<Link to={`/admin/changes/review?${new URLSearchParams({asset:context.technical.reference.fully_qualified_name||"",assetId:tableId})}`}>변경 제안 검토</Link></article>}
      {section === "lineage" && <article><h4>계보 · OpenMetadata</h4><p>이 자산의 물리적 상류·하류 연결을 원천에서 조회합니다.</p><button onClick={loadLineage}>계보 불러오기</button>{lineageError && <p role="alert">계보 조회 실패: {lineageError}</p>}{lineage && <p>노드 {Array.isArray(lineage.nodes) ? lineage.nodes.length : 0}개 · 상류 연결 {Array.isArray(lineage.upstreamEdges) ? lineage.upstreamEdges.length : 0}개 · 하류 연결 {Array.isArray(lineage.downstreamEdges) ? lineage.downstreamEdges.length : 0}개</p>}</article>}
    </div>
    {section !== "all" && <footer className="asset-context-observed"><small>조회 시각 {date(context.observed_at)}</small></footer>}
  </section>;
}
