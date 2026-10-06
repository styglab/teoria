import { useCallback, useEffect, useMemo, useState } from "react";
import { adminApi, type LinkEdge, type ObjectNode, type OntologyBindingImpact, type OntologyDiff, type OntologySummary, type OntologyVersion, type OntologyVersionDetail, type RuntimeContractGraph, type ValidationReport } from "../../api/admin";
import { DetailPanel } from "./DetailPanel";
import { OntologyGraph } from "./OntologyGraph";

type View = "graph" | "objects" | "relationships" | "rules" | "review";

export function OntologyAuthoring() {
  const [namespace, setNamespace] = useState("teoria");
  const [ontologies, setOntologies] = useState<OntologySummary[]>([]);
  const [versions, setVersions] = useState<OntologyVersion[]>([]);
  const [detail, setDetail] = useState<OntologyVersionDetail | null>(null);
  const [view, setView] = useState<View>("graph");
  const [query, setQuery] = useState("");
  const [graphDomain, setGraphDomain] = useState("all");
  const [expandedObject, setExpandedObject] = useState<string | null>(null);
  const [selectedGraphItem, setSelectedGraphItem] = useState<ObjectNode | LinkEdge | null>(null);
  const [compareVersionId, setCompareVersionId] = useState<string>("");
  const [validation, setValidation] = useState<ValidationReport | null>(null);
  const [bindingImpact, setBindingImpact] = useState<OntologyBindingImpact | null>(null);
  const [diff, setDiff] = useState<OntologyDiff | null>(null);
  const [reviewLoading, setReviewLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const result = await adminApi.ontologyVersions(namespace);
      setVersions(result.items);
      const preferred = result.items.find((item) => item.status === "published") ?? result.items[0];
      setDetail(preferred ? await adminApi.ontologyVersion(preferred.ontology_version_id) : null);
    } catch (reason) { setError((reason as Error).message); }
  }, [namespace]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    adminApi.authoredOntologies().then((result) => {
      setOntologies(result.items);
      if (!result.items.some((item) => item.namespace === namespace) && result.items[0]) setNamespace(result.items[0].namespace);
    }).catch((reason: Error) => setError(reason.message));
  }, []);

  const mutate = async (action: () => Promise<unknown>) => {
    setError(null);
    try { await action(); await load(); } catch (reason) { setError((reason as Error).message); }
  };
  const objectCodes = useMemo(() => new Map(detail?.objects.map((item) => [item.business_object_id, item.code]) ?? []), [detail]);
  const normalized = query.trim().toLocaleLowerCase();
  const objects = useMemo(() => detail?.objects.filter((item) => !normalized || [item.code, item.name, item.description, item.stable_key, ...item.properties.flatMap((property) => [property.code, property.name, property.stable_key])].some((value) => value?.toLocaleLowerCase().includes(normalized))) ?? [], [detail, normalized]);
  const relationships = useMemo(() => detail?.relationships.filter((item) => !normalized || [item.code, item.name, item.stable_key, objectCodes.get(item.source_object_id), objectCodes.get(item.target_object_id)].some((value) => value?.toLocaleLowerCase().includes(normalized))) ?? [], [detail, normalized]);
  const rules = useMemo(() => detail?.rules.filter((item) => !normalized || [item.code, item.name, item.description, item.stable_key].some((value) => value?.toLocaleLowerCase().includes(normalized))) ?? [], [detail, normalized]);
  const domains = useMemo(() => [...new Set(detail?.objects.map((item) => item.stable_key.split(".")[0]).filter(Boolean) ?? [])].sort(), [detail]);
  const graph = useMemo<RuntimeContractGraph | null>(() => {
    if (!detail) return null;
    const domainObjects = detail.objects.filter((object) => graphDomain === "all" || object.stable_key.startsWith(`${graphDomain}.`));
    const domainObjectIds = new Set(domainObjects.map((object) => object.business_object_id));
    const domainRelationships = detail.relationships.filter((relationship) => domainObjectIds.has(relationship.source_object_id) && domainObjectIds.has(relationship.target_object_id));
    const graphQuery = normalized;
    const matchedRelationships = domainRelationships.filter((relationship) => !graphQuery || [relationship.code, relationship.name, relationship.stable_key].some((value) => value.toLocaleLowerCase().includes(graphQuery)));
    const visibleIds = new Set(domainObjects.filter((object) => !graphQuery || [object.code, object.name, object.description, object.stable_key, ...object.properties.flatMap((property) => [property.code, property.name, property.stable_key])].some((value) => value?.toLocaleLowerCase().includes(graphQuery))).map((object) => object.business_object_id));
    if (graphQuery) matchedRelationships.forEach((relationship) => { visibleIds.add(relationship.source_object_id); visibleIds.add(relationship.target_object_id); });
    const visibleObjects = domainObjects.filter((object) => visibleIds.has(object.business_object_id));
    const visibleRelationships = domainRelationships.filter((relationship) => visibleIds.has(relationship.source_object_id) && visibleIds.has(relationship.target_object_id));
    return {
    runtime_contract: {
      id: detail.namespace,
      name: `${detail.ontology_name} v${detail.version}`,
      description: `${detail.status} Business Ontology visualization`,
    },
    nodes: visibleObjects.map((object) => ({
      id: object.business_object_id,
      ontology: detail.namespace,
      object_type: object.code,
      group: object.stable_key.split(".")[0],
      name: object.name,
      description: object.description,
      primary_key: object.identity_policy?.properties?.join(" + ") || null,
      external: false,
      properties: object.properties.map((property) => ({
        id: property.stable_key,
        name: property.name,
        description: property.description,
        type: property.value_type,
        collection: property.cardinality === "many" ? "list" : "scalar",
      })),
    })),
    edges: visibleRelationships.map((relationship) => ({
      id: relationship.concept_id,
      ontology: detail.namespace,
      link_type: relationship.code,
      name: relationship.name,
      description: relationship.stable_key,
      source: relationship.source_object_id,
      target: relationship.target_object_id,
    })),
    };
  }, [detail, graphDomain, normalized]);

  useEffect(() => {
    if (!detail) return;
    const preferred = detail.based_on_version_id
      ?? versions.find((version) => version.ontology_version_id !== detail.ontology_version_id && version.status === "published")?.ontology_version_id
      ?? versions.find((version) => version.ontology_version_id !== detail.ontology_version_id)?.ontology_version_id
      ?? "";
    setCompareVersionId(preferred);
    setValidation(null);
    setBindingImpact(null);
    setDiff(null);
  }, [detail, versions]);

  useEffect(() => {
    if (view !== "review" || !detail) return;
    let cancelled = false;
    setReviewLoading(true);
    Promise.all([
      adminApi.ontologyVersionValidation(detail.ontology_version_id),
      adminApi.ontologyVersionBindingImpact(detail.ontology_version_id),
      compareVersionId ? adminApi.ontologyVersionDiff(detail.ontology_version_id, compareVersionId) : Promise.resolve(null),
    ]).then(([nextValidation, nextImpact, nextDiff]) => {
      if (cancelled) return;
      setValidation(nextValidation);
      setBindingImpact(nextImpact);
      setDiff(nextDiff);
    }).catch((reason: Error) => { if (!cancelled) setError(reason.message); }).finally(() => { if (!cancelled) setReviewLoading(false); });
    return () => { cancelled = true; };
  }, [compareVersionId, detail, view]);

  const conceptNames = useMemo(() => {
    const names = new Map<string, string>();
    detail?.objects.forEach((object) => {
      names.set(`object:${object.concept_id}`, object.stable_key);
      object.properties.forEach((property) => names.set(`property:${property.concept_id}`, property.stable_key));
    });
    detail?.relationships.forEach((relationship) => names.set(`relationship:${relationship.concept_id}`, relationship.stable_key));
    detail?.rules.forEach((rule) => names.set(`rule:${rule.concept_id}`, rule.stable_key));
    return names;
  }, [detail]);

  return <div className="authoring-layout">
    <aside className="registry-list">
      <header className="authoring-toolbar"><select aria-label="Ontology" value={namespace} onChange={(event) => setNamespace(event.target.value)}>{ontologies.map((item) => <option value={item.namespace} key={item.namespace}>{item.namespace} · {item.latest_status ?? "empty"}</option>)}</select><button onClick={() => { const version = window.prompt("새 Draft 버전"); if (version) mutate(() => adminApi.createOntologyDraft(namespace, version)); }}>Create Draft</button></header>
      {versions.map((item) => <button className={`registry-card ${detail?.ontology_version_id === item.ontology_version_id ? "selected" : ""}`} key={item.ontology_version_id} onClick={() => adminApi.ontologyVersion(item.ontology_version_id).then(setDetail)}><strong>v{item.version}</strong><small className={`ontology-status ${item.status}`}>{item.status}</small></button>)}
    </aside>
    <section>{error && <div className="error-state">{error}</div>}{detail && <>
      <header className="authoring-toolbar"><div><span>BUSINESS ONTOLOGY</span><h2>{detail.ontology_name} v{detail.version}</h2><p><code>{detail.namespace}</code> · {detail.status}</p></div><div className="suggestion-actions">{detail.status === "draft" && <button onClick={() => mutate(() => adminApi.transitionOntology(detail.ontology_version_id, "submit"))}>Submit Review</button>}{detail.status === "in_review" && <button onClick={() => mutate(() => adminApi.transitionOntology(detail.ontology_version_id, "approve"))}>Approve</button>}{detail.status === "approved" && <button onClick={() => mutate(() => adminApi.publishOntology(detail.ontology_version_id))}>Publish</button>}</div></header>
      <div className="authoring-summary"><span><b>{detail.objects.length}</b> objects</span><span><b>{detail.objects.reduce((count, item) => count + item.properties.length, 0)}</b> properties</span><span><b>{detail.relationships.length}</b> links</span><span><b>{detail.rules.length}</b> rules</span></div>
      <div className="ontology-review-toolbar"><div className="ontology-tabs"><button className={view === "graph" ? "active" : ""} onClick={() => setView("graph")}>Graph</button><button className={view === "objects" ? "active" : ""} onClick={() => setView("objects")}>Objects</button><button className={view === "relationships" ? "active" : ""} onClick={() => setView("relationships")}>Links</button><button className={view === "rules" ? "active" : ""} onClick={() => setView("rules")}>Rules</button><button className={view === "review" ? "active" : ""} onClick={() => setView("review")}>Review</button></div>{view !== "review" && <div className="ontology-filter-controls">{view === "graph" && <select aria-label="도메인 필터" value={graphDomain} onChange={(event) => setGraphDomain(event.target.value)}><option value="all">모든 도메인</option>{domains.map((domain) => <option value={domain} key={domain}>{domain}</option>)}</select>}<input aria-label="온톨로지 검색" placeholder="이름, Stable Key, 속성 검색" value={query} onChange={(event) => setQuery(event.target.value)} /></div>}</div>
      {view === "graph" && graph && <><div className="ontology-domain-legend">{domains.map((domain) => <button className={graphDomain === domain ? "active" : ""} key={domain} onClick={() => setGraphDomain(graphDomain === domain ? "all" : domain)}>{domain}</button>)}<span>{graph.nodes.length} objects · {graph.edges.length} links</span></div><div className="authored-ontology-graph"><OntologyGraph graph={graph} onSelect={setSelectedGraphItem} /></div></>}
      {view === "objects" && <div className="ontology-review-list">{objects.map((object) => { const expanded = expandedObject === object.concept_id; return <article className={`ontology-review-card ${expanded ? "expanded" : ""}`} key={object.concept_id}><button className="ontology-card-heading" onClick={() => setExpandedObject(expanded ? null : object.concept_id)}><div><span>OBJECT</span><h3>{object.name} <small>{object.code}</small></h3><code>{object.stable_key}</code></div><b>{object.properties.length} properties</b></button><p>{object.description}</p>{expanded && <div className="ontology-properties"><div className="ontology-identity"><span>Identity</span><code>{object.identity_policy?.properties?.join(" + ") || "not defined"}</code></div>{object.properties.map((property) => <div key={property.concept_id}><div><strong>{property.name}</strong><code>{property.code}: {property.value_type}{property.cardinality === "many" ? "[]" : ""}</code></div><small>{property.stable_key}</small>{property.description && <p>{property.description}</p>}<em>{[property.cardinality, property.unit, property.temporal ? "temporal" : null].filter(Boolean).join(" · ")}</em></div>)}</div>}</article>; })}</div>}
      {view === "relationships" && <div className="ontology-review-list">{relationships.map((link) => <article className="ontology-review-card" key={link.concept_id}><span>LINK</span><h3>{link.name} <small>{link.code}</small></h3><code>{link.stable_key}</code><div className="ontology-link"><strong>{objectCodes.get(link.source_object_id) ?? link.source_object_id}</strong><span>→</span><strong>{objectCodes.get(link.target_object_id) ?? link.target_object_id}</strong></div><small>{link.source_cardinality} → {link.target_cardinality}{link.temporal ? " · temporal" : ""}</small></article>)}</div>}
      {view === "rules" && <div className="ontology-review-list">{rules.map((rule) => <article className="ontology-review-card" key={rule.concept_id}><span>RULE</span><h3>{rule.name} <small>{rule.code}</small></h3><code>{rule.stable_key}</code><p>{rule.description}</p><small>{rule.evaluator_key ?? "declarative"}</small></article>)}</div>}
      {view === "review" && <div className="ontology-review-dashboard">{reviewLoading ? <div className="loading-state">검토 정보를 계산하는 중입니다.</div> : <>
        <article><span>VALIDATION</span><h3>{validation?.status === "valid" ? "구조 검증 통과" : "구조 검증 필요"}</h3><strong className={validation?.status === "valid" ? "review-ok" : "review-warning"}>{validation?.diagnostic_count ?? 0} diagnostics</strong>{validation?.diagnostics.map((diagnostic) => <div className="review-diagnostic" key={`${diagnostic.code}:${diagnostic.path}`}><b>{diagnostic.severity}</b><code>{diagnostic.path}</code><p>{diagnostic.message}</p></div>)}</article>
        <article><span>BINDING IMPACT</span><h3>{bindingImpact?.compatible ? "호환 가능" : "Binding 확인 필요"}</h3><strong className={bindingImpact?.compatible ? "review-ok" : "review-warning"}>{bindingImpact?.incompatible_binding_count ?? 0} incompatible</strong>{bindingImpact?.incompatible_bindings.map((binding) => <div className="review-diagnostic" key={binding.binding_id}><code>{binding.stable_key}</code><p>{binding.status}</p></div>)}</article>
        <article className="ontology-diff"><header><div><span>SEMANTIC DIFF</span><h3>Stable Concept 변경</h3></div><select aria-label="비교 버전" value={compareVersionId} onChange={(event) => setCompareVersionId(event.target.value)}><option value="">비교 버전 없음</option>{versions.filter((version) => version.ontology_version_id !== detail.ontology_version_id).map((version) => <option value={version.ontology_version_id} key={version.ontology_version_id}>v{version.version} · {version.status}</option>)}</select></header>{diff ? <div className="diff-columns">{(["added", "changed", "removed"] as const).map((kind) => <section key={kind}><h4>{kind} <b>{diff[kind].length}</b></h4>{diff[kind].map((key) => <code key={key}>{conceptNames.get(key) ?? key}</code>)}</section>)}</div> : <p>비교할 이전 버전을 선택하세요.</p>}</article>
      </>}</div>}
    </>}</section>
    {selectedGraphItem && <DetailPanel item={selectedGraphItem} mode="business" onClose={() => setSelectedGraphItem(null)} />}
  </div>;
}
