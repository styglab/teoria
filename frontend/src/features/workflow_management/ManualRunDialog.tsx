import { useEffect, useRef, useState } from "react";
import { workflowsApi, type Pipeline } from "../../api/workflows";

function requestKey() {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 15) | 64;
  bytes[8] = (bytes[8] & 63) | 128;
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join(
    "",
  );
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}
export function ManualRunDialog({
  pipeline,
  onClose,
  onStarted,
}: {
  pipeline: Pipeline;
  onClose: () => void;
  onStarted: (id: string) => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [deploy, setDeploy] = useState(false);
  const [manifest, setManifest] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const key = useRef(requestKey());
  useEffect(() => {
    if (dialog.current?.showModal) dialog.current.showModal();
    else dialog.current?.setAttribute("open", "");
  }, []);
  return (
    <dialog
      ref={dialog}
      className="workflow-dialog"
      aria-labelledby="manual-run-title"
      onCancel={(event) => {
        event.preventDefault();
        if (!busy) onClose();
      }}
    >
      <form
        onSubmit={async (event) => {
          event.preventDefault();
          if (busy) return;
          setError("");
          let parsed: Record<string, unknown> | undefined;
          if (pipeline.input_kind === "manifest") {
            try {
              parsed = JSON.parse(manifest);
              if (
                !parsed ||
                Array.isArray(parsed) ||
                typeof parsed !== "object"
              )
                throw Error();
            } catch {
              setError("실행 입력은 JSON 객체로 입력하세요.");
              return;
            }
          }
          setBusy(true);
          try {
            const result = await workflowsApi.run(pipeline.id, key.current, {
              ...(pipeline.input_kind === "model" ? { deploy } : {}),
              ...(parsed ? { manifest: parsed } : {}),
            });
            onStarted(result.flow_run_id);
          } catch (reason) {
            setError((reason as Error).message);
          } finally {
            setBusy(false);
          }
        }}
      >
        <h2 id="manual-run-title">수동 실행</h2>
        <p>{pipeline.name}</p>
        {pipeline.input_kind === "manifest" ? (
          <label>
            실행 입력(JSON)
            <textarea
              autoFocus
              required
              rows={12}
              value={manifest}
              onChange={(e) => setManifest(e.target.value)}
              placeholder={
                pipeline.id === "specification-standard-workflow"
                  ? '{"workflow_id":"...","extraction":{...},"base_profile_revision_id":"..."}'
                  : '{"run_id":"...","mode":"...","documents":[...],"artifact_root":"file:///app/specification_artifacts"}'
              }
            />
            <small>
              규격서·저장 위치·고정 표준 등 해당 파이프라인의 실행 계약을
              입력합니다. 인증정보는 입력하지 마세요.
            </small>
          </label>
        ) : pipeline.input_kind === "model" ? (
          <label className="workflow-checkbox">
            <input
              type="checkbox"
              checked={deploy}
              onChange={(e) => setDeploy(e.target.checked)}
            />
            평가 통과 후 자동 배포
            <small>선택하지 않으면 학습·평가·모델 등록까지만 실행합니다.</small>
          </label>
        ) : (
          <p>
            등록된 운영 설정으로 한 번 실행합니다. 기존 스케줄은 유지됩니다.
          </p>
        )}
        {error && (
          <p role="alert" className="workspace-error">
            {error}
          </p>
        )}
        <footer>
          <button type="button" disabled={busy} onClick={onClose}>
            취소
          </button>
          <button type="submit" disabled={busy} className="page-primary-link">
            {busy ? "요청 중…" : "실행 요청"}
          </button>
        </footer>
      </form>
    </dialog>
  );
}
