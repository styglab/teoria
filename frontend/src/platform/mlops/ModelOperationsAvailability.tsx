import { createContext, useContext, type ReactNode } from "react";
import { useServerQuery } from "../../api/server_queries";
import { useAdminAccess } from "../access_control/AdminAccess";
import { modelOperationsApi } from "./api";

const AvailabilityContext = createContext({
  enabled: false,
  checking: false,
  error: null as string | null,
  refresh: () => {},
});
export const useModelOperationsAvailability = () =>
  useContext(AvailabilityContext);

export function ModelOperationsAvailability({
  children,
}: {
  children: ReactNode;
}) {
  const { principal } = useAdminAccess();

  const result = useServerQuery(
    ["mlops", "status"],
    (signal) => modelOperationsApi.status(signal),
    { enabled: !!principal },
  );
  const state = {
    enabled: !!principal && !!result.data?.enabled,
    checking: !!principal && result.loading,
    error: result.error || null,
  };
  return (
    <AvailabilityContext.Provider value={{ ...state, refresh: result.retry }}>
      {children}
    </AvailabilityContext.Provider>
  );
}
