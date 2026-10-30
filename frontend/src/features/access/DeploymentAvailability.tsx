import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { getJson } from "../../api/http_client";

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
  const [modules, setModules] = useState<DeploymentModules | null>(null);
  const [error, setError] = useState(false);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    let active = true;
    setError(false);
    deploymentApi
      .status()
      .then((value) => {
        if (active) setModules(value);
      })
      .catch(() => {
        if (active) setError(true);
      });
    return () => {
      active = false;
    };
  }, [revision]);
  if (error)
    return (
      <div className="workspace-empty" role="alert">
        사용 가능한 서비스를 확인하지 못했습니다.{" "}
        <button onClick={() => setRevision((v) => v + 1)}>다시 조회</button>
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
