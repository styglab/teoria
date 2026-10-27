import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { ExternalLink, Play, RefreshCw } from "lucide-react";
import { workflowsApi, type PipelinePage } from "../../api/workflows";
import { SelectionCatalog } from "../../components/workspace/SelectionCatalog";
import {
  PageHeader,
  PageState,
  FilterTabs,
} from "../../components/workspace/WorkspaceLayout";
import { CatalogPagination } from "../../components/workspace/CatalogPagination";
import {
  dateLabel,
  runDurationLabel,
  stateLabels,
} from "../model_operations/presentation";
import { ManualRunDialog } from "./ManualRunDialog";
import { RunDetailPanel } from "./RunDetailPanel";

export function scheduleLabel(schedule: {
  cron?: string;
  interval?: number;
  rrule?: string;
}) {
  return (
    schedule.cron ||
    (schedule.interval
      ? `${schedule.interval}초 간격`
      : schedule.rrule || "예약 실행")
  );
}
export function Pipelines() {
  const [params, setParams] = useSearchParams();
  const selectedId = params.get("pipeline") || "";
  const tab = params.get("tab") || (params.get("run") ? "history" : "overview");
  const state = params.get("state") || "";
  const page = Math.max(0, Number(params.get("page")) || 0);
  const size = params.get("size") === "50" ? 50 : 25;
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("");
  const [data, setData] = useState<PipelinePage | null>(null);
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [showRun, setShowRun] = useState(false);
  const [editingSchedule, setEditingSchedule] = useState<{
    id: string;
    cron: string;
    timezone: string;
  } | null>(null);
  const [scheduleBusy, setScheduleBusy] = useState("");
  const [actionError, setActionError] = useState("");
  const update = (values: Record<string, string>) =>
    setParams(
      (previous) => {
        const next = new URLSearchParams(previous);
        Object.entries(values).forEach(([k, v]) =>
          v ? next.set(k, v) : next.delete(k),
        );
        return next;
      },
      { replace: true },
    );
  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    setData(null);
    setError("");
    const load = async () => {
      try {
        const result = await workflowsApi.pipelines({
          pipeline: selectedId,
          state,
          page,
          size,
        });
        if (!active) return;
        setData(result);
        setError("");
        if (!selectedId && !params.get("run") && result.items[0])
          update({ pipeline: result.items[0].id });
        if (page > 0 && page * size >= (result.total || 0))
          update({ page: "" });
      } catch (reason) {
        if (active) setError((reason as Error).message);
      } finally {
        if (active) timer = setTimeout(load, 10000);
      }
    };
    void load();
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [selectedId, state, page, size, refresh]);
  const selected = data?.items.find((item) => item.id === selectedId);
  const filtered =
    data?.items.filter(
      (item) =>
        (!category || item.category === category) &&
        `${item.name} ${item.id}`
          .toLocaleLowerCase()
          .includes(query.toLocaleLowerCase()),
    ) || [];
  const choose = (id: string) => {
    setEditingSchedule(null);
    setActionError("");
    update({ pipeline: id, tab: "", run: "", page: "", state: "" });
  };
  return (
    <SelectionCatalog
      title="파이프라인"
      search={query}
      onSearch={setQuery}
      selected={selectedId}
      onSelect={choose}
      controls={
        <label className="selection-filter">
          분류
          <select
            value={category}
            onChange={(e) => setCategory(e.target.value)}
          >
            <option value="">전체</option>
            {[
              ...new Set(
                data?.items.map((item) => item.category).filter(Boolean),
              ),
            ].map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </label>
      }
      items={filtered.map((item) => ({
        id: item.id,
        title: item.name,
        subtitle: item.schedules?.length
          ? item.schedules
              .map(
                (s) =>
                  `${scheduleLabel(s.schedule)} · ${s.schedule.timezone || "UTC"}`,
              )
              .join(" / ")
          : "수동 실행",
        status: (
          <span
            className={`selection-status ${item.latest_run?.state_type || ""}`}
          >
            {item.paused
              ? "일시정지"
              : item.latest_run
                ? stateLabels[item.latest_run.state_type] ||
                  item.latest_run.state_name
                : "실행 이력 없음"}
          </span>
        ),
      }))}
      footer={<span>{filtered.length}개 파이프라인 · 10초마다 갱신</span>}
    >
      <PageHeader
        title="파이프라인"
        description="스케줄과 실행 이력을 확인하고 필요한 작업을 실행합니다."
        actions={
          <>
            <a
              href="/prefect/"
              target="_blank"
              rel="noreferrer"
              className="operations-link"
            >
              Prefect 열기 <ExternalLink size={13} />
            </a>
            <button
              className="page-icon-button"
              aria-label="파이프라인 새로고침"
              onClick={() => setRefresh((v) => v + 1)}
            >
              <RefreshCw size={16} />
            </button>
          </>
        }
      />
      {error && (
        <p role="alert" className="workspace-error">
          {error}
        </p>
      )}
      {!data ? (
        <PageState
          loading={!error}
          title={
            error
              ? "파이프라인을 불러오지 못했습니다"
              : "파이프라인을 불러오고 있습니다…"
          }
        />
      ) : !data.enabled ? (
        <PageState title="Prefect 연결이 설정되지 않았습니다" />
      ) : !selected && !params.get("run") ? (
        <PageState title="왼쪽에서 파이프라인을 선택하세요" />
      ) : (
        <>
          {selected && (
            <>
              <div className="operations-detail-heading">
                <div>
                  <span>{selected.category}</span>
                  <h3>{selected.name}</h3>
                  <p>{selected.description || "등록된 파이프라인"}</p>
                </div>
                <button
                  className="page-primary-link"
                  disabled={
                    !selected.available ||
                    selected.paused ||
                    selected.can_run === false
                  }
                  onClick={() => setShowRun(true)}
                >
                  <Play size={13} />
                  수동 실행
                </button>
              </div>
              {selected.paused && (
                <p className="operations-note">
                  일시정지된 파이프라인입니다. 활성화 설정은 Prefect에서
                  확인하세요.
                </p>
              )}
              <FilterTabs
                label="파이프라인 상세"
                value={tab}
                onChange={(value) => update({ tab: value, run: "" })}
                items={[
                  { id: "overview", label: "개요" },
                  { id: "schedule", label: "스케줄" },
                  { id: "history", label: "실행 이력" },
                ]}
              />
              {actionError && (
                <p role="alert" className="workspace-error">
                  {actionError}
                </p>
              )}
              {tab === "overview" && (
                <section className="operations-section">
                  <h4>실행 현황</h4>
                  <dl className="operations-facts">
                    <div>
                      <dt>실행 중</dt>
                      <dd>
                        {selected.running_runs?.length
                          ? selected.running_runs.map((run) => (
                              <button
                                key={run.id}
                                className="operations-link"
                                onClick={() =>
                                  update({ tab: "history", run: run.id })
                                }
                              >
                                {run.name} · {runDurationLabel(run)}
                              </button>
                            ))
                          : "현재 실행 중인 작업 없음"}
                      </dd>
                    </div>
                    <div>
                      <dt>최근 실행</dt>
                      <dd>
                        {selected.latest_run ? (
                          <button
                            className="operations-link"
                            onClick={() =>
                              update({
                                tab: "history",
                                run: selected.latest_run!.id,
                              })
                            }
                          >
                            {stateLabels[selected.latest_run.state_type] ||
                              selected.latest_run.state_name}{" "}
                            ·{" "}
                            {dateLabel(
                              selected.latest_run.start_time ||
                                selected.latest_run.created,
                            )}
                          </button>
                        ) : (
                          "실행 이력 없음"
                        )}
                      </dd>
                    </div>
                    <div>
                      <dt>최근 소요 시간</dt>
                      <dd>
                        {runDurationLabel(selected.latest_run || undefined)}
                      </dd>
                    </div>
                    <div>
                      <dt>다음 예약</dt>
                      <dd>
                        {dateLabel(selected.next_run?.expected_start_time)}
                      </dd>
                    </div>
                    <div>
                      <dt>실행 방식</dt>
                      <dd>
                        {selected.schedules?.some((s) => s.active)
                          ? "스케줄 · 수동 실행"
                          : "수동 실행"}
                      </dd>
                    </div>
                  </dl>
                  <a
                    className="operations-link"
                    href={`/prefect/deployments/deployment/${selected.deployment_id}`}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Prefect 파이프라인 상세 <ExternalLink size={12} />
                  </a>
                </section>
              )}
              {tab === "schedule" && (
                <section className="operations-section">
                  <h4>실행 스케줄</h4>
                  {!selected.schedules?.length ? (
                    <PageState
                      title="등록된 스케줄이 없습니다"
                      description="현재 수동 실행 파이프라인입니다. 주기 추가·변경은 Prefect에서 관리합니다."
                    />
                  ) : (
                    <div className="page-table-wrap">
                      <table className="page-table">
                        <thead>
                          <tr>
                            <th>주기</th>
                            <th>시간대</th>
                            <th>상태</th>
                            <th>관리</th>
                          </tr>
                        </thead>
                        <tbody>
                          {selected.schedules.map((schedule) => (
                            <tr key={schedule.id}>
                              <td>
                                <code>{scheduleLabel(schedule.schedule)}</code>
                              </td>
                              <td>{schedule.schedule.timezone || "UTC"}</td>
                              <td>{schedule.active ? "활성" : "중지"}</td>
                              <td>
                                <button
                                  className="operations-link"
                                  disabled={
                                    !!scheduleBusy ||
                                    selected.can_manage_schedule === false ||
                                    selected.paused
                                  }
                                  onClick={async () => {
                                    setScheduleBusy(schedule.id);
                                    setActionError("");
                                    try {
                                      await workflowsApi.schedule(
                                        selected.id,
                                        schedule.id,
                                        !schedule.active,
                                      );
                                      setRefresh((v) => v + 1);
                                    } catch (reason) {
                                      setActionError((reason as Error).message);
                                    } finally {
                                      setScheduleBusy("");
                                    }
                                  }}
                                >
                                  {scheduleBusy === schedule.id
                                    ? "변경 중…"
                                    : schedule.active
                                      ? "스케줄 중지"
                                      : "스케줄 활성화"}
                                </button>
                                {schedule.schedule.cron && (
                                  <button
                                    className="operations-link"
                                    disabled={
                                      !!scheduleBusy ||
                                      selected.can_manage_schedule === false
                                    }
                                    onClick={() =>
                                      setEditingSchedule({
                                        id: schedule.id,
                                        cron: schedule.schedule.cron!,
                                        timezone:
                                          schedule.schedule.timezone || "UTC",
                                      })
                                    }
                                  >
                                    스케줄 변경
                                  </button>
                                )}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                  {editingSchedule && (
                    <form
                      className="schedule-editor"
                      onSubmit={async (event) => {
                        event.preventDefault();
                        setScheduleBusy(editingSchedule.id);
                        setActionError("");
                        try {
                          await workflowsApi.schedule(
                            selected.id,
                            editingSchedule.id,
                            {
                              cron: editingSchedule.cron,
                              timezone: editingSchedule.timezone,
                            },
                          );
                          setEditingSchedule(null);
                          setRefresh((v) => v + 1);
                        } catch (reason) {
                          setActionError((reason as Error).message);
                        } finally {
                          setScheduleBusy("");
                        }
                      }}
                    >
                      <label>
                        Cron 주기
                        <input
                          required
                          value={editingSchedule.cron}
                          onChange={(event) =>
                            setEditingSchedule({
                              ...editingSchedule,
                              cron: event.target.value,
                            })
                          }
                        />
                      </label>
                      <label>
                        시간대
                        <input
                          required
                          value={editingSchedule.timezone}
                          onChange={(event) =>
                            setEditingSchedule({
                              ...editingSchedule,
                              timezone: event.target.value,
                            })
                          }
                        />
                      </label>
                      <button
                        className="page-primary-link"
                        disabled={!!scheduleBusy}
                        type="submit"
                      >
                        변경 적용
                      </button>
                      <button
                        className="operations-link"
                        type="button"
                        disabled={!!scheduleBusy}
                        onClick={() => setEditingSchedule(null)}
                      >
                        취소
                      </button>
                    </form>
                  )}
                  <p className="operations-note">
                    다음 예약:{" "}
                    {dateLabel(selected.next_run?.expected_start_time)}. 스케줄
                    중지는 이미 생성된 예약·실행을 취소하지 않습니다.
                  </p>
                  <a
                    className="operations-link"
                    href={`/prefect/deployments/deployment/${selected.deployment_id}`}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Prefect에서 주기 편집 <ExternalLink size={12} />
                  </a>
                </section>
              )}
            </>
          )}
          {(tab === "history" || !selected) && (
            <section className="operations-section">
              <div className="operations-toolbar">
                <h4>실행 이력</h4>
                <label>
                  상태
                  <select
                    value={state}
                    onChange={(e) =>
                      update({ state: e.target.value, page: "", run: "" })
                    }
                  >
                    <option value="">전체 상태</option>
                    {Object.entries(stateLabels)
                      .filter(
                        ([key]) => !["PAUSED", "CANCELLING"].includes(key),
                      )
                      .map(([key, label]) => (
                        <option key={key} value={key}>
                          {label}
                        </option>
                      ))}
                  </select>
                </label>
              </div>
              {params.get("run") ? (
                <>
                  <button
                    className="operations-link"
                    onClick={() => update({ run: "" })}
                  >
                    ← 실행 목록
                  </button>
                  <RunDetailPanel
                    runId={params.get("run")!}
                    onClose={() => update({ run: "" })}
                  />
                </>
              ) : (
                <>
                  <div className="page-table-wrap operations-history">
                    <table className="page-table">
                      <thead>
                        <tr>
                          <th>실행</th>
                          <th>상태</th>
                          <th>요청 시각</th>
                          <th>소요 시간</th>
                          <th>요청 주체</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.runs.map((run) => (
                          <tr key={run.id}>
                            <td>
                              <button
                                className="operations-link"
                                onClick={() => update({ run: run.id })}
                              >
                                {run.name}
                              </button>
                            </td>
                            <td>
                              <span className={`model-state ${run.state_type}`}>
                                {stateLabels[run.state_type] || run.state_name}
                              </span>
                            </td>
                            <td>{dateLabel(run.created)}</td>
                            <td>{runDurationLabel(run)}</td>
                            <td>{run.requested_by || "스케줄·Prefect"}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    {!data.runs.length && (
                      <PageState title="조건에 맞는 실행이 없습니다" />
                    )}
                  </div>
                  <CatalogPagination
                    page={page}
                    pageSize={size}
                    total={data.total || 0}
                    onPageChange={(value) => update({ page: String(value) })}
                    onPageSizeChange={(value) =>
                      update({ size: String(value), page: "" })
                    }
                  />
                  <p className="operations-note">
                    {state === "SCHEDULED"
                      ? "향후 예약을 포함합니다."
                      : "향후 예약을 제외한 기록입니다. 예약·대기 필터에서 예정된 실행을 확인할 수 있습니다."}
                  </p>
                </>
              )}
            </section>
          )}
        </>
      )}
      {showRun && selected && (
        <ManualRunDialog
          pipeline={selected}
          onClose={() => setShowRun(false)}
          onStarted={(id) => {
            setShowRun(false);
            update({ tab: "history", run: id, page: "", state: "" });
            setRefresh((v) => v + 1);
          }}
        />
      )}
    </SelectionCatalog>
  );
}
