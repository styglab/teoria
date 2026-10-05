import { useEffect, useState } from "react";
import { Database, ExternalLink, Table2, X } from "lucide-react";
import { adminApi, type MetadataEntity, type MetadataStatus, type MetadataTableDetail } from "../../api/admin";

export function MetadataExplorer() {
  const [status, setStatus] = useState<MetadataStatus | null>(null);
  const [tables, setTables] = useState<MetadataEntity[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [detail, setDetail] = useState<MetadataTableDetail | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

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
    {detail && <div className="validation-backdrop" onMouseDown={() => setDetail(null)}><section className="validation-dialog" onMouseDown={(event) => event.stopPropagation()}>
      <header><div><span>OPENMETADATA TABLE</span><h2>{detail.display_name || detail.name}</h2><p>{detail.reference.fully_qualified_name}</p></div><button className="icon-button" onClick={() => setDetail(null)}><X size={16} /></button></header>
      <div className="validation-dialog-body registry-list">{detail.columns.map((column) => <article className="registry-card" key={column.name}>
        <header><div><span>{column.dataType || "unknown"}</span><h3>{column.displayName || column.name}</h3></div></header>
        <p>{column.description || "Column description 없음"}</p>
        <footer className="suggestion-actions"><button disabled={busy === column.name} onClick={async (event) => { event.stopPropagation(); setBusy(column.name); setError(null); try { await adminApi.suggestColumnBinding(detail.reference.entity_id, column.name); } catch (reason) { setError((reason as Error).message); } finally { setBusy(null); } }}>Binding 후보 생성</button></footer>
      </article>)}</div>
    </section></div>}
  </div>;
}
