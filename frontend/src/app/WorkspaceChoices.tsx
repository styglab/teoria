import { Link } from "react-router-dom";
import { useDeploymentModules } from "../features/access/DeploymentAvailability";
import { navigationGroups, navigationItems, navigationAvailable } from "./navigation";

export function WorkspaceChoices({ modelOperationsEnabled }: { modelOperationsEnabled: boolean }) {
  const modules = useDeploymentModules();
  const workspaces = navigationGroups.filter((group) =>
    group.id === "ontology_operations" ? modules.semantic :
    group.id === "goods_domain" ? modules.semantic || modules.formatid :
    group.id === "model_operations" && modules.mlops && modelOperationsEnabled,
  );
  if (!workspaces.length) return null;
  return (
    <section className="workspace-choices" aria-label="작업 공간 선택">
      {workspaces.map((group) => {
        const Icon = group.icon;
        return (
          <article key={group.id} className="workspace-choice">
            <h2><Icon size={18} aria-hidden="true" />{group.label}</h2>
            <p>{group.description}</p>
            <nav aria-label={`${group.label} 시작`}>
              {navigationItems.filter((item) => item.group === group.id && navigationAvailable(item, modules)).map((item) => (
                <Link key={item.path} to={item.path}>{item.label}</Link>
              ))}
            </nav>
          </article>
        );
      })}
    </section>
  );
}
