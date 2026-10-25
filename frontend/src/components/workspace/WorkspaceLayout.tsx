import type { ReactNode } from "react";
import { Search } from "lucide-react";

export function WorkspaceFrame({ children }: { children: ReactNode }) {
  return <div className="workspace-frame"><section className="workspace-surface">{children}</section></div>;
}

export function CatalogLayout({ sidebar, children, className = "", label }: { sidebar: ReactNode; children: ReactNode; className?: string; label: string }) {
  return <div className={`catalog-layout ${className}`}><aside className="catalog-sidebar" aria-label={label}>{sidebar}</aside><section className="catalog-content">{children}</section></div>;
}

export function PageHeader({ title, description, actions, children }: { title: ReactNode; description?: ReactNode; actions?: ReactNode; children?: ReactNode }) {
  return <header className="page-header"><div><h2>{title}</h2>{description && <p>{description}</p>}{children}</div>{actions && <div className="page-header-actions">{actions}</div>}</header>;
}

export function SearchField({ label, placeholder, value, onChange }: { label: string; placeholder: string; value: string; onChange: (value: string) => void }) {
  return <div className="page-search"><Search size={17} aria-hidden="true" /><input aria-label={label} placeholder={placeholder} value={value} onChange={event => onChange(event.target.value)} />{value && <button type="button" aria-label={`${label} 지우기`} onClick={() => onChange("")}>지우기</button>}</div>;
}

export function FilterTabs<T extends string>({ label, items, value, onChange, disabled }: { label: string; items: Array<{ id: T; label: string; count?: number | string }>; value: T; onChange: (value: T) => void; disabled?: boolean }) {
  return <nav className="page-filters" aria-label={label}>{items.map(item => <button type="button" key={item.id} aria-pressed={value === item.id} disabled={disabled} onClick={() => onChange(item.id)}>{item.label}{item.count !== undefined && <span>{item.count}</span>}</button>)}</nav>;
}

export function PageState({ title, description, loading = false, children }: { title: string; description?: string; loading?: boolean; children?: ReactNode }) {
  return <div className="page-state" role={loading ? "status" : undefined}><strong>{title}</strong>{description && <p>{description}</p>}{children}</div>;
}
