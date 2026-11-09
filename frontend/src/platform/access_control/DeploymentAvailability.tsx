import { createContext, useContext, type ReactNode } from "react";
import { getJson } from "../../api/http_client";
import { useServerQuery } from "../../api/server_queries";

export type DeploymentModules = {
  semantic: boolean;
  formatid: boolean;
  mlops: boolean;
};
export const deploymentApi = {
  status: () => getJson<DeploymentModules>("/deployment"),
};
// Standalone component tests and legacy embedding retain their existing defaults.
const DeploymentContext = createContext<DeploymentModules>({
  semantic: true,
  formatid: true,
  mlops: true,
});
export const useDeploymentModules = () => useContext(DeploymentContext);

export function DeploymentAvailability({ children }: { children: ReactNode }) {
  const result = useServerQuery(["deployment"], () => deploymentApi.status());
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
