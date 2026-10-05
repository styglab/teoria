import { useCallback, useEffect, useState } from "react";
import { adminApi, type IntelligenceSuggestion } from "../../api/admin";

export function SuggestionReview() {
  const [items, setItems] = useState<IntelligenceSuggestion[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const load = useCallback(() => {
    adminApi.intelligenceSuggestions().then((value) => setItems(value.items)).catch((reason: Error) => setError(reason.message));
  }, []);
  useEffect(load, [load]);

  const review = async (id: string, decision: "approve" | "reject") => {
    setBusy(id); setError(null);
    try { await adminApi.reviewSuggestion(id, decision); load(); }
    catch (reason) { setError((reason as Error).message); }
    finally { setBusy(null); }
  };

  if (error) return <div className="error-state">{error}</div>;
  if (!items.length) return <div className="loading-state">검토할 Metadata Suggestion이 없습니다.</div>;
  return <div className="registry-list suggestion-list">
    {items.map((item) => <article className="registry-card" key={item.suggestion_id}>
      <header><div><span>{item.suggestion_type} · {item.risk_level}</span><h3>{item.target_ref}</h3></div><b>{item.status}</b></header>
      <p>{item.proposed_value.description ?? (item.proposed_value.ontology_stable_key ? `추천 Binding: ${item.proposed_value.ontology_stable_key}` : JSON.stringify(item.proposed_value))}</p>
      {!!item.proposed_value.alternatives?.length && <small>다른 후보: {item.proposed_value.alternatives.map((candidate) => `${candidate.stable_key} ${(candidate.score * 100).toFixed(0)}%`).join(" · ")}</small>}
      <small>{item.model_provider}/{item.model_name} · confidence {(item.confidence * 100).toFixed(0)}% · policy {item.policy_version}</small>
      {item.rationale && <p>{item.rationale}</p>}
      {item.status === "pending" && <footer className="suggestion-actions">
        <button disabled={busy === item.suggestion_id} onClick={() => review(item.suggestion_id, "reject")}>거절</button>
        <button disabled={busy === item.suggestion_id} onClick={() => review(item.suggestion_id, "approve")}>{item.suggestion_type === "binding" ? "승인 및 Draft 생성" : "승인 및 반영"}</button>
      </footer>}
    </article>)}
  </div>;
}
