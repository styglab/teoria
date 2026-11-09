import { useEffect, useState } from "react";
import {
  Braces,
  ChevronDown,
  ChevronRight,
  PanelLeftClose,
  PanelLeftOpen,
} from "lucide-react";
import { Link, NavLink, useLocation } from "react-router-dom";
import { useDeploymentModules } from "../features/access/DeploymentAvailability";
import { navigationGroups, navigationItems, navigationAvailable, type NavigationItem } from "./navigation";

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
      navigationAvailable(item, modules) &&
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
            <small>의미·모델·실행</small>
          </span>
        )}
      </Link>
      <nav className="workspace-primary-nav" aria-label="주요 메뉴">
        {main.filter((item) => !item.group).map(renderLink)}
        {navigationGroups.map((group) => {
          const children = main.filter((item) => item.group === group.id);
          if (!children.length) return null;
          if (!expanded)
            return <div key={group.id} role="group" aria-label={group.label}>{children.map(renderLink)}</div>;
          const Icon = group.icon;
          const open = Boolean(groups[group.id]);
          return (
            <div key={group.id} className="workspace-nav-section">
              <button
                className="workspace-nav-parent"
                aria-expanded={open}
                aria-controls={`workspace-nav-${group.id}`}
                title={group.description}
                onClick={() => setGroups((previous) => ({ ...previous, [group.id]: !open }))}
              >
                <Icon size={17} aria-hidden="true" />
                <span>{group.label}</span>
                {open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
              </button>
              {open && (
                <div id={`workspace-nav-${group.id}`} className="workspace-nav-children">
                  {children.map(renderLink)}
                </div>
              )}
            </div>
          );
        })}
      </nav>
      <div className="workspace-sidebar-footer">
        <nav aria-label="공통 운영">
          {expanded && <p className="workspace-nav-group">공통 운영</p>}
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
