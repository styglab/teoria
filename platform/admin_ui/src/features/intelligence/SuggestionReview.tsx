import { useCallback, useEffect, useMemo, useState } from "react";
import { Check, ChevronDown, CircleAlert, FileText, Inbox, X } from "lucide-react";
import { adminApi, type IntelligenceSuggestion } from "../../api/admin";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../components/ui/card";

const TYPE_LABELS: Record<string, string> = {
  description: "Description",
  binding: "Semantic Binding",
  glossary_term: "Glossary Term",
  glossary_term_assignment: "Term Assignment",
  ontology_change: "Ontology Change",
  test_suite: "Test Suite",
  quality_test: "Quality Test",
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
  if (item.suggestion_type === "description") return "승인하면 OpenMetadata 컬럼 설명에 반영됩니다.";
  if (item.suggestion_type === "binding") return "승인하면 Teoria Binding Draft가 생성됩니다.";
  if (item.suggestion_type === "ontology_change") return "승인하면 새 Ontology Draft에만 반영됩니다.";
  if (item.suggestion_type === "glossary_term_assignment") return "승인하면 OpenMetadata 컬럼에 용어가 할당됩니다.";
  if (item.suggestion_type === "glossary_term") return "승인하면 OpenMetadata Glossary Term이 생성됩니다.";
  if (item.suggestion_type === "test_suite") return "승인하면 OpenMetadata Test Suite가 생성됩니다.";
  if (item.suggestion_type === "quality_test") return "승인하면 OpenMetadata Test Case가 생성됩니다.";
  return "승인 후 유형별 application service가 실행됩니다.";
}

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
  const [items, setItems] = useState<IntelligenceSuggestion[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [filter, setFilter] = useState<"pending" | "all">("pending");
  const load = useCallback(() => {
    adminApi.intelligenceSuggestions().then((value) => setItems(value.items)).catch((reason: Error) => setError(reason.message));
  }, []);
  useEffect(load, [load]);

  const visible = useMemo(() => filter === "pending" ? items.filter((item) => item.status === "pending") : items, [filter, items]);
  const pendingCount = items.filter((item) => item.status === "pending").length;

  const review = async (id: string, decision: "approve" | "reject") => {
    setBusy(id); setError(null);
    try { await adminApi.reviewSuggestion(id, decision); load(); }
    catch (reason) { setError((reason as Error).message); }
    finally { setBusy(null); }
  };

  return <div className="review-queue">
    <header className="review-queue-header">
      <div>
        <span className="review-eyebrow"><Inbox size={14} /> Metadata governance</span>
        <h2>Review Queue</h2>
        <p>AI 제안을 근거와 적용 효과까지 확인한 뒤 최소 변경 단위로 승인합니다.</p>
      </div>
      <div className="review-summary">
        <strong>{pendingCount}</strong><span>검토 대기</span>
      </div>
    </header>

    <nav className="review-filters" aria-label="Suggestion 상태 필터">
      <Button size="sm" variant={filter === "pending" ? "default" : "ghost"} onClick={() => setFilter("pending")}>대기 중 {pendingCount}</Button>
      <Button size="sm" variant={filter === "all" ? "default" : "ghost"} onClick={() => setFilter("all")}>전체 {items.length}</Button>
    </nav>

    {error && <div className="review-error"><CircleAlert size={16} />{error}</div>}
    {!visible.length ? <div className="review-empty"><Check size={28} /><h3>검토할 제안이 없습니다</h3><p>새 분석 결과가 제출되면 이곳에 표시됩니다.</p></div> : <div className="review-list">
      {visible.map((item) => <Card className="review-card" key={item.suggestion_id}>
        <CardHeader className="review-card-header">
          <div className="review-card-title">
            <div className="review-badges">
              <Badge variant="outline">{TYPE_LABELS[item.suggestion_type] ?? item.suggestion_type}</Badge>
              <Badge variant={item.status === "applied" ? "success" : item.status === "failed" || item.status === "rejected" ? "destructive" : item.status === "pending" ? "warning" : "default"}>{STATUS_LABELS[item.status] ?? item.status}</Badge>
              <Badge variant="outline">신뢰도 {Math.round(item.confidence * 100)}%</Badge>
            </div>
            <CardTitle>{targetName(item)}</CardTitle>
            <CardDescription>{item.target_ref}</CardDescription>
          </div>
        </CardHeader>
        <CardContent>
          <div className="review-effect"><CircleAlert size={15} /><span>{applicationEffect(item)}</span></div>
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
            <small>{item.model_provider}/{item.model_name} · {new Date(item.created_at).toLocaleString("ko-KR")}</small>
            {item.status === "pending" && <div>
              <Button variant="outline" disabled={busy === item.suggestion_id} onClick={() => review(item.suggestion_id, "reject")}><X size={14} /> 거절</Button>
              <Button disabled={busy === item.suggestion_id} onClick={() => review(item.suggestion_id, "approve")}><Check size={14} /> {["binding", "ontology_change"].includes(item.suggestion_type) ? "승인하고 Draft 생성" : "승인하고 반영"}</Button>
            </div>}
          </footer>
        </CardContent>
      </Card>)}
    </div>}
  </div>;
}
