import "./selection_catalog.css";
import type { ReactNode } from "react";
import { CatalogLayout, SearchField } from "./WorkspaceLayout";

export function SelectionCatalog({
  title,
  search,
  onSearch,
  items,
  selected,
  onSelect,
  controls,
  footer,
  children,
}: {
  title: string;
  search: string;
  onSearch: (value: string) => void;
  items: Array<{
    id: string;
    title: string;
    subtitle?: string;
    status?: ReactNode;
  }>;
  selected?: string;
  onSelect: (id: string) => void;
  controls?: ReactNode;
  footer?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="selection-catalog">
      <CatalogLayout
        label={`${title} 목록`}
        sidebar={
          <>
            <h3 className="selection-heading">{title}</h3>
            <SearchField
              label={`${title} 검색`}
              placeholder="이름으로 검색"
              value={search}
              onChange={onSearch}
            />
            {controls}
            <div className="selection-list">
              {items.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  aria-pressed={selected === item.id}
                  className={selected === item.id ? "selected" : ""}
                  onClick={() => onSelect(item.id)}
                >
                  <span>
                    <strong>{item.title}</strong>
                    {item.subtitle && <small>{item.subtitle}</small>}
                    {item.status}
                  </span>
                </button>
              ))}
              {!items.length && (
                <p className="selection-empty">표시할 항목이 없습니다.</p>
              )}
            </div>
            {footer && <div className="selection-footer">{footer}</div>}
          </>
        }
      >
        {children}
      </CatalogLayout>
    </div>
  );
}
