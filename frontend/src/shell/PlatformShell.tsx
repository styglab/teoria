import { Menu } from "lucide-react";
import { Suspense, useEffect, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { RouteBoundary } from "../components/workspace/RouteBoundary";
import { AdminAccessProvider } from "../platform/access_control/AdminAccess";
import {
  DeploymentAvailability,
  useDeploymentModules,
} from "../platform/access_control/DeploymentAvailability";
import {
  ModelOperationsAvailability,
  useModelOperationsAvailability,
} from "../platform/mlops/ModelOperationsAvailability";
import { WorkspaceSidebar } from "./WorkspaceSidebar";
import {
  currentNavigation,
  navigationAvailable,
  navigationGroups,
  navigationPaths,
} from "./navigation";
import { WorkspaceRoutes } from "./routes";

export function PlatformShell() {
  return (
    <DeploymentAvailability>
      <AdminAccessProvider>
        <ModelOperationsAvailability>
          <AdminWorkspace />
        </ModelOperationsAvailability>
      </AdminAccessProvider>
    </DeploymentAvailability>
  );
}

function AdminWorkspace() {
  const modules = useDeploymentModules();
  const { enabled: modelOperationsEnabled } = useModelOperationsAvailability();
  const [compact, setCompact] = useState(() => window.innerWidth < 1000);
  const [sidebarOpen, setSidebarOpen] = useState(
    () => window.innerWidth >= 1000,
  );
  const location = useLocation();
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
  const current = currentNavigation(location.pathname);
  const currentGroup = navigationGroups.find(
    (group) => group.id === current.group,
  );
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
          <nav className="workspace-location" aria-label="현재 위치">
            <Link to={navigationPaths.overview}>홈</Link>
            {current.path !== navigationPaths.overview && (
              <>
                <span aria-hidden="true">/</span>
                {currentGroup && (
                  <>
                    <span>{currentGroup.label}</span>
                    <span aria-hidden="true">/</span>
                  </>
                )}
                <span aria-current="page">{current.label}</span>
              </>
            )}
          </nav>
        </div>
      </header>

      <main className="workspace-main h-screen pt-16">
        {!navigationAvailable(current, modules) ? (
          <div className="workspace-empty">
            <h2>{current.label}</h2>
            <p>현재 실행 구성에서 사용하지 않는 기능입니다.</p>
          </div>
        ) : (
          <RouteBoundary key={location.pathname}>
            <Suspense
              fallback={
                <div className="page-state" role="status">
                  화면을 불러오는 중입니다.
                </div>
              }
            >
              <WorkspaceRoutes
                modelOperationsEnabled={modelOperationsEnabled}
              />
            </Suspense>
          </RouteBoundary>
        )}
      </main>
    </div>
  );
}
