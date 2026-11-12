import { Link } from "react-router-dom";
import { useDeploymentModules } from "../platform/access_control/DeploymentAvailability";
import {
  navigationAvailable,
  navigationGroups,
  navigationItems,
} from "./navigation";

export function WorkspaceChoices({
  modelOperationsEnabled,
}: {
  modelOperationsEnabled: boolean;
}) {
  const modules = useDeploymentModules();
  const workspaces = navigationGroups.filter((group) => {
    switch (group.id) {
      case "data": return modules.metadata;
      case "ontology": return modules.ontology;
      case "goods_domain": return modules.goods;
      case "mlops": return modules.mlops && modelOperationsEnabled;
      default: return false;
    }
  });
  if (!workspaces.length) return null;
  return (
    <section className="workspace-choices" aria-label="작업 공간 선택">
      {workspaces.map((group) => {
        const Icon = group.icon;
        return (
          <article key={group.id} className="workspace-choice">
            <h2>
              <Icon size={18} aria-hidden="true" />
              {group.label}
            </h2>
            <p>{group.description}</p>
            <nav aria-label={`${group.label} 시작`}>
              {navigationItems
                .filter(
                  (item) =>
                    item.group === group.id &&
                    navigationAvailable(item, modules),
                )
                .map((item) => (
                  <Link key={item.path} to={item.path}>
                    {item.label}
                  </Link>
                ))}
            </nav>
          </article>
        );
      })}
    </section>
  );
}
