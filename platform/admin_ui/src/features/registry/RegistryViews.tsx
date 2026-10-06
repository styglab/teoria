import { ArrowRight, Braces, Database, GitFork } from "lucide-react";
import type { CapabilitySummary, LineageLink, MappingSummary, SourceSummary } from "../../api/admin";

function Empty({ label }: { label: string }) {
  return <div className="loading-state">등록된 {label}이 없습니다.</div>;
}

export function CapabilitiesView({ items }: { items: CapabilitySummary[] }) {
  if (!items.length) return <Empty label="Capability" />;
  return <div className="registry-grid">{items.map((item) => <article key={item.id}>
    <header><Braces size={16} /><div><strong>{item.name}</strong><code>{item.id}</code></div></header>
    <p>{item.description}</p>
    <footer><span>{item.inputs.length} inputs</span><span>{item.steps.length} steps</span><span>{item.returns.length} returns</span></footer>
  </article>)}</div>;
}

export function SourcesView({ items }: { items: SourceSummary[] }) {
  if (!items.length) return <Empty label="Source" />;
  return <div className="registry-grid">{items.map((item) => <article key={item.id}>
    <header><Database size={16} /><div><strong>{item.name}</strong><code>{item.id}</code></div><b>{item.type}</b></header>
    <p>{item.description ?? `${item.provider ?? "Teoria"}에서 제공하는 ${item.type.toUpperCase()} Source`}</p>
    <footer><span>{item.provider ?? "Teoria Data DB"}</span><span>{item.items} {item.item_label}</span></footer>
  </article>)}</div>;
}

export function MappingsView({ items }: { items: MappingSummary[] }) {
  if (!items.length) return <Empty label="Mapping" />;
  return <div className="registry-grid">{items.map((item) => <article key={item.id}>
    <header><GitFork size={16} /><div><strong>{item.name}</strong><code>{item.id}</code></div></header>
    <p>{item.description}</p>
    <footer><span>→ {item.ontology}</span><span>{item.property_count} properties</span><span>{item.binding_count} bindings</span></footer>
  </article>)}</div>;
}

export function LineageView({ links }: { links: LineageLink[] }) {
  if (!links.length) return <Empty label="Lineage" />;
  return <div className="lineage-list">{links.map((link, index) => <article key={`${link.kind}-${link.from}-${link.via}-${link.to}-${index}`}>
    <div><small>SOURCE</small><strong>{link.from}</strong></div><ArrowRight size={15} /><div className="via"><small>{link.kind.toUpperCase()}</small><strong>{link.via}</strong></div><ArrowRight size={15} /><div><small>ONTOLOGY</small><strong>{link.to}</strong></div>
  </article>)}</div>;
}
