import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { RefreshCw, ArrowRight } from "lucide-react";
import {
  PageHeader,
  PageState,
  FilterTabs,
  SearchField,
} from "../../components/workspace/WorkspaceLayout";
import {
  CatalogPagination,
  useCatalogPagination,
} from "../../components/workspace/CatalogPagination";
import { loadReviewWork, type ReviewWorkItem } from "./review_work";
import { SuggestionReview } from "./SuggestionReview";

export function ReviewInbox() {
  const [params, setParams] = useSearchParams();
  const detail =
    params.has("suggestion") ||
    params.has("assetId") ||
    params.has("status") ||
    params.get("kind") === "suggestions";
  return detail ? (
    <div className="review-detail-workspace">
      <Link className="breadcrumb-link" to="/admin/changes/review">
        ← 검토함
      </Link>
      <SuggestionReview />
    </div>
  ) : (
    <ReviewQueue />
  );
}
function ReviewQueue() {
  const [params, setParams] = useSearchParams();
  const kind = params.get("type") || "all";
  const query = params.get("q") || "";
  const [data, setData] = useState<Awaited<
    ReturnType<typeof loadReviewWork>
  > | null>(null);
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    let active = true;
    setData(null);
    loadReviewWork().then((value) => {
      if (active) setData(value);
    });
    return () => {
      active = false;
    };
  }, [refresh]);
  const update = (values: Record<string, string>) =>
    setParams((previous) => {
      const next = new URLSearchParams(previous);
      next.delete("page");
      Object.entries(values).forEach(([k, v]) =>
        v ? next.set(k, v) : next.delete(k),
      );
      return next;
    });
  const items =
    data?.items.filter(
      (item) =>
        (kind === "all" || kind === item.kind) &&
        `${item.title} ${item.description}`
          .toLocaleLowerCase()
          .includes(query.toLocaleLowerCase()),
    ) || [];
  const pagination = useCatalogPagination(
    items.length,
    JSON.stringify([kind, query]),
  );
  return (
    <div className="workspace-page review-inbox">
      <PageHeader
        title="검토함"
        description="변경 전후와 근거를 확인하고, 유형별 검토 절차로 이어갑니다."
        actions={
          <>
            <Link
              className="operations-link"
              to="/admin/changes/review?kind=suggestions&status=all"
            >
              처리한 제안 보기
            </Link>
            <button
              className="page-icon-button"
              aria-label="검토함 새로고침"
              onClick={() => setRefresh((v) => v + 1)}
            >
              <RefreshCw size={16} />
            </button>
          </>
        }
      />
      <SearchField
        label="검토할 작업 검색"
        placeholder="대상 이름과 설명 검색"
        value={query}
        onChange={(q) => update({ q })}
      />
      <div className="page-controls">
        <FilterTabs
          label="검토 유형"
          value={kind}
          onChange={(type) => update({ type })}
          items={[
            { id: "all", label: "전체" },
            { id: "suggestion", label: "변경 제안" },
            { id: "binding", label: "의미 연결" },
            { id: "ontology", label: "온톨로지" },
          ]}
        />
        <span className="workspace-muted">조회된 범위 {items.length}개</span>
      </div>
      {!!data?.errors.length && (
        <p role="alert" className="workspace-error">
          {data.errors.join(", ")}을 조회하지 못했습니다.{" "}
          <button onClick={() => setRefresh((v) => v + 1)}>다시 조회</button>
        </p>
      )}
      {data?.limited && (
        <p className="operations-note">
          변경 제안은 첫 50개, 온톨로지는 최대 20개 업무 모델을 조회했습니다.
          유형별 전체 목록에서 나머지 항목을 확인하세요.
        </p>
      )}
      <div className="page-table-wrap review-inbox-table">
        <table className="page-table">
          <thead>
            <tr>
              <th>검토 대상</th>
              <th>상태</th>
              <th>등록 시각</th>
              <th>검토</th>
            </tr>
          </thead>
          <tbody>
            {items.slice(pagination.start, pagination.end).map((item) => (
              <tr key={`${item.kind}:${item.id}`}>
                <td>
                  <strong>{item.title}</strong>
                  <p className="review-queue-description">{item.description}</p>
                </td>
                <td>{item.state}</td>
                <td>{new Date(item.created).toLocaleString("ko-KR")}</td>
                <td>
                  <Link className="operations-link" to={item.href}>
                    검토 열기 <ArrowRight size={12} />
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!data ? (
          <PageState loading title="검토할 작업을 확인하고 있습니다…" />
        ) : (
          !items.length && (
            <PageState title="조회 범위에 검토할 작업이 없습니다" />
          )
        )}
      </div>
      <CatalogPagination {...pagination} loading={!data} />
      <p className="operations-note">
        제안 승인, 의미 연결 승인, 온톨로지 게시는 각 기능의 권한과 정책에 따라
        별도로 처리됩니다.
      </p>
    </div>
  );
}
