import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Check, ChevronDown, CircleAlert, FileText, X } from "lucide-react";
import { adminApi, type IntelligenceSuggestion, type MetadataTableDetail } from "../../api/admin";
import { FilterTabs, PageHeader } from "../../components/workspace/WorkspaceLayout";
import { SuggestionComparison } from "./SuggestionComparison";
import { SuggestionApplicationHistory } from "./SuggestionApplicationHistory";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../components/ui/card";

const TYPE_LABELS: Record<string, string> = {
  description: "설명",
  binding: "의미 연결",
  glossary_term: "업무 용어",
  glossary_term_assignment: "업무 용어 할당",
  ontology_change: "온톨로지 변경",
  test_suite: "품질 검사 묶음",
  quality_test: "품질 검사",
};

const STATUS_LABELS: Record<string, string> = {
  pending: "검토 대기", approved: "승인됨", rejected: "거절됨",
  changes_requested: "수정 요청", applied: "적용 완료", failed: "적용 실패",
};

function targetName(item: IntelligenceSuggestion) {
  return item.proposed_value.column_name
    ?? item.target_ref.split("/").at(-1)?.split(".").at(-1)
    ?? item.target_ref;
}

function applicationEffect(item: IntelligenceSuggestion) {
  if (item.suggestion_type === "description") return `승인하면 OpenMetadata ${item.target_type === "openmetadata_table" ? "테이블" : "컬럼"} 설명에 반영됩니다.`;
  if (item.suggestion_type === "binding") return "승인하면 Teoria Binding Draft가 생성됩니다.";
  if (item.suggestion_type === "ontology_change") return "승인하면 새 Ontology Draft에만 반영됩니다.";
  if (item.suggestion_type === "glossary_term_assignment") return "승인하면 OpenMetadata 컬럼에 용어가 할당됩니다.";
  if (item.suggestion_type === "glossary_term") return "승인하면 OpenMetadata Glossary Term이 생성됩니다.";
  if (item.suggestion_type === "test_suite") return "승인하면 OpenMetadata Test Suite가 생성됩니다.";
  if (item.suggestion_type === "quality_test") return "승인하면 OpenMetadata Test Case가 생성됩니다.";
  return "승인 후 유형별 application service가 실행됩니다.";
}

function draftLink(item: IntelligenceSuggestion): { to: string; label: string } | null {
  const application = item.application;
  if (!application?.effect_succeeded_at) return null;
  const ref = application.external_change_ref;
  const binding = ref?.match(/^teoria:\/\/binding\/([0-9a-f-]{36})$/i);
  if (binding) return { to: `/admin/semantic-model/bindings?binding=${encodeURIComponent(binding[1])}`, label: "생성된 Binding 검토" };
  const ontology = ref?.match(/^teoria:\/\/ontology\/draft\/([0-9a-f-]{36})$/i);
  if (ontology) return { to: `/admin/semantic-model/ontology?version=${encodeURIComponent(ontology[1])}`, label: "생성된 Ontology 초안 검토" };
  return null;
}

const ACTION_MESSAGES = {
  wait: "적용이 진행 중입니다. 완료 후 새로고침하세요.",
  retry: "변경을 시작하지 못했습니다. 기존 승인으로 다시 적용할 수 있습니다.",
  reconcile: "변경이 시작된 기록이 있습니다. 다시 쓰기 전에 기존 적용 결과를 확인하세요.",
  reanalyze: "원천이 제안 생성 후 변경됐습니다. 자산을 다시 분석해 새 제안을 제출하세요.",
};

const ERROR_MESSAGES: Record<string, string> = {
  stale_evidence: "제안의 근거보다 원천 자산이 변경됐습니다. 최신 정보로 새 제안을 제출하세요.",
  application_in_progress: "다른 실행이 적용 중입니다. 완료 후 새로고침하세요.",
  application_reconciliation_required: "외부 변경이 이미 시작됐을 수 있습니다. 기존 적용 결과를 먼저 확인하세요.",
  application_claim_lost: "이 시도의 실행권이 만료되거나 변경됐습니다. 현재 상태를 새로고침하세요.",
  openmetadata_unavailable: "OpenMetadata 연결 상태를 확인하세요.",
};

function proposalSummary(item: IntelligenceSuggestion) {
  if (item.proposed_value.description) return String(item.proposed_value.description);
  if (item.proposed_value.ontology_stable_key) return `추천 개념: ${item.proposed_value.ontology_stable_key}`;
  const testCase = item.proposed_value.test_case as Record<string, unknown> | undefined;
  if (testCase) {
    const definition = String(testCase.testDefinition ?? "quality test");
    const parameters = Array.isArray(testCase.parameterValues)
      ? testCase.parameterValues.map((value) => {
          const parameter = value as { name?: string; value?: unknown };
          return `${parameter.name}: ${String(parameter.value)}`;
        }).join(", ")
      : "";
    return `${definition}${parameters ? ` (${parameters})` : ""}`;
  }
  return JSON.stringify(item.proposed_value, null, 2);
}

export function SuggestionReview() {
  const [params, setParams]=useSearchParams();
  const asset=params.get("asset");
  const assetId=params.get("assetId");
  const selectedId=params.get("suggestion");
  const requestedStatus=params.get("status");
  const [table,setTable]=useState<MetadataTableDetail|null>(null);
  const [items, setItems] = useState<IntelligenceSuggestion[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const filter = selectedId ? "all" : requestedStatus && (requestedStatus === "all" || Object.hasOwn(STATUS_LABELS, requestedStatus)) ? requestedStatus : "pending";
  const scope = `${assetId || ""}:${selectedId || ""}:${filter}`;
  const [pagination, setPagination] = useState<{ scope: string; cursors: (string | undefined)[]; index: number }>({ scope, cursors: [undefined], index: 0 });
  const page = pagination.scope === scope ? pagination : { scope, cursors: [undefined], index: 0 };
  const cursor = page.cursors[page.index];
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [refresh, setRefresh] = useState(0);
  const setFilter = (status: string) => setParams(previous => {
    const next = new URLSearchParams(previous);
    next.set("status", status); next.delete("suggestion");
    return next;
  });
  useEffect(()=>{
    let active=true;setTable(null);
    if(asset)adminApi.metadataTable(asset).then(value=>{if(active)setTable(value)}).catch(()=>{});
    return()=>{active=false};
  },[asset]);
  useEffect(() => { setError(null); }, [scope]);
  useEffect(() => {
    let active = true;
    setLoading(true); setItems([]); setNextCursor(null);
    const fetchItems = selectedId
      ? adminApi.intelligenceSuggestion(selectedId).then(item => ({ items: [item], next_cursor: null }))
      : adminApi.suggestionPage(filter === "all" ? undefined : filter, cursor, assetId || undefined);
    fetchItems.then(value => { if (active) { setItems(value.items); setNextCursor(value.next_cursor); } })
      .catch((reason: Error) => { if (active) setError(reason.message); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [assetId, selectedId, filter, cursor, refresh]);

  const act = async (id: string, action: "approve" | "reject" | "retry" | "reconcile") => {
    setBusy(id); setError(null);
    try {
      if (action === "retry") await adminApi.retrySuggestionApplication(id);
      else if (action === "reconcile") await adminApi.reconcileSuggestionApplication(id);
      else await adminApi.reviewSuggestion(id, action);
    }
    catch (reason) { setError((reason as Error).message); }
    finally { setBusy(null); setRefresh(value => value + 1); }
  };

  return <div className="review-queue">
    {asset&&<div className="context-banner"><span>선택한 자산: <strong>{asset}</strong></span><Link to={`/admin/data-catalog/assets/${encodeURIComponent(asset)}?tab=governance`}>자산으로 돌아가기</Link><Link to="/admin/changes/review">범위 해제</Link></div>}
    {!selectedId && <p className="review-scope-note">선택한 상태의 제안을 페이지당 최대 50개씩 조회합니다.</p>}
    <PageHeader title="제안 검토" description="변경 내용과 근거를 확인하고, 적용 결과와 복구 이력을 검토합니다." actions={<Button size="sm" variant="outline" disabled={loading || !!busy} onClick={() => { setError(null); setRefresh(value => value + 1); }}>새로고침</Button>}><div className="page-header-meta"><span>{items.length}개 · 현재 페이지</span></div></PageHeader>
    <FilterTabs label="Suggestion 상태 필터" items={[...Object.entries(STATUS_LABELS).map(([id,label]) => ({id,label})), {id:"all",label:"모든 상태"}]} value={filter} disabled={!!busy} onChange={setFilter}/>

    {error && <div className="review-error"><CircleAlert size={16} />{error}</div>}
    {loading ? <p role="status">제안을 조회하고 있습니다…</p> : !error && !items.length ? <div className="review-empty"><Check size={28} /><h3>이 페이지에 제안이 없습니다</h3><p>상태를 바꾸거나 이전 페이지를 확인하세요.</p></div> : <div className="review-list">
      {items.map((item) => <Card className="review-card" key={item.suggestion_id}>
        <CardHeader className="review-card-header">
          <div className="review-card-title">
            <div className="review-badges">
              <Badge variant="outline">{TYPE_LABELS[item.suggestion_type] ?? item.suggestion_type}</Badge>
              <Badge variant={item.status === "applied" ? "success" : item.status === "failed" || item.status === "rejected" ? "destructive" : item.status === "pending" ? "warning" : "default"}>{STATUS_LABELS[item.status] ?? item.status}</Badge>
              <Badge variant="outline">신뢰도 {Math.round(item.confidence * 100)}%</Badge>
              <Badge variant={item.risk_level === "high" ? "destructive" : item.risk_level === "medium" ? "warning" : "outline"}>위험도 {{ low: "낮음", medium: "보통", high: "높음" }[item.risk_level]}</Badge>
            </div>
            <CardTitle>{targetName(item)}</CardTitle>
            <CardDescription>{item.target_ref}</CardDescription>
          </div>
        </CardHeader>
        <CardContent>
          <div className="review-effect"><CircleAlert size={15} /><span>{applicationEffect(item)}</span></div>
          {item.application && <section className="review-rationale" aria-label="적용 상태">
            <span>적용 시도 {item.application.attempts}회</span>
            {item.application.error_code && <p>실패 원인: <code>{item.application.error_code}</code></p>}
            {item.application.error_code && <p>{ERROR_MESSAGES[item.application.error_code] ?? "원인을 확인한 뒤 아래 복구 안내에 따라 진행하세요."}</p>}
            {item.application.attempted_at && <p>최근 시도: {new Date(item.application.attempted_at).toLocaleString("ko-KR")}</p>}
            {item.application.effect_started_at && <p>대상 변경 시작: {new Date(item.application.effect_started_at).toLocaleString("ko-KR")}</p>}
            {item.application.effect_succeeded_at && <p>대상 변경 성공 기록: {new Date(item.application.effect_succeeded_at).toLocaleString("ko-KR")}</p>}
            {item.application.external_change_ref && <p>결과 참조: <code>{item.application.external_change_ref}</code></p>}
          </section>}
          {item.next_action && item.next_action !== "none" && <p>{ACTION_MESSAGES[item.next_action]}</p>}
          {draftLink(item) && <p><Link to={draftLink(item)!.to}>{draftLink(item)!.label}</Link><small> · 초안의 별도 검토·승인이 필요합니다.</small></p>}
          <SuggestionComparison item={item} table={table} />
          {item.application && <SuggestionApplicationHistory key={`${item.suggestion_id}:${refresh}`} id={item.suggestion_id} />}
          <section className="review-proposal">
            <span>제안 내용</span>
            <p>{proposalSummary(item)}</p>
          </section>
          {item.rationale && <section className="review-rationale"><span>판단 근거</span><p>{item.rationale}</p></section>}
          {!!item.proposed_value.alternatives?.length && <p className="review-alternatives">다른 후보: {item.proposed_value.alternatives.map((candidate) => `${candidate.stable_key} ${Math.round(candidate.score * 100)}%`).join(" · ")}</p>}
          {!!item.evidence?.length && <details className="review-evidence">
            <summary><FileText size={14} /> 근거 {item.evidence.length}개 <ChevronDown size={14} /></summary>
            <div>{item.evidence.map((evidence) => <article key={evidence.evidence_id}>
              <Badge variant="outline">{evidence.evidence_type}</Badge>
              <code>{evidence.source_ref}</code>
              {evidence.excerpt && <p>{evidence.excerpt}</p>}
            </article>)}</div>
          </details>}
          <footer className="review-card-footer">
            <small>{item.submitted_by&&<>제출 {item.submitted_by} · </>}{item.model_provider}/{item.model_name} · {new Date(item.created_at).toLocaleString("ko-KR")}</small>
            {["pending", "changes_requested"].includes(item.status) && <div>
              <Button variant="outline" disabled={!!busy} onClick={() => act(item.suggestion_id, "reject")}><X size={14} /> 거절</Button>
              <Button disabled={!!busy} onClick={() => act(item.suggestion_id, "approve")}><Check size={14} /> {["binding", "ontology_change"].includes(item.suggestion_type) ? "승인하고 Draft 생성" : "승인하고 반영"}</Button>
            </div>}
            {item.next_action === "retry" && <Button disabled={!!busy} onClick={() => act(item.suggestion_id, "retry")}>기존 승인으로 다시 적용</Button>}
            {item.next_action === "reconcile" && <Button disabled={!!busy} onClick={() => act(item.suggestion_id, "reconcile")}>기존 적용 결과 확인</Button>}
          </footer>
        </CardContent>
      </Card>)}
    </div>}
    {!selectedId && <nav className="review-filters" aria-label="제안 페이지 이동">
      <Button variant="outline" disabled={loading || !!busy || page.index === 0} onClick={() => { setError(null); setPagination({ ...page, index: page.index - 1 }); }}>이전 페이지</Button>
      <span>{page.index + 1} 페이지</span>
      <Button variant="outline" disabled={loading || !!busy || !nextCursor} onClick={() => { setError(null); setPagination({ scope, cursors: [...page.cursors.slice(0, page.index + 1), nextCursor!], index: page.index + 1 }); }}>다음 페이지</Button>
    </nav>}
  </div>;
}
