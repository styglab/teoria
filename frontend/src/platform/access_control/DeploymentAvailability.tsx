import { createContext, useContext, type ReactNode } from "react";
import { getJson } from "../../api/http_client";
import { useServerQuery } from "../../api/server_queries";

export type DeploymentModules = {
  semantic: boolean; // Compatibility with servers predating feature selection.
  metadata?: boolean;
  ontology?: boolean;
  goods?: boolean;
  formatid: boolean;
  mlops: boolean;
};
export const deploymentApi = {
  status: (signal?: AbortSignal) => getJson<DeploymentModules>("/deployment", signal),
};
// Standalone component tests and legacy embedding retain their existing defaults.
const DeploymentContext = createContext<DeploymentModules>({
  semantic: true,
  formatid: true,
  mlops: true,
});
export const useDeploymentModules = () => {
  const modules = useContext(DeploymentContext);
  return {
    ...modules,
    metadata: modules.metadata ?? modules.semantic,
    ontology: modules.ontology ?? modules.semantic,
    goods: modules.goods ?? (modules.semantic || modules.formatid),
  };
};

export function DeploymentAvailability({ children }: { children: ReactNode }) {
  const result = useServerQuery(["deployment"], (signal) => deploymentApi.status(signal));
  const modules = result.data;
  const error = result.error;
  if (error)
    return (
      <div className="workspace-empty" role="alert">
        사용 가능한 서비스를 확인하지 못했습니다.{" "}
        <button onClick={result.retry}>다시 조회</button>
      </div>
    );
  if (!modules)
    return (
      <div className="workspace-empty">서비스 구성을 확인하고 있습니다…</div>
    );
  return (
    <DeploymentContext.Provider value={modules}>
      {children}
    </DeploymentContext.Provider>
  );
}
