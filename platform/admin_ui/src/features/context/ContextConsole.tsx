import { useState, type FormEvent } from "react";
import { AlertTriangle, ArrowRight, CheckCircle2, Database, Play, Route } from "lucide-react";
import { adminApi, type ContextQueryResult } from "../../api/admin";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../components/ui/card";

const EXAMPLES = [
  "근로복지공단의 최근 5년 계약금액을 알려줘",
  "최근 30일 동안 게시된 용역 입찰공고를 찾아줘",
  "추정가격 1억 원 이상인 소프트웨어 관련 공고를 찾아줘",
  "근로복지공단이 게시한 현재 접수 중인 입찰공고를 찾아줘",
];

export function ContextConsole() {
  const [question, setQuestion] = useState(EXAMPLES[0]);
  const [result, setResult] = useState<ContextQueryResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const execute = async (event: FormEvent) => {
    event.preventDefault(); setBusy(true); setError(null);
    try { setResult(await adminApi.contextQuery(question)); }
    catch (reason) { setError((reason as Error).message); }
    finally { setBusy(false); }
  };
  return <div className="context-console">
    <header><Badge variant="outline">CONTEXT ENGINE VERTICAL</Badge><h2>업무 질문을 검증된 실행계획으로</h2><p>승인된 Ontology와 Binding으로 Capability를 선택하고, 실제 데이터 결과와 근거를 함께 반환합니다.</p></header>
    <div className="context-examples">{EXAMPLES.map((item) => <button key={item} type="button" onClick={() => setQuestion(item)}>{item}</button>)}</div>
    <form onSubmit={execute}><input value={question} onChange={(event) => setQuestion(event.target.value)} aria-label="업무 질문" /><Button disabled={busy || !question.trim()}><Play size={14} />{busy ? "실행 중…" : "질문 실행"}</Button></form>
    {error && <div className="context-error"><AlertTriangle size={15} />{error}</div>}
    {!result && !busy && <p className="context-hint">계약금액 집계와 조건별 입찰공고 검색 vertical을 지원합니다.</p>}
    {result && <><section className="context-result"><div><small>{result.interpretation.organization?.organization_name ?? "전체 기관"} · {result.interpretation.period_from}—{result.interpretation.period_to}</small>{result.query_type === "contract_amount" ? <><strong>{(result.result.contract_amount ?? 0).toLocaleString("ko-KR")}원</strong><span>{(result.result.contract_event_count ?? 0).toLocaleString("ko-KR")}개 계약 · 금액 완전성 {result.result.amount_completeness}</span></> : <><strong>{(result.result.total_items ?? 0).toLocaleString("ko-KR")}개 공고</strong><span>상위 {result.result.returned_items ?? 0}개 표시{result.interpretation.period_defaulted ? " · 최근 1년 기본 적용" : ""}</span></>}</div><Badge variant={result.result.status === "complete" ? "success" : "warning"}>{result.result.status === "complete" ? <CheckCircle2 size={11} /> : <AlertTriangle size={11} />}{result.result.status === "complete" ? "검증된 결과" : "부분 결과"}</Badge></section>
      {result.result.notices && <Card><CardHeader><CardTitle>입찰공고</CardTitle><CardDescription>현재 조건과 일치하는 첫 페이지 결과입니다.</CardDescription></CardHeader><CardContent className="evidence-list">{result.result.notices.map((notice) => <div key={notice.bid_notice_id}><Database size={14} /><span><strong>{notice.notice_name ?? notice.bid_notice_id}</strong><small>{notice.notice_organization_name ?? "기관 미상"} · 마감 {notice.bid_deadline_at ? new Date(notice.bid_deadline_at).toLocaleString("ko-KR") : "미정"} · {notice.estimated_price ? `${Number(notice.estimated_price).toLocaleString("ko-KR")}원` : "금액 미상"}</small></span></div>)}</CardContent></Card>}
      <div className="context-grid"><Card><CardHeader><CardTitle>질문 해석</CardTitle><CardDescription>{result.interpretation.concept.description}</CardDescription></CardHeader><CardContent className="context-facts"><div><span>업무 개념</span><code>{result.interpretation.concept.stable_key}</code></div>{result.interpretation.organization && <div><span>기관 코드</span><code>{result.interpretation.organization.organization_code}</code></div>}<div><span>기간</span><code>{result.interpretation.period_years ? `최근 ${result.interpretation.period_years}년` : `${result.interpretation.period_from.slice(0, 10)}—${result.interpretation.period_to.slice(0, 10)}`}</code></div></CardContent></Card><Card><CardHeader><CardTitle>실행계획</CardTitle><CardDescription>승인된 semantic Binding으로 선택했습니다.</CardDescription></CardHeader><CardContent className="context-route"><Route size={16} /><code>{result.execution_plan.capability_id}</code><ArrowRight size={14} /><span>{result.validation.executed_pages} pages</span></CardContent></Card></div>
      <Card><CardHeader><CardTitle>근거와 재현성</CardTitle><CardDescription>사용한 의미 연결, 실행 정책과 배포 artifact입니다.</CardDescription></CardHeader><CardContent className="evidence-list"><div><Database size={14} /><span><strong>Runtime Registry</strong><small>{result.validation.runtime_registry?.version ?? "unknown"}</small></span></div><div><Database size={14} /><span><strong>원천 데이터 최신 관찰</strong><small>{result.validation.data_freshness ? new Date(result.validation.data_freshness).toLocaleString("ko-KR") : "확인 불가"} · quality {result.validation.metadata_quality_status}</small></span></div><div><CheckCircle2 size={14} /><span><strong>Policy allowed · {result.policy.actor}</strong><small>기간 {result.policy.validated_period_years}/{result.policy.max_period_years}년 · 최대 {result.policy.max_pages} pages</small></span></div>{result.evidence.map((item) => <div key={item.locator}><CheckCircle2 size={14} /><span><strong>{item.type} · {item.authority}</strong><small>{item.locator}</small></span></div>)}</CardContent></Card>
      {result.warnings.length > 0 && <div className="context-warning"><AlertTriangle size={14} /><span>{result.warnings.join(" · ")}</span></div>}</>}
  </div>;
}
