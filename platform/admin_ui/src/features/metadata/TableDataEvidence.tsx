import { useEffect, useRef, useState } from "react";
import { metadataApi, type MetadataTableProfile, type MetadataTableSamples } from "../../api/metadata";

const metricLabels: Record<string, string> = {
  timestamp: "관측 시각", rowCount: "행 수", columnCount: "컬럼 수", profileSample: "프로파일 표본 설정",
  valuesCount: "값 수", nullCount: "NULL 수", nullProportion: "NULL 비율", distinctCount: "서로 다른 값 수",
  distinctProportion: "서로 다른 값 비율", uniqueCount: "유일한 값 수", uniqueProportion: "유일한 값 비율",
  minLength: "최소 길이", maxLength: "최대 길이", avgLength: "평균 길이",
};
function metricText(key: string, value: number | null) {
  const label = metricLabels[key] || key;
  if (value === null) return `${label}: —`;
  if (key === "timestamp") return `${label}: ${new Date(value > 1e12 ? value : value * 1000).toLocaleString("ko-KR")}`;
  return `${label}: ${key.endsWith("Proportion") ? `${(value * 100).toFixed(1)}%` : value.toLocaleString("ko-KR")}`;
}

export function TableDataEvidence({ tableId }: { tableId: string }) {
  const [samples, setSamples] = useState<MetadataTableSamples | null>(null);
  const [profile, setProfile] = useState<MetadataTableProfile | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const requestSequence = useRef(0);

  useEffect(() => {
    requestSequence.current += 1;
    setSamples(null); setProfile(null); setError(null); setBusy(false);
    return () => { requestSequence.current += 1; };
  }, [tableId]);

  const load = async (kind: "samples" | "values" | "profile") => {
    const request = ++requestSequence.current;
    setBusy(true); setError(null);
    // Remove displayed values before switching to a masked request or after a
    // permission failure; late responses never populate another table's dialog.
    if (kind !== "profile") setSamples(null);
    try {
      if (kind === "profile") {
        const result = await metadataApi.metadataTableProfile(tableId);
        if (request === requestSequence.current) setProfile(result);
      } else {
        const result = await metadataApi.metadataTableSamples(tableId, kind === "values");
        if (request === requestSequence.current) setSamples(result);
      }
    } catch (reason) {
      if (request === requestSequence.current) setError((reason as Error).message);
    } finally {
      if (request === requestSequence.current) setBusy(false);
    }
  };

  return <section className="table-data-evidence">
    <header><strong>데이터 샘플 · 프로파일</strong><div className="suggestion-actions">
      <button disabled={busy} onClick={() => load("samples")}>샘플 확인</button>
      <button disabled={busy} onClick={() => load("values")}>샘플 값 보기</button>
      <button disabled={busy} onClick={() => load("profile")}>프로파일 확인</button>
    </div></header>
    {busy && <p role="status">데이터 관측 정보를 조회하고 있습니다…</p>}
    {error && <p role="alert">{error}</p>}
    {samples && !samples.available && <p>수집된 샘플이 없습니다.</p>}
    {samples?.available && <>
      <p>저장된 샘플 {samples.stored_row_count}행 중 {samples.rows.length}행 표시
        {samples.values_included ? "" : " · 값 가림"}{samples.truncated ? " · 일부만 표시" : ""}</p>
      <div className="catalog-table-wrap"><table className="catalog-table"><thead><tr>
        {samples.columns.map((column, index) => <th key={index}>{column}</th>)}
      </tr></thead><tbody>{samples.rows.map((row, index) => <tr key={index}>
        {row.map((value, cell) => <td key={cell}>{value === null ? "NULL" : String(value)}</td>)}
      </tr>)}</tbody></table></div>
      <small>일부 데이터의 관측 결과이며 전체 데이터에 위험 정보가 없음을 보장하지 않습니다.</small>
    </>}
    {profile && !profile.available && <p>수집된 프로파일이 없습니다.</p>}
    {profile?.available && <>
      <p>{Object.entries(profile.table_metrics).map(([key, value]) => metricText(key, value)).join(" · ")}</p>
      <div className="registry-list">{profile.column_metrics.map((column) => <article className="registry-card" key={column.name}>
        <strong>{column.name}</strong><p>{Object.entries(column.metrics).map(([key, value]) => metricText(key, value)).join(" · ")}</p>
      </article>)}</div>
    </>}
  </section>;
}
