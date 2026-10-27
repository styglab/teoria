import { Braces, PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { Link, NavLink } from "react-router-dom";
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
  const items = navigationItems.filter(
    (item) => !item.modelOperations || modelOperationsEnabled,
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
        title={expanded ? item.description : `${item.label} · ${item.description}`}
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
            <small>
              {modelOperationsEnabled
                ? "데이터·의미·모델 운영"
                : "메타데이터·온톨로지 관리"}
            </small>
          </span>
        )}
      </Link>
      <nav className="workspace-primary-nav" aria-label="주요 메뉴">
        {main.map((item, index) => (
          <div key={item.path}>
            {expanded &&
              item.group &&
              main[index - 1]?.group !== item.group && (
                <p className="workspace-nav-group">{item.group}</p>
              )}
            {renderLink(item)}
          </div>
        ))}
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
