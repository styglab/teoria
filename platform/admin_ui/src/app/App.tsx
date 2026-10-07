import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { Boxes, Braces, CheckCircle2, Database, GitFork, Home, Inbox, Menu, PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { Link, Navigate, NavLink, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { adminApi, type CapabilitySummary, type LineageLink, type MappingSummary, type RegistryRelease, type SourceSummary, type ValidationReport } from "../api/admin";
import { Button } from "../components/ui/button";
import { BindingManager } from "../features/binding/BindingManager";
import { CapabilityStudio } from "../features/capability/CapabilityStudio";
import { ContextConsole } from "../features/context/ContextConsole";
import { SuggestionReview } from "../features/intelligence/SuggestionReview";
import { MetadataExplorer } from "../features/metadata/MetadataExplorer";
import { OntologyAuthoring } from "../features/ontology/OntologyAuthoring";

const sections = [
  { path: "/admin/ask", label: "Ask Teoria", description: "의미 기반 질문 실행", icon: Home },
  { path: "/admin/capabilities", label: "Capabilities", description: "기능 계약과 준비도", icon: Braces },
  { path: "/admin/data-catalog", label: "Data Catalog", description: "OpenMetadata 자산과 컬럼", icon: Database },
  { path: "/admin/review-queue", label: "Review Queue", description: "AI 제안 검토", icon: Inbox },
  { path: "/admin/semantic-bindings", label: "Semantic Bindings", description: "의미 연결과 승인", icon: GitFork },
  { path: "/admin/business-concepts", label: "Business Concepts", description: "Ontology authoring", icon: Boxes },
];

function FramedPage({ children }: { children: ReactNode }) {
  return <div className="h-full overflow-hidden p-4"><section className="h-full overflow-hidden rounded-xl border border-border bg-card">{children}</section></div>;
}

export function App() {
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const location = useLocation();
  const navigate = useNavigate();
  const [capabilities, setCapabilities] = useState<CapabilitySummary[]>([]);
  const [sources, setSources] = useState<SourceSummary[]>([]);
  const [mappings, setMappings] = useState<MappingSummary[]>([]);
  const [lineage, setLineage] = useState<LineageLink[]>([]);
  const [validation, setValidation] = useState<ValidationReport | null>(null);
  const [release, setRelease] = useState<RegistryRelease | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([adminApi.capabilities(), adminApi.sources(), adminApi.mappings(), adminApi.lineage(), adminApi.validation(), adminApi.registryRelease()])
      .then(([capabilityResponse, sourceResponse, mappingResponse, lineageResponse, validationResponse, releaseResponse]) => {
        setCapabilities(capabilityResponse.capabilities);
        setSources(sourceResponse.sources);
        setMappings(mappingResponse.mappings);
        setLineage(lineageResponse.links);
        setValidation(validationResponse);
        setRelease(releaseResponse);
      })
      .catch((reason: Error) => setError(reason.message));
  }, []);

  const current = sections.find((item) => location.pathname === item.path) ?? sections[0];
  return <div className={`min-h-screen bg-background text-foreground ${sidebarOpen ? "pl-64" : "pl-16"}`}>
    <aside className={`fixed inset-y-0 left-0 z-30 flex flex-col border-r border-border bg-background transition-[width] ${sidebarOpen ? "w-64" : "w-16"}`}>
      <Link to="/admin/ask" className="flex h-16 cursor-pointer items-center border-b border-border px-4" aria-label="Ask Teoria 홈">
        <div className="grid size-8 shrink-0 place-items-center rounded-lg bg-foreground text-background"><Braces className="size-4" /></div>
        {sidebarOpen && <div className="ml-3 min-w-0"><strong className="block text-sm tracking-tight">Teoria</strong><span className="block text-[11px] text-muted-foreground">Semantic Operations</span></div>}
      </Link>
      <nav className="flex-1 space-y-1 p-2" aria-label="주요 메뉴">
        {sections.map((item) => { const Icon = item.icon; return <NavLink key={item.path} to={item.path} className={({ isActive }) => `flex w-full cursor-pointer items-center gap-3 rounded-lg px-3 py-2.5 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${isActive ? "bg-muted text-foreground" : "text-muted-foreground hover:bg-muted/60 hover:text-foreground"}`} title={!sidebarOpen ? item.label : undefined}><Icon className="size-4 shrink-0" />{sidebarOpen && <span className="min-w-0"><strong className="block truncate text-xs font-medium">{item.label}</strong><small className="mt-0.5 block truncate text-[10px] text-muted-foreground">{item.description}</small></span>}</NavLink>; })}
      </nav>
      <div className="border-t border-border p-2"><button onClick={() => setSidebarOpen((value) => !value)} className="flex w-full cursor-pointer items-center gap-3 rounded-lg px-3 py-2 text-xs text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">{sidebarOpen ? <PanelLeftClose className="size-4" /> : <PanelLeftOpen className="size-4" />}{sidebarOpen && "사이드바 접기"}</button></div>
    </aside>

    <header className={`fixed inset-x-0 top-0 z-20 flex h-16 items-center justify-between border-b border-border bg-background/95 px-6 backdrop-blur ${sidebarOpen ? "left-64" : "left-16"}`}>
      <div className="flex items-center gap-3"><Menu className="size-4 text-muted-foreground md:hidden" /><div><h1 className="text-sm font-semibold tracking-tight">{current.label}</h1><p className="text-[11px] text-muted-foreground">{current.description}</p></div></div>
      <div className="flex items-center gap-2"><span className="hidden text-[11px] text-muted-foreground sm:inline">Registry {release?.version ?? "draft"}</span><span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[10px] ${validation?.status === "valid" ? "border-border text-foreground" : "border-destructive/30 text-destructive"}`}><CheckCircle2 className="size-3" />{validation?.status === "valid" ? "검증됨" : `${validation?.diagnostic_count ?? 0} issues`}</span></div>
    </header>

    <main className="h-screen pt-16">
      {error ? <div className="grid h-full place-items-center"><div className="rounded-lg border border-destructive/30 px-4 py-3 text-sm text-destructive">{error}</div></div> : <Routes>
        <Route path="/" element={<Navigate to="/admin/ask" replace />} />
        <Route path="/admin" element={<Navigate to="/admin/ask" replace />} />
        <Route path="/admin/ask" element={<ContextConsole />} />
        <Route path="/admin/capabilities" element={<CapabilityStudio capabilities={capabilities} sources={sources} mappings={mappings} lineage={lineage} validation={validation} onOpenBindings={() => navigate("/admin/semantic-bindings")} />} />
        <Route path="/admin/data-catalog" element={<FramedPage><MetadataExplorer /></FramedPage>} />
        <Route path="/admin/review-queue" element={<FramedPage><SuggestionReview /></FramedPage>} />
        <Route path="/admin/semantic-bindings" element={<FramedPage><BindingManager /></FramedPage>} />
        <Route path="/admin/business-concepts" element={<FramedPage><OntologyAuthoring /></FramedPage>} />
        <Route path="*" element={<Navigate to="/admin/ask" replace />} />
      </Routes>}
    </main>
  </div>;
}
