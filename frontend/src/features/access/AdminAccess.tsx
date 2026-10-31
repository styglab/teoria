import {
  createContext,
  useContext,
  useEffect,
  useState,
  useRef,
  type ReactNode,
} from "react";
import { AdminLoginDialog } from "./AdminLoginDialog";
import { AdminApiError, SESSION_EXPIRED_EVENT } from "../../api/http_client";
import { authApi } from "../../api/auth";

type Principal = { actor: string; roles: string[] };
const AccessContext = createContext<{
  principal: Principal | null;
  requestLogin: () => void;
}>({ principal: null, requestLogin: () => {} });
export const useAdminAccess = () => useContext(AccessContext);
export function AdminAccessProvider({ children }: { children: ReactNode }) {
  const [principal, setPrincipal] = useState<Principal | null>(null);
  const [open, setOpen] = useState(false);
  const generation = useRef(0);
  useEffect(() => {
    let active = true;
    const current = generation.current;
    const expired = () => {
      generation.current += 1;
      setPrincipal(null);
    };
    window.addEventListener(SESSION_EXPIRED_EVENT, expired);
    if (window.sessionStorage.getItem("teoria-admin-token"))
      authApi
        .session()
        .then((value) => {
          if (active && current === generation.current) setPrincipal(value);
        })
        .catch((reason) => {
          if (
            active &&
            current === generation.current &&
            reason instanceof AdminApiError &&
            [401, 403].includes(reason.status)
          ) {
            window.sessionStorage.removeItem("teoria-admin-token");
            setPrincipal(null);
          }
        });
    return () => {
      active = false;
      window.removeEventListener(SESSION_EXPIRED_EVENT, expired);
    };
  }, []);

  return (
    <AccessContext.Provider
      value={{ principal, requestLogin: () => setOpen(true) }}
    >
      {children}
      <div className="admin-session-control">
        {principal ? (
          <>
            <span>관리자 · {principal.actor}</span>
            <button
              onClick={() => {
                generation.current += 1;
                window.sessionStorage.removeItem("teoria-admin-token");
                setPrincipal(null);
              }}
            >
              로그아웃
            </button>
          </>
        ) : (
          <>
            <span>조회 모드</span>
            <button onClick={() => setOpen(true)}>관리자 연결</button>
          </>
        )}
      </div>
      {open && (
        <AdminLoginDialog
          onClose={() => setOpen(false)}
          onAuthenticated={(value) => {
            generation.current += 1;
            setPrincipal(value);
            setOpen(false);
          }}
        />
      )}
    </AccessContext.Provider>
  );
}
export function AdminAccess({ children }: { children: ReactNode }) {
  const { principal, requestLogin } = useAdminAccess();
  if (!principal)
    return (
      <div className="workspace-empty">
        <h2>관리자 연결이 필요합니다</h2>
        <p>검토·승인·업무 의미 관리에는 인증된 관리자가 필요합니다.</p>
        <button onClick={requestLogin}>관리자 연결</button>
      </div>
    );
  return <>{children}</>;
}
