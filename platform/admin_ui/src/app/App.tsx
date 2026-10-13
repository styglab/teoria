import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { Boxes, Braces, CheckCircle2, Database, GitFork, Home, Inbox, Menu, PanelLeftClose, PanelLeftOpen, ShieldCheck, Wrench } from "lucide-react";
import { Link, Navigate, NavLink, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { adminApi, type CapabilitySummary, type LineageLink, type MappingSummary, type RegistryRelease, type SourceSummary, type ValidationReport } from "../api/admin";
import { BindingManager } from "../features/binding/BindingManager";
import { CapabilityStudio } from "../features/capability/CapabilityStudio";
import { ContextConsole } from "../features/context/ContextConsole";
import { SuggestionReview } from "../features/intelligence/SuggestionReview";
import { MetadataExplorer } from "../features/metadata/MetadataExplorer";
import { MetadataAssetPage } from "../features/metadata/MetadataAssetPage";
import { Overview, OperationsSettings } from "../features/overview/Overview";
import { GovernanceOverview } from "../features/governance/GovernanceOverview";
import { AdminAccess, AdminAccessProvider } from "../features/access/AdminAccess";
import { OntologyAuthoring } from "../features/ontology/OntologyAuthoring";

const sections = [
  { path: "/admin/overview", label: "현황", description: "연결 상태와 작업 현황", icon: Home, group: "전체" },
  { path: "/admin/data-catalog", label: "데이터 자산", description: "기술·운영·의미 메타데이터", icon: Database, group: "데이터 카탈로그" },
  { path: "/admin/semantic-model/ontology", label: "온톨로지", description: "업무 개념·관계·게시 버전", icon: Boxes, group: "의미 모델" },
  { path: "/admin/semantic-model/bindings", label: "의미 연결", description: "용어·자산·기능 연결", icon: GitFork, group: "의미 모델" },
  { path: "/admin/governance", label: "메타데이터 공백", description: "설명·소유자·분류 누락", icon: ShieldCheck, group: "거버넌스" },
  { path: "/admin/changes/review", label: "제안 검토", description: "AI 제안·근거·적용 결과", icon: Inbox, group: "검토·적용" },
  { path: "/admin/operations", label: "연결 및 수집", description: "메타데이터와 파이프라인 운영", icon: Wrench, group: "운영" },
  { path: "/admin/developer/capabilities", label: "기능 계약", description: "Capability와 준비도", icon: Braces, group: "개발 도구" },
  { path: "/admin/developer/ask", label: "질문 테스트", description: "의미 기반 실행 결과 검증", icon: Home, group: "개발 도구" },
];

function FramedPage({ children }: { children: ReactNode }) {
  return <div className="h-full overflow-hidden p-4"><section className="h-full overflow-hidden rounded-xl border border-border bg-card">{children}</section></div>;
}

export function App() { return <AdminAccessProvider><AdminWorkspace /></AdminAccessProvider>; }

function AdminWorkspace() {
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
    const requests = [
      {label:"기능",load:()=>adminApi.capabilities().then(value=>setCapabilities(value.capabilities))},
      {label:"소스",load:()=>adminApi.sources().then(value=>setSources(value.sources))},
      {label:"매핑",load:()=>adminApi.mappings().then(value=>setMappings(value.mappings))},
      {label:"계보",load:()=>adminApi.lineage().then(value=>setLineage(value.links))},
      {label:"검증",load:()=>adminApi.validation().then(setValidation)},
      {label:"게시 버전",load:()=>adminApi.registryRelease().then(setRelease)},
    ];
    Promise.allSettled(requests.map(request=>request.load())).then(results=>{
      const unavailable=results.flatMap((result,index)=>result.status==="rejected"?[requests[index].label]:[]);
      if(unavailable.length)setError(`${unavailable.join(", ")} 정보를 조회하지 못했습니다. 다른 화면은 계속 사용할 수 있습니다.`);
    });
  }, []);

  const current = sections.find((item) => location.pathname === item.path || location.pathname.startsWith(item.path + "/")) ?? sections[0];
  return <div className={`min-h-screen bg-background text-foreground ${sidebarOpen ? "pl-64" : "pl-16"}`}>
    <aside className={`fixed inset-y-0 left-0 z-30 flex flex-col border-r border-border bg-background transition-[width] ${sidebarOpen ? "w-64" : "w-16"}`}>
      <Link to="/admin/overview" className="flex h-16 cursor-pointer items-center border-b border-border px-4" aria-label="Teoria 개요">
        <div className="grid size-8 shrink-0 place-items-center rounded-lg bg-foreground text-background"><Braces className="size-4" /></div>
        {sidebarOpen && <div className="ml-3 min-w-0"><strong className="block text-sm tracking-tight">Teoria</strong><span className="block text-[11px] text-muted-foreground">메타데이터·온톨로지 관리</span></div>}
      </Link>
      <nav className="flex-1 overflow-y-auto space-y-1 p-2" aria-label="주요 메뉴">
        {sections.map((item, index) => { const Icon = item.icon; return <div key={item.path}>{sidebarOpen && (index === 0 || sections[index - 1].group !== item.group) && <p className="nav-group-label">{item.group}</p>}<NavLink to={item.path} className={({ isActive }) => `flex w-full cursor-pointer items-center gap-3 rounded-lg px-3 py-2.5 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${isActive ? "bg-muted text-foreground" : "text-muted-foreground hover:bg-muted/60 hover:text-foreground"}`} title={!sidebarOpen ? item.label : undefined}><Icon className="size-4 shrink-0" />{sidebarOpen && <span className="min-w-0"><strong className="block truncate text-xs font-medium">{item.label}</strong><small className="mt-0.5 block truncate text-[10px] text-muted-foreground">{item.description}</small></span>}</NavLink></div>; })}
      </nav>
      <div className="border-t border-border p-2"><button onClick={() => setSidebarOpen((value) => !value)} className="flex w-full cursor-pointer items-center gap-3 rounded-lg px-3 py-2 text-xs text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">{sidebarOpen ? <PanelLeftClose className="size-4" /> : <PanelLeftOpen className="size-4" />}{sidebarOpen && "사이드바 접기"}</button></div>
    </aside>

    <header className={`fixed inset-x-0 top-0 z-20 flex h-16 items-center justify-between border-b border-border bg-background/95 px-6 backdrop-blur ${sidebarOpen ? "left-64" : "left-16"}`}>
      <div className="flex items-center gap-3"><Menu className="size-4 text-muted-foreground md:hidden" /><div><p className="text-[10px] font-medium text-muted-foreground">{current.group}</p><h1 className="text-sm font-semibold tracking-tight">{current.label}</h1></div></div>
      <div className="flex items-center gap-2 pr-48"><span className="hidden text-[11px] text-muted-foreground sm:inline">Registry {release?.version ?? "draft"}</span><span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[10px] ${validation?.status === "valid" ? "border-border text-foreground" : "border-destructive/30 text-destructive"}`}><CheckCircle2 className="size-3" />{validation ? validation.status === "valid" ? "Registry 검증됨" : `${validation.diagnostic_count} issues` : "Registry 확인 중"}</span></div>
    </header>

    <main className="workspace-main h-screen pt-16">
      <Routes>
        <Route path="/" element={<Navigate to="/admin/overview" replace />} />
        <Route path="/admin" element={<Navigate to="/admin/overview" replace />} />
        <Route path="/admin/overview" element={<Overview />} />
        <Route path="/admin/governance" element={<GovernanceOverview />} />
        <Route path="/admin/operations" element={<OperationsSettings />} />
        <Route path="/admin/developer/ask" element={<AdminAccess><ContextConsole /></AdminAccess>} />
        <Route path="/admin/developer/capabilities" element={<><div>{error && <p role="alert" className="workspace-error">{error}</p>}</div><CapabilityStudio capabilities={capabilities} sources={sources} mappings={mappings} lineage={lineage} validation={validation} onOpenBindings={() => navigate("/admin/semantic-model/bindings")} /></>} />
        <Route path="/admin/data-catalog" element={<FramedPage><MetadataExplorer /></FramedPage>} />
        <Route path="/admin/data-catalog/assets/:fqn" element={<MetadataAssetPage />} />
        <Route path="/admin/changes/review" element={<AdminAccess><FramedPage><SuggestionReview /></FramedPage></AdminAccess>} />
        <Route path="/admin/semantic-model/bindings" element={<AdminAccess><FramedPage><BindingManager /></FramedPage></AdminAccess>} />
        <Route path="/admin/semantic-model/ontology" element={<AdminAccess><FramedPage><OntologyAuthoring /></FramedPage></AdminAccess>} />
        <Route path="/admin/settings" element={<Navigate to="/admin/operations" replace />} />
        <Route path="/admin/ask" element={<Navigate to="/admin/developer/ask" replace />} />
        <Route path="/admin/capabilities" element={<Navigate to="/admin/developer/capabilities" replace />} />
        <Route path="/admin/review-queue" element={<Navigate to="/admin/changes/review" replace />} />
        <Route path="/admin/semantic-bindings" element={<Navigate to="/admin/semantic-model/bindings" replace />} />
        <Route path="/admin/business-concepts" element={<Navigate to="/admin/semantic-model/ontology" replace />} />
        <Route path="*" element={<Navigate to="/admin/overview" replace />} />
      </Routes>
    </main>
  </div>;
}
