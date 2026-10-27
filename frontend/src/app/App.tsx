import { useEffect, useState } from "react";
import { CheckCircle2, Menu } from "lucide-react";
import {
  Navigate,
  Route,
  Routes,
  useLocation,
  useNavigate,
} from "react-router-dom";
import { capabilityApi, type CapabilitySummary } from "../api/capability";
import {
  registryApi,
  type LineageLink,
  type MappingSummary,
  type RegistryRelease,
  type SourceSummary,
  type ValidationReport,
} from "../api/registry";
import {
  ModelOperationsAvailability,
  useModelOperationsAvailability,
} from "../features/model_operations/ModelOperationsAvailability";
import { WorkspaceSidebar } from "./WorkspaceSidebar";
import { currentNavigation } from "./navigation";
import { ModelOperations } from "../features/model_operations/ModelOperations";
import { BindingManager } from "../features/binding/BindingManager";
import { CapabilityStudio } from "../features/capability/CapabilityStudio";
import { SuggestionReview } from "../features/intelligence/SuggestionReview";
import { MetadataExplorer } from "../features/metadata/MetadataExplorer";
import { MetadataAssetPage } from "../features/metadata/MetadataAssetPage";
import { Overview, OperationsSettings } from "../features/overview/Overview";
import { GovernanceOverview } from "../features/governance/GovernanceOverview";
import {
  AdminAccess,
  AdminAccessProvider,
} from "../features/access/AdminAccess";
import { WorkspaceFrame } from "../components/workspace/WorkspaceLayout";
import { OntologyAuthoring } from "../features/ontology/OntologyAuthoring";

export function App() {
  return (
    <AdminAccessProvider>
      <ModelOperationsAvailability>
        <AdminWorkspace />
      </ModelOperationsAvailability>
    </AdminAccessProvider>
  );
}

function AdminWorkspace() {
  const { enabled: modelOperationsEnabled } = useModelOperationsAvailability();
  const [compact, setCompact] = useState(() => window.innerWidth < 1000);
  const [sidebarOpen, setSidebarOpen] = useState(
    () => window.innerWidth >= 1000,
  );
  const location = useLocation();
  const navigate = useNavigate();
  useEffect(() => {
    const resize = () => {
      const next = window.innerWidth < 1000;
      if (next !== compact) {
        setCompact(next);
        setSidebarOpen(!next);
      }
    };
    window.addEventListener("resize", resize);
    return () => window.removeEventListener("resize", resize);
  }, [compact]);
  useEffect(() => {
    if (compact) setSidebarOpen(false);
  }, [location.pathname, compact]);
  const [capabilities, setCapabilities] = useState<CapabilitySummary[]>([]);
  const [sources, setSources] = useState<SourceSummary[]>([]);
  const [mappings, setMappings] = useState<MappingSummary[]>([]);
  const [lineage, setLineage] = useState<LineageLink[]>([]);
  const [validation, setValidation] = useState<ValidationReport | null>(null);
  const [release, setRelease] = useState<RegistryRelease | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const requests = [
      {
        label: "기능",
        load: () =>
          capabilityApi
            .capabilities()
            .then((value) => setCapabilities(value.capabilities)),
      },
      {
        label: "소스",
        load: () =>
          registryApi.sources().then((value) => setSources(value.sources)),
      },
      {
        label: "매핑",
        load: () =>
          registryApi.mappings().then((value) => setMappings(value.mappings)),
      },
      {
        label: "계보",
        load: () =>
          registryApi.lineage().then((value) => setLineage(value.links)),
      },
      {
        label: "검증",
        load: () => registryApi.validation().then(setValidation),
      },
      {
        label: "게시 버전",
        load: () => registryApi.registryRelease().then(setRelease),
      },
    ];
    Promise.allSettled(requests.map((request) => request.load())).then(
      (results) => {
        const unavailable = results.flatMap((result, index) =>
          result.status === "rejected" ? [requests[index].label] : [],
        );
        if (unavailable.length)
          setError(
            `${unavailable.join(", ")} 정보를 조회하지 못했습니다. 다른 화면은 계속 사용할 수 있습니다.`,
          );
      },
    );
  }, []);

  const current = currentNavigation(location.pathname);
  const wideSidebar = sidebarOpen && !compact;
  return (
    <div
      className={`min-h-screen bg-background text-foreground ${wideSidebar ? "pl-64" : "pl-16"}`}
    >
      {compact && sidebarOpen && (
        <button
          className="workspace-nav-scrim"
          aria-label="메뉴 닫기"
          onClick={() => setSidebarOpen(false)}
        />
      )}
      <WorkspaceSidebar
        expanded={sidebarOpen}
        modelOperationsEnabled={modelOperationsEnabled}
        onNavigate={() => {
          if (compact) setSidebarOpen(false);
        }}
        onToggle={() => setSidebarOpen((value) => !value)}
      />
      <header
        className={`admin-topbar fixed inset-x-0 top-0 z-20 flex h-16 items-center justify-between border-b border-border bg-background/95 px-6 backdrop-blur ${wideSidebar ? "left-64" : "left-16"}`}
      >
        <div className="workspace-breadcrumb">
          <button
            className="workspace-mobile-menu"
            aria-label="탐색 메뉴 열기"
            aria-expanded={sidebarOpen}
            onClick={() => setSidebarOpen((value) => !value)}
          >
            <Menu size={17} />
          </button>
          <div>
            <p>{current.group || "Teoria"}</p>
            <h1>{current.label}</h1>
          </div>
        </div>
        {current.path === "/admin/developer/capabilities" && (
          <div className="workspace-contract-status flex items-center gap-2 pr-48">
            <span className="hidden text-[11px] text-muted-foreground sm:inline">
              Runtime 계약 {release?.version ?? "draft"}
            </span>
            <span
              className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[10px] ${validation?.status === "valid" ? "border-border text-foreground" : "border-destructive/30 text-destructive"}`}
            >
              <CheckCircle2 className="size-3" />
              {validation
                ? validation.status === "valid"
                  ? "계약 검증됨"
                  : `${validation.diagnostic_count} issues`
                : "계약 확인 중"}
            </span>
          </div>
        )}
      </header>

      <main className="workspace-main h-screen pt-16">
        <Routes>
          <Route path="/" element={<Navigate to="/admin/overview" replace />} />
          <Route
            path="/admin"
            element={<Navigate to="/admin/overview" replace />}
          />
          <Route
            path="/admin/overview"
            element={
              <WorkspaceFrame>
                <Overview />
              </WorkspaceFrame>
            }
          />
          <Route
            path="/admin/governance"
            element={
              <WorkspaceFrame>
                <GovernanceOverview />
              </WorkspaceFrame>
            }
          />
          <Route
            path="/admin/workflows"
            element={
              <AdminAccess>
                <WorkspaceFrame>
                  <ModelOperations view="pipelines" />
                </WorkspaceFrame>
              </AdminAccess>
            }
          />
          <Route
            path="/admin/models"
            element={
              <AdminAccess>
                <WorkspaceFrame>
                  <ModelOperations view="models" />
                </WorkspaceFrame>
              </AdminAccess>
            }
          />
          <Route
            path="/admin/serving"
            element={
              <AdminAccess>
                <WorkspaceFrame>
                  <ModelOperations view="serving" />
                </WorkspaceFrame>
              </AdminAccess>
            }
          />
          <Route
            path="/admin/model-operations"
            element={<LegacyModelRoute />}
          />
          <Route
            path="/admin/operations"
            element={
              <WorkspaceFrame>
                <OperationsSettings />
              </WorkspaceFrame>
            }
          />
          <Route
            path="/admin/developer/capabilities"
            element={
              <WorkspaceFrame>
                <div>
                  {error && (
                    <p role="alert" className="workspace-error">
                      {error}
                    </p>
                  )}
                </div>
                <CapabilityStudio
                  capabilities={capabilities}
                  sources={sources}
                  mappings={mappings}
                  lineage={lineage}
                  validation={validation}
                  onOpenBindings={() =>
                    navigate("/admin/semantic-model/bindings")
                  }
                />
              </WorkspaceFrame>
            }
          />
          <Route
            path="/admin/data-catalog"
            element={
              <WorkspaceFrame>
                <MetadataExplorer />
              </WorkspaceFrame>
            }
          />
          <Route
            path="/admin/data-catalog/assets/:fqn"
            element={
              <WorkspaceFrame>
                <MetadataAssetPage />
              </WorkspaceFrame>
            }
          />
          <Route
            path="/admin/changes/review"
            element={
              <AdminAccess>
                <WorkspaceFrame>
                  <SuggestionReview />
                </WorkspaceFrame>
              </AdminAccess>
            }
          />
          <Route
            path="/admin/semantic-model/bindings"
            element={
              <AdminAccess>
                <WorkspaceFrame>
                  <BindingManager />
                </WorkspaceFrame>
              </AdminAccess>
            }
          />
          <Route
            path="/admin/semantic-model/ontology"
            element={
              <AdminAccess>
                <WorkspaceFrame>
                  <OntologyAuthoring />
                </WorkspaceFrame>
              </AdminAccess>
            }
          />
          <Route
            path="/admin/settings"
            element={<Navigate to="/admin/operations" replace />}
          />
          <Route
            path="/admin/ask"
            element={<Navigate to="/admin/developer/capabilities" replace />}
          />
          <Route
            path="/admin/capabilities"
            element={<Navigate to="/admin/developer/capabilities" replace />}
          />
          <Route
            path="/admin/review-queue"
            element={<Navigate to="/admin/changes/review" replace />}
          />
          <Route
            path="/admin/semantic-bindings"
            element={<Navigate to="/admin/semantic-model/bindings" replace />}
          />
          <Route
            path="/admin/business-concepts"
            element={<Navigate to="/admin/semantic-model/ontology" replace />}
          />
          <Route path="*" element={<Navigate to="/admin/overview" replace />} />
        </Routes>
      </main>
    </div>
  );
}

function LegacyModelRoute() {
  const location = useLocation();
  return (
    <Navigate
      to={{
        pathname: "/admin/models",
        search: location.search,
        hash: location.hash,
      }}
      replace
    />
  );
}
