import { useEffect, useMemo, useState } from "react";
import { Bot, ChevronLeft, ChevronRight, Clipboard, Database, Inbox, Search, Table2, X } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { adminApi, type IntelligenceSuggestion, type MetadataEntity, type MetadataStatus, type MetadataTableDetail } from "../../api/admin";

export function MetadataExplorer() {
  const navigate = useNavigate();
  const [status, setStatus] = useState<MetadataStatus | null>(null);
  const [tables, setTables] = useState<MetadataEntity[]>([]);
  const [total, setTotal] = useState(0);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [cursorHistory, setCursorHistory] = useState<Array<string | undefined>>([undefined]);
  const [pageLoading, setPageLoading] = useState(false);
  const [query, setQuery] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [detail, setDetail] = useState<MetadataTableDetail | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [suggestion, setSuggestion] = useState<IntelligenceSuggestion | null>(null);
  const [bindingApproved, setBindingApproved] = useState(false);
  const [copied, setCopied] = useState(false);
  const pageSize = 25;

  const loadPage = async (cursor: string | undefined) => {
    setPageLoading(true); setError(null);
    try {
      const page = await adminApi.metadataTables({ after: cursor, limit: pageSize });
      setTables(page.items); setTotal(page.total); setNextCursor(page.after);
    } catch (reason) { setError((reason as Error).message); }
    finally { setPageLoading(false); }
  };

  const filteredTables = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    if (!normalized) return tables;
    return tables.filter((table) => [table.name, table.display_name, table.description, table.reference.fully_qualified_name]
      .some((value) => value?.toLowerCase().includes(normalized)));
  }, [query, tables]);

  const openTable = (table: MetadataEntity) => {
    if (!table.reference.fully_qualified_name) return;
    adminApi.metadataTable(table.reference.fully_qualified_name).then(setDetail).catch((reason: Error) => setError(reason.message));
  };

  const copyAnalysisRequest = async () => {
    const fqn = detail?.reference.fully_qualified_name;
    if (!fqn) return;
    const prompt = `$analyze-metadata-asset\nOpenMetadata 테이블 ${fqn}를 분석해줘.\n컬럼 description, glossary term 할당, ontology binding과 quality test 공백을 검토하고, 근거와 confidence를 포함한 제안을 Review Queue에 올려줘. 승인하거나 적용하지는 마.`;
    await navigator.clipboard.writeText(prompt);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 2500);
  };

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
      if (next.available) loadPage(undefined);
    }).catch((reason: Error) => setError(reason.message));
  }, []);

  if (error) return <div className="error-state">{error}</div>;
  if (!status) return <div className="loading-state">Metadata Foundation 상태를 확인하고 있습니다…</div>;
  if (!status.enabled) return <div className="metadata-empty"><Database size={28} /><h3>OpenMetadata가 비활성화되어 있습니다</h3><p>metadata profile을 실행하고 Teoria Admin API integration을 활성화하세요.</p></div>;
  if (!status.available) return <div className="metadata-empty"><Database size={28} /><h3>OpenMetadata에 연결할 수 없습니다</h3><p>{status.reason}</p></div>;
  return <div className="metadata-explorer">
    <header className="catalog-header"><div><span className="status-dot" /><div><strong>Data assets</strong><small>{status.database_service} · 전체 {total.toLocaleString("ko-KR")}개</small></div></div><label><Search size={14} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="현재 페이지에서 이름 또는 FQN 검색" /></label></header>
    <div className="catalog-table-wrap"><table className="catalog-table"><thead><tr><th>테이블</th><th>설명</th><th>태그 / 용어</th><th>Owner</th><th aria-label="상세" /></tr></thead><tbody>
      {filteredTables.map((table) => <tr key={table.reference.entity_id} onClick={() => openTable(table)} tabIndex={0} onKeyDown={(event) => { if (event.key === "Enter") openTable(table); }}>
        <td><div className="catalog-asset-name"><Table2 size={15} /><span><strong>{table.display_name || table.name}</strong><code>{table.reference.fully_qualified_name}</code></span></div></td>
        <td><p className={table.description ? "" : "catalog-missing"}>{table.description || "Description 없음"}</p></td>
        <td><div className="catalog-tags">{table.tags.slice(0, 3).map((tag, index) => <span key={String(tag.tagFQN ?? tag.name ?? index)}>{String(tag.tagFQN ?? tag.name ?? "tag")}</span>)}{!table.tags.length && <em>없음</em>}{table.tags.length > 3 && <em>+{table.tags.length - 3}</em>}</div></td>
        <td><span className="catalog-count">{table.owners.length || "—"}</span></td>
        <td><ChevronRight size={15} /></td>
      </tr>)}
    </tbody></table>{!filteredTables.length && <div className="catalog-empty">{query ? "검색 결과가 없습니다." : "수집된 Table metadata가 없습니다."}</div>}</div>
    <footer className="catalog-pagination"><span>페이지 {cursorHistory.length} · 페이지당 최대 {pageSize}개</span><div><button disabled={pageLoading || cursorHistory.length === 1} onClick={() => { const history = cursorHistory.slice(0, -1); setCursorHistory(history); loadPage(history.at(-1)); }}><ChevronLeft size={14} />이전</button><button disabled={pageLoading || !nextCursor} onClick={() => { if (!nextCursor) return; setCursorHistory((history) => [...history, nextCursor]); loadPage(nextCursor); }}>다음<ChevronRight size={14} /></button></div></footer>
    {detail && <div className="validation-backdrop" onMouseDown={() => { setDetail(null); setSuggestion(null); }}><section className="validation-dialog" onMouseDown={(event) => event.stopPropagation()}>
      <header><div><span>OPENMETADATA TABLE</span><h2>{detail.display_name || detail.name}</h2><p>{detail.reference.fully_qualified_name}</p></div><button className="icon-button" onClick={() => setDetail(null)}><X size={16} /></button></header>
      <div className="metadata-agent-bar">
        <div><Bot size={16} /><span><strong>Metadata Agent</strong><small>Codex Skill이 근거 기반 제안을 만들고, 적용은 Review Queue에서 사람이 결정합니다.</small></span></div>
        <div><button onClick={copyAnalysisRequest}><Clipboard size={14} />{copied ? "요청 복사됨" : "분석 요청 복사"}</button><button onClick={() => navigate("/admin/review-queue")}><Inbox size={14} />Review Queue</button></div>
      </div>
      <div className="metadata-quality-strip"><span>Description {detail.description ? "등록" : "없음"}</span><span>Glossary {detail.glossary_terms.length ? `${detail.glossary_terms.length}개` : "없음"}</span><span>Quality Suite {detail.test_suite ? "연결" : "없음"}</span></div>
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
