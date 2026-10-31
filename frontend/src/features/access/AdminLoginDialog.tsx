import { useEffect, useRef, useState, type FormEvent } from "react";
import { authApi } from "../../api/auth";
import { AdminApiError } from "../../api/http_client";

type Principal = Awaited<ReturnType<typeof authApi.session>>;

export function AdminLoginDialog({
  onClose,
  onAuthenticated,
}: {
  onClose: () => void;
  onAuthenticated: (principal: Principal) => void;
}) {
  const dialog = useRef<HTMLElement>(null);
  const busyRef = useRef(false);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    dialog.current?.querySelector<HTMLInputElement>("input")?.focus();
    const keydown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busyRef.current) {
        event.preventDefault();
        closeRef.current();
      }
      if (event.key !== "Tab") return;
      const controls = Array.from(
        dialog.current?.querySelectorAll<HTMLElement>(
          'button:not(:disabled), input:not(:disabled), [tabindex="0"]',
        ) || [],
      );
      const first = controls[0],
        last = controls[controls.length - 1];
      if (!first) {
        event.preventDefault();
        dialog.current?.focus();
        return;
      }
      if (
        event.shiftKey &&
        (document.activeElement === first ||
          !controls.includes(document.activeElement as HTMLElement))
      ) {
        event.preventDefault();
        last.focus();
      } else if (
        !event.shiftKey &&
        (document.activeElement === last ||
          !controls.includes(document.activeElement as HTMLElement))
      ) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", keydown);
    return () => {
      document.removeEventListener("keydown", keydown);
      previous?.focus();
    };
  }, []);
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [visible, setVisible] = useState(false);
  const connect = async (event: FormEvent) => {
    event.preventDefault();
    if (busyRef.current) return;
    let value = token
      .trim()
      .replace(/^(?:export\s+)?TEORIA_ADMIN_API_TOKEN\s*=\s*/, "");
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    )
      value = value.slice(1, -1);
    value = value.replace(/^Bearer\s+/i, "").trim();
    if (!value) return;
    busyRef.current = true;
    setBusy(true);
    setError(null);
    window.sessionStorage.setItem("teoria-admin-token", value);
    try {
      const principal = await authApi.session();
      if (window.sessionStorage.getItem("teoria-admin-token") !== value)
        throw new AdminApiError("인증이 만료됐습니다", 401);
      onAuthenticated(principal);
    } catch (reason) {
      if (window.sessionStorage.getItem("teoria-admin-token") === value)
        window.sessionStorage.removeItem("teoria-admin-token");
      setError(
        reason instanceof AdminApiError && reason.status === 401
          ? "운영 서버가 토큰을 거절했습니다. Teoria 관리자 토큰인지 확인하세요."
          : reason instanceof AdminApiError && reason.status === 403
            ? "이 계정에는 관리자 연결 권한이 없습니다."
            : "인증 서버에 연결하지 못했습니다. 다시 시도하세요.",
      );
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  };
  return (
    <div className="validation-backdrop">
      <section
        ref={dialog}
        tabIndex={-1}
        className="admin-login-dialog"
        role="dialog"
        aria-modal="true"
        aria-label="관리자 연결"
      >
        <h2>관리자 연결</h2>
        <p>
          변경 작업에는 관리자 인증이 필요합니다. 조회 가능 범위는 서버 설정에
          따라 달라집니다.
        </p>
        <form onSubmit={connect}>
          <label>
            관리자 토큰
            <input
              type={visible ? "text" : "password"}
              autoComplete="off"
              disabled={busy}
              value={token}
              onChange={(event) => setToken(event.target.value)}
            />
          </label>
          <div className="page-actions">
            <button
              type="button"
              disabled={busy}
              onClick={() => setVisible((value) => !value)}
            >
              {visible ? "토큰 숨기기" : "토큰 보기"}
            </button>
            <button type="button" disabled={busy} onClick={onClose}>
              취소
            </button>
            <button type="submit" disabled={busy || !token.trim()}>
              {busy ? "연결 중…" : "연결"}
            </button>
          </div>
          {error && <p role="alert">{error}</p>}
        </form>
      </section>
    </div>
  );
}
