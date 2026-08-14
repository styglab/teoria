import { useEffect, useState } from "react";
import { Activity, Boxes, Braces, CircleDot, Database, GitFork, Moon, Network, Search, Sun, Workflow, X } from "lucide-react";
import { adminApi, type CapabilitySummary, type LineageLink, type LinkEdge, type MappingSummary, type ObjectNode, type OntologyGraph as GraphData, type OntologySummary, type Overview, type RegistryRelease, type SourceSummary, type ValidationReport } from "../api/admin";
import { MetricCard } from "../components/MetricCard";
import { DetailPanel } from "../features/ontology/DetailPanel";
import { OntologyGraph } from "../features/ontology/OntologyGraph";
import { CapabilitiesView, LineageView, MappingsView, SourcesView } from "../features/registry/RegistryViews";
import { ValidationView } from "../features/validation/ValidationView";

type Section = "ontologies" | "capabilities" | "sources" | "mappings" | "lineage";
type Theme = "light" | "dark";

const sectionCopy: Record<Exclude<Section, "ontologies">, { eyebrow: string; title: string; description: string }> = {
  capabilities: { eyebrow: "SEMANTIC OPERATIONS", title: "Capabilities", description: "사용자 의도를 실행 가능한 Source Operation과 Ontology 반환 타입으로 연결합니다." },
  sources: { eyebrow: "DATA CONTRACTS", title: "Sources", description: "Semantic Runtime이 직접 호출하거나 조회하는 외부 API와 Database Source를 확인합니다." },
  mappings: { eyebrow: "SEMANTIC BINDINGS", title: "Mappings", description: "Source 필드가 Ontology 속성과 객체로 변환되는 계약을 확인합니다." },
  lineage: { eyebrow: "REGISTRY LINEAGE", title: "Lineage", description: "Source에서 Mapping과 Capability를 거쳐 Ontology로 이어지는 의미 계보를 확인합니다." },
};

export function App() {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [ontologies, setOntologies] = useState<OntologySummary[]>([]);
  const [selectedOntology, setSelectedOntology] = useState<string>("");
  const [graph, setGraph] = useState<GraphData | null>(null);
  const [selectedItem, setSelectedItem] = useState<ObjectNode | LinkEdge | null>(null);
  const [validation, setValidation] = useState<ValidationReport | null>(null);
  const [registryRelease, setRegistryRelease] = useState<RegistryRelease | null>(null);
  const [capabilities, setCapabilities] = useState<CapabilitySummary[]>([]);
  const [sources, setSources] = useState<SourceSummary[]>([]);
  const [mappings, setMappings] = useState<MappingSummary[]>([]);
  const [lineage, setLineage] = useState<LineageLink[]>([]);
  const [section, setSection] = useState<Section>("ontologies");
  const [validationOpen, setValidationOpen] = useState(false);
  const [theme, setTheme] = useState<Theme>(() => {
    const saved = window.localStorage.getItem("teoria-admin-theme");
    if (saved === "light" || saved === "dark") return saved;
    return window.matchMedia?.("(prefers-color-scheme: light)").matches ? "light" : "dark";
  });
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    window.localStorage.setItem("teoria-admin-theme", theme);
  }, [theme]);

  useEffect(() => {
    Promise.all([adminApi.overview(), adminApi.ontologies(), adminApi.validation(), adminApi.registryRelease(), adminApi.capabilities(), adminApi.sources(), adminApi.mappings(), adminApi.lineage()])
      .then(([nextOverview, response, nextValidation, nextRegistryRelease, capabilityResponse, sourceResponse, mappingResponse, lineageResponse]) => {
        setOverview(nextOverview);
        setOntologies(response.ontologies);
        setValidation(nextValidation);
        setRegistryRelease(nextRegistryRelease);
        setCapabilities(capabilityResponse.capabilities);
        setSources(sourceResponse.sources);
        setMappings(mappingResponse.mappings);
        setLineage(lineageResponse.links);
        setSelectedOntology(response.ontologies.length ? "all" : "");
      })
      .catch((reason: Error) => setError(reason.message));
  }, []);

  useEffect(() => {
    if (!selectedOntology) return;
    setSelectedItem(null);
    adminApi.ontologyGraph(selectedOntology).then(setGraph).catch((reason: Error) => setError(reason.message));
  }, [selectedOntology]);

  const counts = overview?.counts;
  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand-mark"><CircleDot size={18} /></div>
        <div className="brand"><strong>Teoria</strong><span>Semantic Admin</span></div>
        <div className="global-search"><Search size={15} /><input placeholder="Registry 검색" disabled /><kbd>/</kbd></div>
        <span className={`release-badge ${registryRelease?.status ?? "draft"}`} title={registryRelease?.checksum ?? undefined}>Registry {registryRelease?.version ?? "Draft"}</span>
        <button className="theme-toggle" aria-label={`${theme === "dark" ? "라이트" : "다크"} 모드로 전환`} onClick={() => setTheme((value) => value === "dark" ? "light" : "dark")}>{theme === "dark" ? <Sun size={15} /> : <Moon size={15} />}</button>
        <button className={`status ${overview?.validation.status === "valid" ? "ok" : ""}`} onClick={() => setValidationOpen(true)}><Activity size={14} /> Registry {overview?.validation.status ?? "loading"}</button>
      </header>

      <aside className="sidebar">
        <nav>
          <span className="nav-group-label">REGISTRY</span>
          <button className={section === "ontologies" ? "active" : ""} onClick={() => setSection("ontologies")}><Network size={16} /> Ontologies</button>
          <button className={section === "capabilities" ? "active" : ""} onClick={() => { setSection("capabilities"); setSelectedItem(null); }}><Braces size={16} /> Capabilities</button>
          <button className={section === "sources" ? "active" : ""} onClick={() => { setSection("sources"); setSelectedItem(null); }}><Database size={16} /> Sources</button>
          <button className={section === "mappings" ? "active" : ""} onClick={() => { setSection("mappings"); setSelectedItem(null); }}><GitFork size={16} /> Mappings</button>
          <button className={section === "lineage" ? "active" : ""} onClick={() => { setSection("lineage"); setSelectedItem(null); }}><Workflow size={16} /> Lineage</button>
        </nav>
        {section === "ontologies" && <div className="ontology-list">
          <span>ONTOLOGIES</span>
          <button className={selectedOntology === "all" ? "selected" : ""} onClick={() => setSelectedOntology("all")}>
            <i /><div><strong>전체 Ontology</strong><small>{overview?.counts.object_types ?? 0} objects · {overview?.counts.link_types ?? 0} links</small></div>
          </button>
          {ontologies.map((ontology) => (
            <button key={ontology.id} className={ontology.id === selectedOntology ? "selected" : ""} onClick={() => setSelectedOntology(ontology.id)}>
              <i /><div><strong>{ontology.name}</strong><small>{ontology.object_count} objects · {ontology.link_count} links</small></div>
            </button>
          ))}
        </div>}
      </aside>

      <main>
        <section className="overview-row">
          <MetricCard label="Ontologies" value={counts?.ontologies ?? 0} icon={<Network size={17} />} />
          <MetricCard label="Object types" value={counts?.object_types ?? 0} icon={<Boxes size={17} />} />
          <MetricCard label="Link types" value={counts?.link_types ?? 0} icon={<GitFork size={17} />} />
          <MetricCard label="Capabilities" value={counts?.capabilities ?? 0} icon={<Braces size={17} />} />
        </section>
        {section === "ontologies" ? <section className="workspace">
          <div className="workspace-header">
            <div><span>ONTOLOGY EXPLORER</span><h1>{graph?.ontology.name ?? "Registry 불러오는 중"}</h1><p>{graph?.ontology.description}</p></div>
            {graph && <div className="graph-counts"><b>{graph.nodes.length}</b> nodes <b>{graph.edges.length}</b> edges</div>}
          </div>
          <div className="canvas-wrap">
            {error && <div className="error-state">{error}</div>}
            {!error && graph && <OntologyGraph graph={graph} onSelect={setSelectedItem} />}
            {!error && !graph && <div className="loading-state">Registry graph를 구성하고 있습니다…</div>}
          </div>
        </section> : <section className="workspace">
          <div className="workspace-header">
            <div><span>{sectionCopy[section].eyebrow}</span><h1>{sectionCopy[section].title}</h1><p>{sectionCopy[section].description}</p></div>
            <div className="graph-counts"><b>{section === "capabilities" ? capabilities.length : section === "sources" ? sources.length : section === "mappings" ? mappings.length : lineage.length}</b> items</div>
          </div>
          <div className="canvas-wrap">
            {error ? <div className="error-state">{error}</div> : section === "capabilities" ? <CapabilitiesView items={capabilities} /> : section === "sources" ? <SourcesView items={sources} /> : section === "mappings" ? <MappingsView items={mappings} /> : <LineageView links={lineage} />}
          </div>
        </section>}
      </main>
      {selectedItem && <DetailPanel item={selectedItem} onClose={() => setSelectedItem(null)} />}
      {validationOpen && <div className="validation-backdrop" onMouseDown={() => setValidationOpen(false)}>
        <section className="validation-dialog" role="dialog" aria-modal="true" aria-labelledby="validation-title" onMouseDown={(event) => event.stopPropagation()}>
          <header><div><span>REGISTRY DIAGNOSTICS</span><h2 id="validation-title">Registry Validation</h2><p>Semantic Registry의 구조와 교차 계약 검증 결과입니다.</p></div><button className="icon-button" aria-label="닫기" onClick={() => setValidationOpen(false)}><X size={16} /></button></header>
          <div className="validation-dialog-body">{error ? <div className="error-state">{error}</div> : <ValidationView report={validation} />}</div>
        </section>
      </div>}
    </div>
  );
}
