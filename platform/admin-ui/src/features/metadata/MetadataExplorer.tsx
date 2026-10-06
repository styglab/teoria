import { useEffect, useState } from "react";
import { Database, ExternalLink, Table2, X } from "lucide-react";
import { adminApi, type IntelligenceSuggestion, type MetadataEntity, type MetadataStatus, type MetadataTableDetail } from "../../api/admin";

export function MetadataExplorer() {
  const [status, setStatus] = useState<MetadataStatus | null>(null);
  const [tables, setTables] = useState<MetadataEntity[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [detail, setDetail] = useState<MetadataTableDetail | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [suggestion, setSuggestion] = useState<IntelligenceSuggestion | null>(null);
  const [bindingApproved, setBindingApproved] = useState(false);

  const reviewSuggestion = async (decision: "approve" | "reject") => {
    if (!suggestion) return;
    setBusy(suggestion.suggestion_id); setError(null);
    try { setSuggestion(await adminApi.reviewSuggestion(suggestion.suggestion_id, decision)); }
    catch (reason) { setError((reason as Error).message); }
    finally { setBusy(null); }
  };

  const approveBinding = async () => {
    if (!suggestion?.resulting_binding) return;
    setBusy(suggestion.resulting_binding.binding_id); setError(null);
    try { await adminApi.reviewBinding(suggestion.resulting_binding.binding_id, "approve", `Suggestion ${suggestion.suggestion_id} 검토 완료`); setBindingApproved(true); }
    catch (reason) { setError((reason as Error).message); }
    finally { setBusy(null); }
  };

  useEffect(() => {
    adminApi.metadataStatus().then((next) => {
      setStatus(next);
      if (next.available) adminApi.metadataTables().then((page) => setTables(page.items)).catch((reason: Error) => setError(reason.message));
    }).catch((reason: Error) => setError(reason.message));
  }, []);

  if (error) return <div className="error-state">{error}</div>;
  if (!status) return <div className="loading-state">Metadata Foundation 상태를 확인하고 있습니다…</div>;
  if (!status.enabled) return <div className="metadata-empty"><Database size={28} /><h3>OpenMetadata가 비활성화되어 있습니다</h3><p>metadata profile을 실행하고 Teoria Admin API integration을 활성화하세요.</p></div>;
  if (!status.available) return <div className="metadata-empty"><Database size={28} /><h3>OpenMetadata에 연결할 수 없습니다</h3><p>{status.reason}</p></div>;
  return <div className="metadata-explorer">
    <div className="metadata-status"><span className="status-dot" /><div><strong>OpenMetadata connected</strong><small>{status.database_service}</small></div><a href={status.base_url?.replace(/\/api$/, "") ?? "#"} target="_blank" rel="noreferrer">Catalog 열기 <ExternalLink size={13} /></a></div>
    <div className="registry-grid">{tables.map((table) => <article key={table.reference.entity_id} onClick={() => table.reference.fully_qualified_name && adminApi.metadataTable(table.reference.fully_qualified_name).then(setDetail).catch((reason: Error) => setError(reason.message))}>
      <header><Table2 size={16} /><div><strong>{table.display_name || table.name}</strong><code>{table.reference.fully_qualified_name}</code></div></header>
      <p>{table.description || "설명이 아직 등록되지 않았습니다."}</p>
      <footer><span>{table.owners.length} owners</span><span>{table.tags.length} tags/terms</span></footer>
    </article>)}</div>
    {!tables.length && <div className="loading-state">수집된 Table metadata가 없습니다.</div>}
    {detail && <div className="validation-backdrop" onMouseDown={() => { setDetail(null); setSuggestion(null); }}><section className="validation-dialog" onMouseDown={(event) => event.stopPropagation()}>
      <header><div><span>OPENMETADATA TABLE</span><h2>{detail.display_name || detail.name}</h2><p>{detail.reference.fully_qualified_name}</p></div><button className="icon-button" onClick={() => setDetail(null)}><X size={16} /></button></header>
      <div className="validation-dialog-body registry-list">{detail.columns.map((column) => <article className="registry-card" key={column.name}>
        <header><div><span>{column.dataType || "unknown"}</span><h3>{column.displayName || column.name}</h3></div></header>
        <p>{column.description || "Column description 없음"}</p>
        <footer className="suggestion-actions"><button disabled={busy === column.name} onClick={async (event) => { event.stopPropagation(); setBusy(column.name); setError(null); setBindingApproved(false); try { setSuggestion(await adminApi.suggestColumnBinding(detail.reference.entity_id, column.name)); } catch (reason) { setError((reason as Error).message); } finally { setBusy(null); } }}>Binding 후보 생성</button></footer>
      </article>)}</div>
      {suggestion && <aside className="binding-candidate-review">
        <header><div><span>BINDING SUGGESTION</span><h3>{suggestion.proposed_value.ontology_stable_key}</h3></div><b>{(suggestion.confidence * 100).toFixed(0)}%</b></header>
        <div className="binding-candidate-path"><code>{suggestion.target_ref}</code><span>↕</span><code>{suggestion.proposed_value.ontology_stable_key}</code></div>
        <h4>판정 근거</h4>
        <ul>{suggestion.evidence?.map((item) => <li key={item.evidence_id}><strong>{item.evidence_type}</strong><span>{item.provenance?.score == null ? "근거 확인" : `${(item.provenance.score * 100).toFixed(0)}%`}</span></li>)}</ul>
        {!!suggestion.proposed_value.alternatives?.length && <p>다른 후보: {suggestion.proposed_value.alternatives.map((item) => `${item.stable_key} ${(item.score * 100).toFixed(0)}%`).join(" · ")}</p>}
        {suggestion.status === "pending" && <footer className="suggestion-actions"><button disabled={busy === suggestion.suggestion_id} onClick={() => reviewSuggestion("reject")}>거절</button><button disabled={busy === suggestion.suggestion_id} onClick={() => reviewSuggestion("approve")}>승인하고 Binding Draft 생성</button></footer>}
        {suggestion.resulting_binding && !bindingApproved && <><p className="candidate-notice">Suggestion이 승인되어 Binding Draft가 생성되었습니다. 의미 연결은 별도 승인 전까지 활성화되지 않습니다.</p><footer className="suggestion-actions"><button disabled={busy === suggestion.resulting_binding.binding_id} onClick={approveBinding}>Binding Draft 검토·승인</button></footer></>}
        {bindingApproved && <p className="candidate-success">Approved Binding으로 활성화되었습니다.</p>}
      </aside>}
    </section></div>}
  </div>;
}
