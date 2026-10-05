import { useCallback, useEffect, useState } from "react";
import { adminApi, type OntologyVersion, type OntologyVersionDetail } from "../../api/admin";

export function OntologyAuthoring() {
  const [namespace, setNamespace] = useState("procurement");
  const [versions, setVersions] = useState<OntologyVersion[]>([]);
  const [detail, setDetail] = useState<OntologyVersionDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    try {
      const result = await adminApi.ontologyVersions(namespace);
      setVersions(result.items);
      setDetail(result.items[0] ? await adminApi.ontologyVersion(result.items[0].ontology_version_id) : null);
    } catch (reason) { setError((reason as Error).message); }
  }, [namespace]);
  useEffect(() => { load(); }, [load]);
  const mutate = async (action: () => Promise<unknown>) => {
    setError(null);
    try { await action(); await load(); } catch (reason) { setError((reason as Error).message); }
  };
  return <div className="authoring-layout">
    <aside className="registry-list">
      <header className="authoring-toolbar"><select value={namespace} onChange={(event) => setNamespace(event.target.value)}><option value="procurement">procurement</option><option value="company">company</option></select><button onClick={() => { const version = window.prompt("새 Draft 버전"); if (version) mutate(() => adminApi.createOntologyDraft(namespace, version)); }}>Create Draft</button></header>
      {versions.map((item) => <button className={`registry-card ${detail?.ontology_version_id === item.ontology_version_id ? "selected" : ""}`} key={item.ontology_version_id} onClick={() => adminApi.ontologyVersion(item.ontology_version_id).then(setDetail)}><strong>v{item.version}</strong><small>{item.status}</small></button>)}
    </aside>
    <section>{error && <div className="error-state">{error}</div>}{detail && <><header className="authoring-toolbar"><div><span>BUSINESS ONTOLOGY</span><h2>{detail.ontology_name} v{detail.version}</h2><p>{detail.status}</p></div><div className="suggestion-actions">{detail.status === "draft" && <button onClick={() => mutate(() => adminApi.transitionOntology(detail.ontology_version_id, "submit"))}>Submit Review</button>}{detail.status === "in_review" && <button onClick={() => mutate(() => adminApi.transitionOntology(detail.ontology_version_id, "approve"))}>Approve</button>}{detail.status === "approved" && <button onClick={() => mutate(() => adminApi.publishOntology(detail.ontology_version_id))}>Publish</button>}</div></header>
      <div className="registry-list">{detail.objects.map((object) => <article className="registry-card" key={object.concept_id}><header><div><span>OBJECT</span><h3>{object.code} · {object.name}</h3></div></header><p>{object.description}</p><small>{object.properties.map((property) => `${property.code}: ${property.value_type}`).join(" · ") || "properties 없음"}</small></article>)}</div></>}</section>
  </div>;
}
