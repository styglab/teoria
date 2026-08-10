import { useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, Clock3, FileSearch } from "lucide-react";
import { adminApi, type BidNoticeSummary, type BidRequirement } from "../../api/admin";

export function BidCheckView() {
  const [notices, setNotices] = useState<BidNoticeSummary[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [requirements, setRequirements] = useState<BidRequirement[]>([]);
  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [bidStatus, setBidStatus] = useState("");
  const [workType, setWorkType] = useState("");
  const [extractionStatus, setExtractionStatus] = useState("");
  const [reviewStatus, setReviewStatus] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [total, setTotal] = useState(0);
  const [totalPages, setTotalPages] = useState(1);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const timeout = window.setTimeout(() => { setPage(1); setDebouncedQuery(query); }, 300);
    return () => window.clearTimeout(timeout);
  }, [query]);
  useEffect(() => {
    adminApi.bidNotices(page, pageSize, { query: debouncedQuery, bidStatus, workType, extractionStatus, reviewStatus }).then((response) => {
      setNotices(response.items);
      setTotal(response.total);
      setTotalPages(response.total_pages);
      if (!response.items.some((item) => item.bid_notice_id === selected)) {
        setSelected(response.items[0]?.bid_notice_id ?? "");
      }
    }).catch((reason: Error) => setError(reason.message));
  }, [page, pageSize, debouncedQuery, bidStatus, workType, extractionStatus, reviewStatus]);
  useEffect(() => {
    if (!selected) return;
    setRequirements([]);
    adminApi.bidRequirements(selected).then(({ requirements: items }) => setRequirements(items))
      .catch((reason: Error) => setError(reason.message));
  }, [selected]);

  const notice = notices.find((item) => item.bid_notice_id === selected);
  if (error) return <div className="error-state">{error}</div>;
  const metrics = {
    open: notices.filter((item) => item.bid_status === "open").length,
    extracted: notices.filter((item) => item.requirement_count > 0).length,
    review: notices.filter((item) => item.requires_review).length,
    pending: notices.filter((item) => !item.extraction_completeness).length,
  };
  return <div className="bid-check-page">
    <section className="bid-metrics">
      <div><span>진행 중 공고</span><strong>{metrics.open}</strong></div>
      <div><span>추출 완료</span><strong>{metrics.extracted}</strong></div>
      <div><span>확인 필요</span><strong>{metrics.review}</strong></div>
      <div><span>추출 대기</span><strong>{metrics.pending}</strong></div>
    </section>
    <div className="bid-check-layout">
    <aside className="bid-notice-list">
      <div className="bid-search"><FileSearch size={14} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="공고번호·공고명 검색" /></div>
      <div className="bid-filters">
        <select aria-label="공고 상태" value={bidStatus} onChange={(event) => { setBidStatus(event.target.value); setPage(1); }}>
          <option value="">공고 상태 전체</option><option value="open">진행 중</option><option value="scheduled">진행 예정</option><option value="closed">마감</option><option value="unknown">상태 미상</option>
        </select>
        <select aria-label="업무 유형" value={workType} onChange={(event) => { setWorkType(event.target.value); setPage(1); }}>
          <option value="">업무 유형 전체</option><option value="service">용역</option><option value="goods">물품</option><option value="construction">공사</option><option value="foreign">외자</option><option value="other">기타</option>
        </select>
        <select aria-label="추출 상태" value={extractionStatus} onChange={(event) => { setExtractionStatus(event.target.value); setPage(1); }}>
          <option value="">추출 상태 전체</option><option value="pending">추출 대기</option><option value="extracted">추출 완료</option><option value="complete">문서 전체 추출</option><option value="partial">일부 문서 추출</option><option value="api_only">API 정보만</option>
        </select>
        <select aria-label="검토 상태" value={reviewStatus} onChange={(event) => { setReviewStatus(event.target.value); setPage(1); }}>
          <option value="">검토 상태 전체</option><option value="required">확인 필요</option><option value="not_required">확인 불필요</option>
        </select>
        <button type="button" onClick={() => { setQuery(""); setDebouncedQuery(""); setBidStatus(""); setWorkType(""); setExtractionStatus(""); setReviewStatus(""); setPage(1); }}>초기화</button>
      </div>
      <div className="bid-result-count"><strong>{total.toLocaleString()}</strong>건 검색됨</div>
      {notices.map((item) => <button key={item.bid_notice_id} className={selected === item.bid_notice_id ? "selected" : ""} onClick={() => setSelected(item.bid_notice_id)}>
        <div><code>{item.notice_number}</code><span className={`bid-state ${item.bid_status}`}>{item.bid_status}</span></div>
        <strong>{item.notice_name}</strong>
        <small>{item.notice_organization_name ?? item.demand_organization_name ?? "기관 미상"}</small>
        <footer><span>{item.requirement_count} requirements</span><span>{item.extraction_completeness ?? "추출 대기"}</span></footer>
      </button>)}
      <footer className="bid-pagination">
        <select aria-label="페이지당 건수" value={pageSize} onChange={(event) => { setPageSize(Number(event.target.value)); setPage(1); }}><option value="20">20개</option><option value="50">50개</option><option value="100">100개</option></select>
        <nav aria-label="입찰공고 페이지">
          <button disabled={page <= 1} onClick={() => setPage((value) => value - 1)}>이전</button>
          {paginationItems(page, totalPages).map((item, index) => item === "…"
            ? <span key={`ellipsis-${index}`} className="ellipsis">…</span>
            : <button key={item} className={item === page ? "active" : ""} aria-current={item === page ? "page" : undefined} onClick={() => setPage(item)}>{item}</button>)}
          <button disabled={page >= totalPages} onClick={() => setPage((value) => value + 1)}>다음</button>
        </nav>
      </footer>
    </aside>
    <section className="bid-requirements">
      <header><div><span>BID ELIGIBILITY</span><h2>{notice?.notice_name ?? "공고를 선택하세요"}</h2><p>{notice?.bid_notice_id} · 마감 {formatDate(notice?.bid_deadline_at)}</p></div>{notice?.requires_review && <b><AlertTriangle size={13} /> 확인 필요</b>}</header>
      <div className="requirement-list">
        {!requirements.length && <div className="bid-empty"><Clock3 size={20} /><span>참가자격 추출 대기 중입니다.</span></div>}
        {requirements.map((item) => <article key={item.requirement_id}>
          <header><CheckCircle2 size={14} /><strong>{item.requirement_type}</strong><code>{item.operator}</code><span>{Math.round(item.confidence * 100)}%</span></header>
          {item.proposition_text && item.proposition_text !== item.original_text &&
            <p><strong>원자 조건</strong><br />{item.proposition_text}</p>}
          <p><strong>인용 원문</strong><br />{item.original_text}</p>
          <dl><div><dt>적용 대상</dt><dd>{item.holder_scope}</dd></div><div><dt>판정 단계</dt><dd>{item.assessment_stage}</dd></div><div><dt>불충족 효과</dt><dd>{item.failure_effect}</dd></div><div><dt>비교 방식</dt><dd>{item.comparison_mode}</dd></div><div><dt>기준일</dt><dd>{item.reference_date_type}</dd></div></dl>
          {item.proof_summary && <p><strong>제출 증빙</strong><br />{item.proof_summary}</p>}
          {item.evidence_summary && <blockquote>{item.evidence_summary}</blockquote>}
        </article>)}
      </div>
    </section>
    </div>
  </div>;
}

function formatDate(value?: string | null) {
  return value ? new Intl.DateTimeFormat("ko-KR", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value)) : "미정";
}

function paginationItems(current: number, total: number): Array<number | "…"> {
  if (total <= 7) return Array.from({ length: total }, (_, index) => index + 1);
  const pages = new Set([1, total, current - 1, current, current + 1]);
  const valid = [...pages].filter((value) => value >= 1 && value <= total).sort((a, b) => a - b);
  const result: Array<number | "…"> = [];
  valid.forEach((value, index) => {
    if (index > 0 && value - valid[index - 1] > 1) result.push("…");
    result.push(value);
  });
  return result;
}
