import { useEffect, useRef, useState } from "react";
import { ExternalLink, RefreshCw, X } from "lucide-react";
import { workflowsApi, type RunDetail } from "../../api/workflows";
import { PageState } from "../../components/workspace/WorkspaceLayout";
import {
  dateLabel,
  runDurationLabel,
  stateLabels,
} from "../model_operations/presentation";

export function RunDetailPanel({
  runId,
  onClose,
}: {
  runId: string;
  onClose: () => void;
}) {
  const [detail, setDetail] = useState<RunDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<"tasks" | "logs">("tasks");
  const [refresh, setRefresh] = useState(0);
  const [stopping, setStopping] = useState(false);
  const [stopError, setStopError] = useState("");
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    setDetail(null);
    setError(null);
    setTab("tasks");
    const load = async () => {
      try {
        const next = await workflowsApi.runDetail(runId);
        if (!active) return;
        setDetail(next);
        setError(null);
        if (
          ["RUNNING", "SCHEDULED", "PENDING", "CANCELLING"].includes(
            next.run.state_type,
          )
        )
          timer = setTimeout(load, 3000);
      } catch (reason) {
        if (active) setError((reason as Error).message);
      }
    };
    void load();
    heading.current?.focus({ preventScroll: true });
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [runId, refresh]);
  return (
    <section className="model-run-detail" aria-label="실행 상세">
      <header>
        <div>
          <span>실행 상세</span>
          <h3 ref={heading} tabIndex={-1}>
            {detail?.run.name || "불러오는 중…"}
          </h3>
        </div>
        <div className="model-detail-actions">
          <button
            className="page-icon-button"
            aria-label="실행 상세 새로고침"
            onClick={() => setRefresh((value) => value + 1)}
          >
            <RefreshCw size={14} />
          </button>
          <button
            className="page-icon-button"
            aria-label="실행 상세 닫기"
            onClick={onClose}
          >
            <X size={16} />
          </button>
        </div>
      </header>
      {error ? (
        <p role="alert" className="workspace-error">
          {error}
        </p>
      ) : !detail ? (
        <PageState loading title="실행 상세를 불러오고 있습니다…" />
      ) : (
        <>
          {stopError && (
            <p role="alert" className="workspace-error">
              {stopError}
            </p>
          )}
          <div className="model-detail-summary">
            {detail.can_cancel && (
              <button
                className="operations-link"
                disabled={stopping}
                onClick={async () => {
                  setStopping(true);
                  setStopError("");
                  try {
                    await workflowsApi.cancel(runId);
                    setRefresh((value) => value + 1);
                  } catch (reason) {
                    setStopError((reason as Error).message);
                  } finally {
                    setStopping(false);
                  }
                }}
              >
                {stopping ? "중지 요청 중…" : "실행 중지"}
              </button>
            )}
            <span className={`model-state ${detail.run.state_type}`}>
              {detail.run.state_name ||
                stateLabels[detail.run.state_type] ||
                detail.run.state_type}
            </span>
            <span>소요 {runDurationLabel(detail.run)}</span>
            <a
              href={`/prefect/runs/flow-run/${encodeURIComponent(runId)}`}
              target="_blank"
              rel="noreferrer"
            >
              Prefect에서 보기 <ExternalLink size={12} />
            </a>
          </div>
          <dl className="model-run-facts">
            <div>
              <dt>시작</dt>
              <dd>{dateLabel(detail.run.start_time)}</dd>
            </div>
            <div>
              <dt>종료</dt>
              <dd>{dateLabel(detail.run.end_time)}</dd>
            </div>
            {Object.entries(detail.run.parameters).map(([key, value]) => (
              <div key={key}>
                <dt>{key === "model_version" ? "모델 버전" : "요청 주체"}</dt>
                <dd>{value}</dd>
              </div>
            ))}
          </dl>
          {detail.run.message && (
            <p className={`model-state-message ${detail.run.state_type}`}>
              {detail.run.message}
            </p>
          )}
          {!!detail.subflows?.length && (
            <div className="model-task-list" aria-label="하위 Flow 진행 상황">
              {detail.subflows.map((child) => (
                <article key={child.id}>
                  <span className={`model-state-dot ${child.state_type}`} />
                  <div>
                    <strong>{child.name}</strong>
                    <small>
                      {child.state_name ||
                        stateLabels[child.state_type] ||
                        child.state_type}{" "}
                      · {runDurationLabel(child)}
                    </small>
                    <a
                      href={`/prefect/runs/flow-run/${encodeURIComponent(child.id)}`}
                      target="_blank"
                      rel="noreferrer"
                    >
                      하위 Flow 단계·로그 <ExternalLink size={12} />
                    </a>
                  </div>
                </article>
              ))}
            </div>
          )}
          <div
            className="model-detail-tabs"
            role="tablist"
            aria-label="실행 상세 보기"
          >
            <button
              role="tab"
              aria-selected={tab === "tasks"}
              onClick={() => setTab("tasks")}
            >
              Task 단계 {detail.tasks.length}
            </button>
            <button
              role="tab"
              aria-selected={tab === "logs"}
              onClick={() => setTab("logs")}
            >
              실행 로그 {detail.logs.length}
            </button>
          </div>
          {tab === "tasks" ? (
            <div
              className="model-task-list"
              role="tabpanel"
              aria-label="Task 단계"
            >
              {detail.tasks.map((task) => (
                <article key={task.id}>
                  <span className={`model-state-dot ${task.state_type}`} />
                  <div>
                    <strong>{task.name}</strong>
                    <small>
                      {stateLabels[task.state_type] || task.state_type} ·{" "}
                      {runDurationLabel(task)}
                      {(task.run_count || 0) > 1
                        ? ` · 시도 ${task.run_count}회`
                        : ""}
                    </small>
                    {["FAILED", "CRASHED"].includes(task.state_type) &&
                      task.message && <p>{task.message}</p>}
                  </div>
                </article>
              ))}
              {!detail.tasks.length && (
                <p className="model-empty-note">
                  아직 기록된 Task가 없습니다. 실행이 시작되면 표시됩니다.
                </p>
              )}
              {detail.tasks_limited && (
                <p className="model-empty-note">
                  처음 100개 Task를 표시합니다. 전체 기록은 Prefect에서
                  확인하세요.
                </p>
              )}
            </div>
          ) : (
            <div
              role="tabpanel"
              aria-label="실행 로그"
              className="model-log-panel"
            >
              {detail.logs_limited && <p>최근 100개 로그를 표시합니다.</p>}
              {detail.logs.map((log) => (
                <div key={log.id} className={log.level >= 40 ? "error" : ""}>
                  <time>{dateLabel(log.timestamp)}</time>
                  <span>
                    {log.level >= 40
                      ? "ERROR"
                      : log.level >= 30
                        ? "WARN"
                        : "INFO"}
                  </span>
                  <pre>{log.message}</pre>
                </div>
              ))}
              {!detail.logs.length && <p>기록된 로그가 없습니다.</p>}
            </div>
          )}
        </>
      )}
    </section>
  );
}
