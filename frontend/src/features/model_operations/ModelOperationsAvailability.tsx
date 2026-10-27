import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { modelOperationsApi } from "../../api/model_operations";
import { useAdminAccess } from "../access/AdminAccess";

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
  const [state, setState] = useState({
    enabled: false,
    checking: false,
    error: null as string | null,
  });
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    let active = true;
    setState({ enabled: false, checking: !!principal, error: null });
    if (principal)
      modelOperationsApi
        .status()
        .then((value) => {
          if (active)
            setState({ enabled: value.enabled, checking: false, error: null });
        })
        .catch((reason) => {
          if (active)
            setState({
              enabled: false,
              checking: false,
              error: (reason as Error).message,
            });
        });
    return () => {
      active = false;
    };
  }, [principal?.actor, revision]);
  return (
    <AvailabilityContext.Provider
      value={{ ...state, refresh: () => setRevision((value) => value + 1) }}
    >
      {children}
    </AvailabilityContext.Provider>
  );
}
