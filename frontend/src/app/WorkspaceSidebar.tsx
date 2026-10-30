import { useEffect, useState } from "react";
import {
  AppWindow,
  Braces,
  ChevronDown,
  ChevronRight,
  PanelLeftClose,
  PanelLeftOpen,
} from "lucide-react";
import { Link, NavLink, useLocation } from "react-router-dom";
import { useDeploymentModules } from "../features/access/DeploymentAvailability";
import { navigationItems, type NavigationItem } from "./navigation";

export function WorkspaceSidebar({
  expanded,
  modelOperationsEnabled,
  onToggle,
  onNavigate,
}: {
  expanded: boolean;
  modelOperationsEnabled: boolean;
  onToggle: () => void;
  onNavigate?: () => void;
}) {
  const location = useLocation();
  const modules = useDeploymentModules();
  const [groups, setGroups] = useState<Record<string, boolean>>({});
  const activeGroup = navigationItems.find((item) =>
    location.pathname.startsWith(item.path),
  )?.group;
  useEffect(() => {
    if (activeGroup)
      setGroups((previous) => ({ ...previous, [activeGroup]: true }));
  }, [activeGroup]);
  const items = navigationItems.filter(
    (item) =>
      (!item.module || modules[item.module]) &&
      (!item.modelOperations || modelOperationsEnabled),
  );
  const main = items.filter((item) => item.placement !== "footer");
  const footer = items.filter((item) => item.placement === "footer");
  const renderLink = (item: NavigationItem) => {
    const Icon = item.icon;
    return (
      <NavLink
        key={item.path}
        to={item.path}
        onClick={onNavigate}
        aria-label={item.label}
        title={
          expanded ? item.description : `${item.label} · ${item.description}`
        }
        className={({ isActive }) =>
          `workspace-nav-link ${isActive ? "active" : ""}`
        }
      >
        <Icon size={17} aria-hidden="true" />
        {expanded && <span>{item.label}</span>}
      </NavLink>
    );
  };
  return (
    <aside
      className={`workspace-sidebar ${expanded ? "expanded" : "collapsed"}`}
      aria-label="플랫폼 탐색"
    >
      <Link
        to="/admin/overview"
        className="workspace-brand"
        aria-label="Teoria 개요"
        onClick={onNavigate}
      >
        <div>
          <Braces size={18} />
        </div>
        {expanded && (
          <span>
            <strong>Teoria</strong>
            <small>메타데이터·온톨로지</small>
          </span>
        )}
      </Link>
      <nav className="workspace-primary-nav" aria-label="주요 메뉴">
        {main
          .filter(
            (item, index) =>
              !["의미 모델", "모델 운영", "앱"].includes(item.group) ||
              main.findIndex((other) => other.group === item.group) === index,
          )
          .map((item) => {
            if (!["의미 모델", "모델 운영", "앱"].includes(item.group))
              return renderLink(item);
            const children = main.filter((other) => other.group === item.group);
            if (!expanded)
              return <div key={item.group}>{children.map(renderLink)}</div>;
            const Icon = item.group === "앱" ? AppWindow : item.icon;
            const open = Boolean(groups[item.group]);
            return (
              <div key={item.group} className="workspace-nav-section">
                <button
                  className="workspace-nav-parent"
                  aria-expanded={open}
                  onClick={() =>
                    setGroups((previous) => ({
                      ...previous,
                      [item.group]: !open,
                    }))
                  }
                >
                  <Icon size={17} />
                  <span>{item.group}</span>
                  {open ? (
                    <ChevronDown size={13} />
                  ) : (
                    <ChevronRight size={13} />
                  )}
                </button>
                {open && (
                  <div className="workspace-nav-children">
                    {children.map(renderLink)}
                  </div>
                )}
              </div>
            );
          })}
      </nav>
      <div className="workspace-sidebar-footer">
        <nav aria-label="플랫폼 관리">
          {expanded && <p className="workspace-nav-group">플랫폼 관리</p>}
          {footer.map(renderLink)}
        </nav>
        <button
          className="workspace-nav-toggle"
          aria-label={expanded ? "사이드바 접기" : "사이드바 펼치기"}
          aria-expanded={expanded}
          onClick={onToggle}
        >
          {expanded ? (
            <PanelLeftClose size={17} />
          ) : (
            <PanelLeftOpen size={17} />
          )}{" "}
          {expanded && <span>사이드바 접기</span>}
        </button>
      </div>
    </aside>
  );
}
