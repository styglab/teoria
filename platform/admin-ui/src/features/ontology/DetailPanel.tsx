import { X } from "lucide-react";
import type { LinkEdge, ObjectNode } from "../../api/admin";

export function DetailPanel({ item, onClose, mode = "runtime" }: { item: ObjectNode | LinkEdge; onClose: () => void; mode?: "runtime" | "business" }) {
  const isLink = "link_type" in item;
  const itemType = mode === "business"
    ? (isLink ? "RELATIONSHIP" : "BUSINESS OBJECT")
    : (isLink ? "LINK TYPE" : "OBJECT TYPE");
  return (
    <aside className="detail-panel">
      <div className="detail-header">
        <div><span>{itemType}</span><h2>{item.name}</h2><code>{item.id}</code></div>
        <button className="icon-button" onClick={onClose} aria-label="닫기"><X size={17} /></button>
      </div>
      <p>{item.description}</p>
      {isLink ? <>
        <div className="link-direction"><div><span>Source</span><code>{item.source}</code></div><div><span>Target</span><code>{item.target}</code></div></div>
        <h3>{mode === "business" ? "Ontology" : "Registry"}</h3>
        <div className="primary-key"><span>{mode === "business" ? "Namespace" : "Runtime domain"}</span><code>{item.ontology}</code></div>
      </> : <>
      {item.primary_key && <div className="primary-key"><span>{mode === "business" ? "Identity" : "Primary key"}</span><code>{item.primary_key}</code></div>}
      <h3>Properties <b>{item.properties.length}</b></h3>
      <div className="detail-properties">
        {item.properties.map((property) => (
          <div key={property.id}>
            <div><strong>{property.name}</strong><code>{property.type}{property.collection === "list" ? "[]" : ""}</code></div>
            <small>{property.id}</small>
            <p>{property.description}</p>
          </div>
        ))}
      </div>
      </>}
    </aside>
  );
}
