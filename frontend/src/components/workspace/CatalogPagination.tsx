import { useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";

export function useCatalogPagination(total: number, scope: string) {
  const [pageSize, setPageSize] = useState(25);
  const [position, setPosition] = useState({ scope, page: 0 });
  if (position.scope !== scope) setPosition({ scope, page: 0 });
  const lastPage = Math.max(0, Math.ceil(total / pageSize) - 1);
  const page = position.scope === scope ? Math.min(position.page, lastPage) : 0;
  return {
    page,
    pageSize,
    total,
    start: page * pageSize,
    end: (page + 1) * pageSize,
    onPageChange: (next: number) => setPosition({ scope, page: next }),
    onPageSizeChange: (size: number) => {
      setPageSize(size);
      setPosition({ scope, page: 0 });
    },
  };
}

type CatalogPaginationProps = {
  page: number;
  pageSize: number;
  total: number;
  loading?: boolean;
  error?: boolean;
  disabled?: boolean;
  onPageChange: (page: number) => void;
  onPageSizeChange: (size: number) => void;
};

export function CatalogPagination({ page, pageSize, total, loading, error, disabled, onPageChange, onPageSizeChange }: CatalogPaginationProps) {
  const lastPage = Math.max(0, Math.ceil(total / pageSize) - 1);
  const unavailable = loading || error || disabled;
  return <footer className="asset-catalog-footer">
    <label>페이지당<select value={pageSize} disabled={disabled} onChange={event => onPageSizeChange(Number(event.target.value))}><option value="25">25개</option><option value="50">50개</option></select></label>
    <span>{loading || error ? "—" : total ? `${page * pageSize + 1}–${Math.min((page + 1) * pageSize, total)} / ${total}개` : "0개"}</span>
    <div>
      <button type="button" aria-label="이전 페이지" disabled={unavailable || page === 0} onClick={() => onPageChange(page - 1)}><ChevronLeft size={16}/></button>
      <span>{page + 1} / {lastPage + 1}</span>
      <button type="button" aria-label="다음 페이지" disabled={unavailable || page >= lastPage} onClick={() => onPageChange(page + 1)}><ChevronRight size={16}/></button>
    </div>
  </footer>;
}
