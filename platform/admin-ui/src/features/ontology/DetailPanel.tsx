import { X } from "lucide-react";
import type { LinkEdge, ObjectNode } from "../../api/admin";

export function DetailPanel({ item, onClose }: { item: ObjectNode | LinkEdge; onClose: () => void }) {
  const isLink = "link_type" in item;
  return (
    <aside className="detail-panel">
      <div className="detail-header">
        <div><span>{isLink ? "LINK TYPE" : "OBJECT TYPE"}</span><h2>{item.name}</h2><code>{item.id}</code></div>
        <button className="icon-button" onClick={onClose} aria-label="닫기"><X size={17} /></button>
      </div>
      <p>{item.description}</p>
      {isLink ? <>
        <div className="link-direction"><div><span>Source</span><code>{item.source}</code></div><div><span>Target</span><code>{item.target}</code></div></div>
        <h3>Registry</h3>
        <div className="primary-key"><span>Ontology</span><code>{item.ontology}</code></div>
      </> : <>
      {item.primary_key && <div className="primary-key"><span>Primary key</span><code>{item.primary_key}</code></div>}
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
