import { useEffect, useState } from "react";
import { suggestionApi, type ApplicationAttempt } from "../../api/suggestions";
import { Button } from "../../components/ui/button";

const OUTCOMES: Record<string, string> = {
  applied: "적용 완료", failed: "적용 실패", superseded: "새 시도로 대체됨", reconciled: "기존 결과 확인 완료",
};
export function SuggestionApplicationHistory({ id }: { id: string }) {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<ApplicationAttempt[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [after, setAfter] = useState<string | undefined>();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    if (!open) return;
    let active = true;
    setLoading(true); setError(null);
    suggestionApi.suggestionAttempts(id, after)
      .then(page => { if (active) { setItems(previous => after ? [...previous, ...page.items] : page.items); setCursor(page.next_cursor); } })
      .catch(() => { if (active) setError("적용 이력을 조회하지 못했습니다."); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [id, open, after, refresh]);
  return <section className="review-history" aria-label="적용 이력">
    <Button variant="outline" size="sm" aria-expanded={open} onClick={() => { setAfter(undefined); setItems([]); setCursor(null); setOpen(value => !value); }}>적용 이력 {open ? "접기" : "보기"}</Button>
    {open && <div>
      {error && <p role="alert">{error} <Button size="sm" variant="outline" onClick={() => setRefresh(value => value + 1)}>다시 조회</Button></p>}
      {!!items.length && <ol>{items.map(attempt => <li key={attempt.attempt_id}>
        <strong>{attempt.outcome ? OUTCOMES[attempt.outcome] ?? attempt.outcome : "종료 기록 없음"}</strong>
        <p>실행자 {attempt.actor} · 대상 {attempt.target_system}</p>
        <p>시작 {new Date(attempt.started_at).toLocaleString("ko-KR")}{attempt.finished_at && <> · 종료 {new Date(attempt.finished_at).toLocaleString("ko-KR")}</>}</p>
        {!attempt.outcome && <p>진행 중이거나 중단된 시도입니다. 현재 적용 상태와 복구 안내를 확인하세요.</p>}
        {attempt.error_code && <p>오류 코드 <code>{attempt.error_code}</code></p>}
      </li>)}</ol>}
      {loading && <p role="status">적용 이력을 조회하고 있습니다…</p>}
      {!loading && !error && !items.length && <p>기록된 적용 시도가 없습니다.</p>}
      {cursor && !error && <Button variant="outline" size="sm" disabled={loading} onClick={() => setAfter(cursor)}>이전 시도 더 보기</Button>}
    </div>}
  </section>;
}
