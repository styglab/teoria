import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Boxes, ChevronDown, ChevronRight, GitBranch, Plus, RefreshCw } from "lucide-react";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { CatalogLayout, FilterTabs, PageHeader, PageState, SearchField } from "../../components/workspace/WorkspaceLayout";
import { useSearchParams } from "react-router-dom";
import { type LinkEdge, type ObjectNode, type RuntimeContractGraph, type ValidationReport } from "../../api/registry";
import { ontologyApi, type OntologyBindingImpact, type OntologyDiff, type OntologySummary, type OntologyVersion, type OntologyVersionDetail } from "../../api/ontology";
import { DetailPanel } from "./DetailPanel";
import { OntologyGraph } from "./OntologyGraph";

type View = "graph" | "objects" | "relationships" | "rules" | "review";
const statusLabels: Record<string, string> = { draft: "초안", in_review: "검토 중", approved: "승인", published: "게시", deprecated: "사용 종료" };
const diffLabels: Record<string, string> = { added: "추가", changed: "변경", removed: "삭제" };

export function OntologyAuthoring() {
  const [params, setParams] = useSearchParams();
  const requestedVersion = params.get("version");
  const [namespace, setNamespace] = useState("teoria");
  const [ontologies, setOntologies] = useState<OntologySummary[]>([]);
  const [versions, setVersions] = useState<OntologyVersion[]>([]);
  const [detail, setDetail] = useState<OntologyVersionDetail | null>(null);
  const [view, setView] = useState<View>("objects");
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
  const loadRequest = useRef(0);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const request = ++loadRequest.current;
    setLoading(true); setError(null); setSelectedGraphItem(null);
    try {
      const target = requestedVersion ? await ontologyApi.ontologyVersion(requestedVersion) : null;
      const resolvedNamespace = target?.namespace ?? namespace;
      const result = await ontologyApi.ontologyVersions(resolvedNamespace);
      const preferred = result.items.find((item) => item.status === "published") ?? result.items[0];
      const nextDetail = target ?? (preferred ? await ontologyApi.ontologyVersion(preferred.ontology_version_id) : null);
      if (request !== loadRequest.current) return;
      setVersions(result.items);
      setDetail(nextDetail);
      if (resolvedNamespace !== namespace) setNamespace(resolvedNamespace);
    } catch (reason) { if (request === loadRequest.current) setError((reason as Error).message); }
    finally { if (request === loadRequest.current) setLoading(false); }
  }, [namespace, requestedVersion]);

  useEffect(() => { load(); return () => { loadRequest.current++; }; }, [load]);
  useEffect(() => {
    ontologyApi.authoredOntologies().then((result) => {
      setOntologies(result.items);
      if (!requestedVersion && !result.items.some((item) => item.namespace === namespace) && result.items[0]) setNamespace(result.items[0].namespace);
    }).catch((reason: Error) => setError(reason.message));
  }, []);

  const mutate = async (action: () => Promise<unknown>) => {
    if (busy) return;
    setBusy(true); setError(null);
    try { await action(); await load(); } catch (reason) { setError((reason as Error).message); }
    finally { setBusy(false); }
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
      ontologyApi.ontologyVersionValidation(detail.ontology_version_id),
      ontologyApi.ontologyVersionBindingImpact(detail.ontology_version_id),
      compareVersionId ? ontologyApi.ontologyVersionDiff(detail.ontology_version_id, compareVersionId) : Promise.resolve(null),
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

  return <CatalogLayout className="ontology-catalog" label="온톨로지 버전 탐색" sidebar={<>
    <h2>온톨로지</h2>
    <label className="catalog-select-label">업무 모델<select aria-label="온톨로지" value={namespace} disabled={busy} onChange={event => { setParams({}); setNamespace(event.target.value); }}>{ontologies.map(item => <option value={item.namespace} key={item.namespace}>{item.namespace}</option>)}</select></label>
    <div className="catalog-sidebar-heading"><span>버전</span><Button variant="ghost" size="sm" disabled={busy || loading || !detail} onClick={() => { const version = window.prompt("새 초안 버전"); if (version) mutate(() => ontologyApi.createOntologyDraft(namespace, version)); }}><Plus size={13}/>새 초안</Button></div>
    {versions.map(item => <button className={`catalog-version ${detail?.ontology_version_id === item.ontology_version_id ? "selected" : ""}`} aria-pressed={detail?.ontology_version_id === item.ontology_version_id} disabled={busy} key={item.ontology_version_id} onClick={() => setParams({ version: item.ontology_version_id })}><GitBranch size={16}/><span><strong>v{item.version}</strong><small>{statusLabels[item.status] ?? item.status}</small></span><ChevronRight size={14}/></button>)}
    {!loading && !versions.length && <p>등록된 버전이 없습니다.</p>}
  </>}>
    {error && <div className="workspace-error" role="alert">{error}<Button size="sm" variant="outline" onClick={load}>다시 조회</Button></div>}
    {loading ? <PageState loading title="온톨로지를 불러오고 있습니다…"/> : !detail ? <PageState title="표시할 온톨로지가 없습니다" description="다른 업무 모델을 선택하거나 연결 상태를 확인하세요."/> : <>
      <PageHeader title={`${detail.ontology_name} v${detail.version}`} description="업무 개념과 관계를 살펴보고 버전별 변경을 검토합니다." actions={<>
        <button className="page-icon-button" aria-label="온톨로지 새로고침" disabled={busy} onClick={load}><RefreshCw size={16}/></button>
        {detail.status === "draft" && <Button disabled={busy} onClick={() => mutate(() => ontologyApi.transitionOntology(detail.ontology_version_id, "submit"))}>검토 요청</Button>}
        {detail.status === "in_review" && <Button disabled={busy} onClick={() => mutate(() => ontologyApi.transitionOntology(detail.ontology_version_id, "approve"))}>승인</Button>}
        {detail.status === "approved" && <Button disabled={busy} onClick={() => mutate(() => ontologyApi.publishOntology(detail.ontology_version_id))}>게시</Button>}
      </>}><div className="page-header-meta"><code>{detail.namespace}</code><Badge variant={detail.status === "published" ? "success" : "outline"}>{statusLabels[detail.status] ?? detail.status}</Badge></div></PageHeader>
      {view !== "review" && <SearchField label="온톨로지 검색" placeholder="이름, Stable Key, 속성 검색" value={query} onChange={setQuery}/>}
      <div className="page-controls"><FilterTabs<View> label="온톨로지 보기" value={view} onChange={setView} items={[
        { id: "objects", label: "업무 개념", count: detail.objects.length },
        { id: "relationships", label: "관계", count: detail.relationships.length },
        { id: "rules", label: "규칙", count: detail.rules.length },
        { id: "graph", label: "관계도" }, { id: "review", label: "버전 검토" },
      ]}/>{view === "graph" && <label>도메인<select aria-label="도메인 필터" value={graphDomain} onChange={event => setGraphDomain(event.target.value)}><option value="all">모든 도메인</option>{domains.map(domain => <option value={domain} key={domain}>{domain}</option>)}</select></label>}</div>
      {view === "graph" && graph && <><div className="ontology-domain-legend">{domains.map((domain) => <button className={graphDomain === domain ? "active" : ""} key={domain} onClick={() => setGraphDomain(graphDomain === domain ? "all" : domain)}>{domain}</button>)}<span>업무 개념 {graph.nodes.length}개 · 관계 {graph.edges.length}개</span></div><div className="authored-ontology-graph"><OntologyGraph graph={graph} onSelect={setSelectedGraphItem} /></div></>}
      {view === "objects" && <div className="ontology-object-list">
        <div className="ontology-list-heading"><span>업무 개념</span><span>설명</span><span>속성</span></div>
        {objects.map(object => { const expanded = expandedObject === object.concept_id; return <article className={`ontology-object-row ${expanded ? "expanded" : ""}`} key={object.concept_id}>
          <button className="ontology-object-toggle" aria-expanded={expanded} onClick={() => setExpandedObject(expanded ? null : object.concept_id)}>
            <div className="ontology-object-name"><span className="page-item-icon"><Boxes size={18}/></span><div><strong>{object.name}</strong><code>{object.stable_key}</code></div></div>
            <p>{object.description || "설명 없음"}</p><span className="ontology-property-count">{object.properties.length}{expanded ? <ChevronDown size={16}/> : <ChevronRight size={16}/>}</span>
          </button>
          {expanded && <div className="ontology-object-detail"><div className="ontology-identity"><span>식별 기준</span><code>{object.identity_policy?.properties?.join(" + ") || "미정의"}</code></div>
            {object.properties.length ? <div className="ontology-property-table-wrap"><table className="page-table ontology-property-table"><thead><tr><th>속성</th><th>타입</th><th>설명</th><th>조건</th></tr></thead><tbody>{object.properties.map(property => <tr key={property.concept_id}><td><strong>{property.name}</strong><code>{property.stable_key}</code></td><td><code>{property.value_type}{property.cardinality === "many" ? "[]" : ""}</code></td><td>{property.description || "설명 없음"}</td><td>{[property.cardinality, property.unit, property.temporal ? "시점 속성" : null].filter(Boolean).join(" · ")}</td></tr>)}</tbody></table></div> : <p className="ontology-no-properties">등록된 속성이 없습니다.</p>}
          </div>}
        </article>; })}
        {!objects.length && <PageState title={query ? "조건에 맞는 업무 개념이 없습니다" : "등록된 업무 개념이 없습니다"}>{query && <Button variant="outline" onClick={() => setQuery("")}>검색 초기화</Button>}</PageState>}
      </div>}
      {view === "relationships" && <div className="page-table-wrap"><table className="page-table"><thead><tr><th>관계</th><th>출발 개념</th><th>도착 개념</th><th>조건</th></tr></thead><tbody>{relationships.map(link => <tr key={link.concept_id}><td><strong>{link.name}</strong><code>{link.stable_key}</code></td><td>{objectCodes.get(link.source_object_id) ?? link.source_object_id}</td><td>{objectCodes.get(link.target_object_id) ?? link.target_object_id}</td><td>{link.source_cardinality} → {link.target_cardinality}{link.temporal ? " · 시점 관계" : ""}</td></tr>)}</tbody></table>{!relationships.length && <PageState title={query ? "조건에 맞는 관계가 없습니다" : "등록된 관계가 없습니다"}/>}</div>}
      {view === "rules" && <div className="page-table-wrap"><table className="page-table"><thead><tr><th>규칙</th><th>설명</th><th>평가 방식</th></tr></thead><tbody>{rules.map(rule => <tr key={rule.concept_id}><td><strong>{rule.name}</strong><code>{rule.stable_key}</code></td><td>{rule.description || "설명 없음"}</td><td><code>{rule.evaluator_key ?? "선언형 규칙"}</code></td></tr>)}</tbody></table>{!rules.length && <PageState title={query ? "조건에 맞는 규칙이 없습니다" : "등록된 규칙이 없습니다"}/>}</div>}
      {view === "review" && <div className="ontology-review-dashboard">{reviewLoading ? <div className="loading-state">검토 정보를 계산하는 중입니다.</div> : <>
        <article><span>구조 검증</span><h3>{validation?.status === "valid" ? "구조 검증 통과" : "구조 검증 필요"}</h3><strong className={validation?.status === "valid" ? "review-ok" : "review-warning"}>진단 {validation?.diagnostic_count ?? 0}개</strong>{validation?.diagnostics.map((diagnostic) => <div className="review-diagnostic" key={`${diagnostic.code}:${diagnostic.path}`}><b>{diagnostic.severity}</b><code>{diagnostic.path}</code><p>{diagnostic.message}</p></div>)}</article>
        <article><span>의미 연결 영향</span><h3>{bindingImpact?.compatible ? "호환 가능" : "의미 연결 확인 필요"}</h3><strong className={bindingImpact?.compatible ? "review-ok" : "review-warning"}>비호환 {bindingImpact?.incompatible_binding_count ?? 0}개</strong>{bindingImpact?.incompatible_bindings.map((binding) => <div className="review-diagnostic" key={binding.binding_id}><code>{binding.stable_key}</code><p>{statusLabels[binding.status] ?? binding.status}</p></div>)}</article>
        <article className="ontology-diff"><header><div><span>버전 비교</span><h3>안정 개념 ID 변경</h3></div><select aria-label="비교 버전" value={compareVersionId} onChange={(event) => setCompareVersionId(event.target.value)}><option value="">비교 버전 없음</option>{versions.filter((version) => version.ontology_version_id !== detail.ontology_version_id).map((version) => <option value={version.ontology_version_id} key={version.ontology_version_id}>v{version.version} · {statusLabels[version.status] ?? version.status}</option>)}</select></header>{diff ? <div className="diff-columns">{(["added", "changed", "removed"] as const).map((kind) => <section key={kind}><h4>{diffLabels[kind]} <b>{diff[kind].length}</b></h4>{diff[kind].map((key) => <code key={key}>{conceptNames.get(key) ?? key}</code>)}</section>)}</div> : <p>비교할 이전 버전을 선택하세요.</p>}</article>
      </>}</div>}
    </>}
    {selectedGraphItem && <DetailPanel item={selectedGraphItem} mode="business" onClose={() => setSelectedGraphItem(null)} />}
  </CatalogLayout>;
}
