import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  ArrowRight,
  Database,
  FlaskConical,
  Layers,
  Play,
  RefreshCw,
  Rocket,
  Workflow,
} from "lucide-react";
import {
  modelOperationsApi,
  type ModelCatalog,
  type ModelRun,
  type Pipeline,
} from "../../api/model_operations";
import {
  PageHeader,
  PageState,
} from "../../components/workspace/WorkspaceLayout";
import { CatalogPagination } from "../../components/workspace/CatalogPagination";
import { Button } from "../../components/ui/button";
import { RunDetailPanel } from "./RunDetailPanel";
import {
  dateLabel,
  runDurationLabel,
  metricLabel,
  stateLabels,
} from "./presentation";

const stages: Record<
  string,
  { icon: typeof Database; input: string; output: string; description: string }
> = {
  "demo-seed-customers": {
    icon: Database,
    input: "고정 seed의 합성 데이터",
    output: "고객·이용 이력 각 600건",
    description:
      "가상 개인정보와 이용 이력을 준비합니다. 다시 실행해도 기존 샘플을 중복 생성하지 않습니다.",
  },
  "openmetadata-postgres-metadata-sync": {
    icon: Layers,
    input: "Data DB 스키마·조회 권한",
    output: "OpenMetadata 데이터 자산",
    description:
      "테이블과 컬럼 메타데이터를 동기화합니다. AI 진단은 자산 상세에서 별도로 요청합니다.",
  },
  "demo-train-customer-churn": {
    icon: FlaskConical,
    input: "합성 이용 이력 600건",
    output: "평가 지표·등록 모델 버전",
    description:
      "식별정보를 제외한 네 이용 특성으로 학습하고, 별도 평가 데이터의 결과를 MLflow에 기록합니다.",
  },
  "demo-deploy-customer-churn": {
    icon: Rocket,
    input: "명시적으로 선택한 모델 버전",
    output: "검증된 추론 엔드포인트",
    description:
      "모델 checksum과 준비 상태를 확인해 배포합니다. 이전 버전을 선택하면 복구할 수 있습니다.",
  },
};
function createRequestId(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 15) | 64;
  bytes[8] = (bytes[8] & 63) | 128;
  const hex = Array.from(bytes, (byte) =>
    byte.toString(16).padStart(2, "0"),
  ).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}
export function ModelOperations({
  view,
}: {
  view: "pipelines" | "models" | "serving";
}) {
  const [params, setParams] = useSearchParams();
  const selectedRun = params.get("run");
  const pipelineFilter = params.get("pipeline") || "";
  const stateFilter = params.get("state") || "";
  const page = Math.max(0, Math.floor(Number(params.get("page")) || 0));
  const pageSize = params.get("size") === "50" ? 50 : 25;
  const update = (values: Record<string, string>) =>
    setParams(
      (previous) => {
        const next = new URLSearchParams(previous);
        next.delete("page");
        Object.entries(values).forEach(([key, value]) =>
          value ? next.set(key, value) : next.delete(key),
        );
        return next;
      },
      { replace: true },
    );
  const selectRun = (id: string) =>
    setParams(
      (previous) => {
        const next = new URLSearchParams(previous);
        id ? next.set("run", id) : next.delete("run");
        return next;
      },
      { replace: true },
    );
  const [pipelines, setPipelines] = useState<Pipeline[]>([]);
  const [runs, setRuns] = useState<ModelRun[]>([]);
  const [total, setTotal] = useState(0);
  const [models, setModels] = useState<ModelCatalog | null>(null);
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [modelError, setModelError] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [busy, setBusy] = useState<string | null>(null);
  const [version, setVersion] = useState("");
  const [inspectedVersion, setInspectedVersion] = useState("");
  const [inputs, setInputs] = useState({
    tenure_months: 12,
    monthly_spend: 50,
    login_days_30d: 8,
    support_tickets_30d: 3,
  });
  const [prediction, setPrediction] = useState<Awaited<
    ReturnType<typeof modelOperationsApi.predict>
  > | null>(null);
  const keys = useRef<Record<string, string>>({});
  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    const load = async () => {
      try {
        const data = await modelOperationsApi.pipelines({
          pipeline: pipelineFilter,
          state: stateFilter,
          page,
          size: pageSize,
        });
        if (!active) return;
        if (
          data.total !== undefined &&
          page > Math.max(0, Math.ceil(data.total / pageSize) - 1)
        ) {
          setParams(
            (previous) => {
              const next = new URLSearchParams(previous);
              next.set(
                "page",
                String(Math.max(0, Math.ceil(data.total! / pageSize) - 1)),
              );
              return next;
            },
            { replace: true },
          );
          return;
        }
        setEnabled(data.enabled);
        setPipelines(data.items);
        setRuns(data.runs);
        setTotal(data.total ?? data.runs.length);
        setError(null);
        if (data.enabled) {
          try {
            const catalog = await modelOperationsApi.models();
            if (active) {
              setModels(catalog);
              setModelError(null);
            }
          } catch (reason) {
            if (active) setModelError((reason as Error).message);
          }
        }
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
  }, [refresh, pipelineFilter, stateFilter, page, pageSize]);
  const run = async (pipeline: Pipeline) => {
    setBusy(pipeline.id);
    setActionError(null);
    setMessage("");
    try {
      const scope = `${pipeline.id}:${pipeline.requires_model_version ? version : "default"}`;
      const key = keys.current[scope] ?? createRequestId();
      keys.current[scope] = key;
      const result = await modelOperationsApi.run(
        pipeline.id,
        key,
        pipeline.requires_model_version ? Number(version) : undefined,
      );
      delete keys.current[scope];
      setMessage(`실행 요청 완료: ${result.name}`);
      selectRun(result.flow_run_id);
      setRefresh((value) => value + 1);
    } catch (reason) {
      setActionError((reason as Error).message);
    } finally {
      setBusy(null);
    }
  };
  const inspected =
    models?.items.find((item) => item.version === inspectedVersion) ??
    models?.items[0];
  const latestTraining = models?.items[0];
  const deployed = models?.items.find(
    (item) => Number(item.version) === models.serving.model_version,
  );
  const pageTitles = {
    pipelines: "파이프라인",
    models: "모델 레지스트리",
    serving: "추론 서비스",
  };
  const pageDescriptions = {
    pipelines:
      "데이터 준비부터 모델 배포까지, 실제 실행 상태와 결과를 확인합니다.",
    models: "등록 모델 버전과 평가 지표, 학습 데이터의 이력을 확인합니다.",
    serving: "현재 배포 버전과 엔드포인트 상태를 확인하고 추론을 테스트합니다.",
  };
  return (
    <div className="model-operations-page">
      <PageHeader
        title={pageTitles[view]}
        description={pageDescriptions[view]}
        actions={
          <>
            {view !== "pipelines" && (
              <Link
                className="page-primary-link"
                to={`/admin/workflows?pipeline=${view === "models" ? "demo-train-customer-churn" : "demo-deploy-customer-churn"}`}
              >
                {view === "models" ? "학습 파이프라인" : "배포 파이프라인"}
              </Link>
            )}
            <button
              className="page-icon-button"
              aria-label="MLOps 새로고침"
              onClick={() => setRefresh((value) => value + 1)}
            >
              <RefreshCw size={16} />
            </button>
          </>
        }
      />
      <div className="model-context-bar">
        <span>
          <i />
          합성 고객 데이터 · 실제 고객의 개인정보가 아닙니다
        </span>
        <div>
          <Link to="/admin/data-catalog?schema=teoria_postgresql.teoria_data.mlops_demo">
            데이터 자산 <ArrowRight size={13} />
          </Link>
          <Link to={view === "models" ? "/admin/serving" : "/admin/models"}>
            {view === "models" ? "추론 서비스" : "모델 레지스트리"}{" "}
            <ArrowRight size={13} />
          </Link>
          {view === "serving" && (
            <Link to="/admin/workflows">
              파이프라인 <ArrowRight size={13} />
            </Link>
          )}
        </div>
      </div>
      {error && (
        <p className="workspace-error" role="alert">
          {error}
        </p>
      )}
      {modelError && (
        <p className="workspace-error" role="alert">
          모델 지표 조회 실패: {modelError}
        </p>
      )}
      {actionError && (
        <p className="workspace-error" role="alert">
          {actionError}
        </p>
      )}
      {message && (
        <p role="status" className="model-action-message">
          {message}
        </p>
      )}
      {enabled === null && !error ? (
        <PageState loading title="모델 운영 상태를 확인하고 있습니다…" />
      ) : enabled === false ? (
        <PageState
          title="MLOps 기능이 설정되지 않았습니다"
          description="연결 및 설정에서 MLOps 서비스 구성을 확인하세요."
        />
      ) : (
        enabled && (
          <>
            <div className="model-overview-stats">
              <article>
                <Workflow size={17} />
                <span>
                  {view === "pipelines"
                    ? "등록·활성 파이프라인"
                    : view === "models"
                      ? "조회 모델 버전"
                      : "추론 엔드포인트"}
                </span>
                <strong>
                  {view === "pipelines" ? (
                    <>
                      {
                        pipelines.filter(
                          (item) => item.available && !item.paused,
                        ).length
                      }
                      <small> / {pipelines.length}</small>
                    </>
                  ) : view === "models" ? (
                    (models?.items.length ?? "—")
                  ) : models?.serving.status === "ok" ? (
                    "1개 활성"
                  ) : (
                    "활성 상태 확인"
                  )}
                </strong>
              </article>
              <article>
                <FlaskConical size={17} />
                <span>최근 등록 모델</span>
                <strong>
                  {latestTraining ? `v${latestTraining.version}` : "미등록"}
                </strong>
              </article>
              <article>
                <Rocket size={17} />
                <span>추론 서비스</span>
                <strong>
                  {models?.serving.status === "ok"
                    ? `정상 · v${models.serving.model_version}`
                    : "상태 확인 필요"}
                </strong>
              </article>
              <article>
                <Layers size={17} />
                <span>
                  {view === "serving"
                    ? "배포 모델 ROC AUC"
                    : "최근 모델 ROC AUC"}
                </span>
                <strong>
                  {metricLabel(
                    (view === "serving" ? deployed : latestTraining)?.metrics
                      ?.roc_auc,
                  )}
                </strong>
                <small>합성 평가 데이터 기준</small>
              </article>
            </div>
            {view === "pipelines" ? (
              <>
                <div className="model-section-heading">
                  <div>
                    <h3>실행 흐름</h3>
                    <p>
                      각 단계는 독립적으로 실행됩니다. 등록된 모델 버전을 선택해
                      배포하세요.
                    </p>
                  </div>
                  <Link to="/admin/data-catalog/assets/teoria_postgresql.teoria_data.mlops_demo.customers">
                    샘플 자산 AI 진단 <ArrowRight size={13} />
                  </Link>
                </div>
                <div className="model-pipeline-list">
                  {pipelines.map((pipeline, index) => {
                    const stage = stages[pipeline.id];
                    const Icon = stage?.icon || Workflow;
                    return (
                      <article key={pipeline.id}>
                        <header>
                          <span className="model-stage-number">
                            {String(index + 1).padStart(2, "0")}
                          </span>
                          <Icon size={18} />
                          <span
                            className={`model-state ${pipeline.latest_run?.state_type || "unrun"}`}
                          >
                            {!pipeline.available
                              ? "미등록"
                              : pipeline.paused
                                ? "일시정지"
                                : pipeline.latest_run
                                  ? stateLabels[
                                      pipeline.latest_run.state_type
                                    ] || pipeline.latest_run.state_type
                                  : "실행 전"}
                          </span>
                        </header>
                        <h4>{pipeline.name}</h4>
                        <p>{stage?.description || pipeline.description}</p>
                        <dl>
                          <div>
                            <dt>입력</dt>
                            <dd>{stage?.input || "설정된 파라미터"}</dd>
                          </div>
                          <div>
                            <dt>산출물</dt>
                            <dd>{stage?.output || "실행 결과"}</dd>
                          </div>
                        </dl>
                        <div className="model-stage-latest">
                          {pipeline.latest_run ? (
                            <button
                              onClick={() => selectRun(pipeline.latest_run!.id)}
                            >
                              최근 실행 ·{" "}
                              {runDurationLabel(pipeline.latest_run)}{" "}
                              <ArrowRight size={12} />
                            </button>
                          ) : (
                            <span>실행 이력이 없습니다</span>
                          )}
                        </div>
                        <footer>
                          {pipeline.requires_model_version && (
                            <label>
                              배포할 모델 버전
                              <select
                                aria-label="배포할 모델 버전"
                                value={version}
                                onChange={(event) =>
                                  setVersion(event.target.value)
                                }
                              >
                                <option value="">선택</option>
                                {models?.items.map((item) => (
                                  <option
                                    key={item.version}
                                    value={item.version}
                                  >
                                    v{item.version}
                                    {Number(item.version) ===
                                    models.serving.model_version
                                      ? " · 현재 배포"
                                      : ""}
                                  </option>
                                ))}
                              </select>
                            </label>
                          )}
                          <Button
                            disabled={
                              !!busy ||
                              !pipeline.available ||
                              pipeline.paused ||
                              (pipeline.requires_model_version && !version)
                            }
                            onClick={() => run(pipeline)}
                          >
                            <Play size={14} />
                            {busy === pipeline.id ? "요청 중…" : "실행"}
                          </Button>
                        </footer>
                      </article>
                    );
                  })}
                </div>
                <div className="model-section-heading">
                  <div>
                    <h3>실행 이력</h3>
                    <p>행을 선택하면 Task 단계와 로그를 확인할 수 있습니다.</p>
                  </div>
                  <span className="model-poll-note">
                    <i />
                    10초마다 갱신
                  </span>
                </div>
                <div className="model-history-controls">
                  <label>
                    파이프라인
                    <select
                      value={pipelineFilter}
                      onChange={(event) =>
                        update({ pipeline: event.target.value })
                      }
                    >
                      <option value="">전체 파이프라인</option>
                      {pipelines.map((item) => (
                        <option key={item.id} value={item.id}>
                          {item.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    상태
                    <select
                      value={stateFilter}
                      onChange={(event) =>
                        update({ state: event.target.value })
                      }
                    >
                      <option value="">전체 상태</option>
                      {Object.entries(stateLabels)
                        .filter(
                          ([key]) => !["CANCELLING", "PAUSED"].includes(key),
                        )
                        .map(([key, label]) => (
                          <option key={key} value={key}>
                            {label}
                          </option>
                        ))}
                    </select>
                  </label>
                  <span>
                    {stateFilter === "SCHEDULED"
                      ? "향후 예약 포함"
                      : "향후 예약을 제외한 실행 기록"}
                  </span>
                </div>
                <div
                  className={`model-run-workspace ${selectedRun ? "with-detail" : ""}`}
                >
                  <div className="model-history-panel">
                    <div
                      className="page-table-wrap model-run-list"
                      aria-busy={!!error}
                    >
                      <table className="page-table">
                        <thead>
                          <tr>
                            <th>실행 / 요청 시각</th>
                            <th>파이프라인</th>
                            <th>상태</th>
                            <th>소요 시간</th>
                            <th>상세</th>
                          </tr>
                        </thead>
                        <tbody>
                          {runs.map((item) => (
                            <tr
                              key={item.id}
                              className={
                                selectedRun === item.id ? "selected" : ""
                              }
                            >
                              <td>
                                <button
                                  className="model-run-name"
                                  onClick={() => selectRun(item.id)}
                                >
                                  {item.name}
                                </button>
                                <small>{dateLabel(item.created)}</small>
                              </td>
                              <td>
                                {pipelines.find(
                                  (p) => p.deployment_id === item.deployment_id,
                                )?.name || "—"}
                              </td>
                              <td>
                                <span
                                  className={`model-state ${item.state_type}`}
                                >
                                  {stateLabels[item.state_type] ||
                                    item.state_type}
                                </span>
                              </td>
                              <td>{runDurationLabel(item)}</td>
                              <td>
                                <button
                                  className="model-detail-button"
                                  aria-label={`${item.name} 실행 상세`}
                                  onClick={() => selectRun(item.id)}
                                >
                                  보기 <ArrowRight size={12} />
                                </button>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                      {!runs.length && (
                        <PageState
                          title={
                            pipelineFilter || stateFilter
                              ? "조건에 맞는 실행이 없습니다"
                              : "실행 이력이 없습니다"
                          }
                        />
                      )}
                    </div>
                    <CatalogPagination
                      page={page}
                      pageSize={pageSize}
                      total={total}
                      error={!!error}
                      onPageChange={(value) => update({ page: String(value) })}
                      onPageSizeChange={(value) =>
                        update({ size: String(value) })
                      }
                    />
                  </div>
                  {selectedRun && (
                    <RunDetailPanel
                      runId={selectedRun}
                      onClose={() => selectRun("")}
                    />
                  )}
                </div>
              </>
            ) : (
              <>
                {view === "models" && (
                  <>
                    <div className="model-section-heading">
                      <div>
                        <h3>등록 모델 버전</h3>
                        <p>
                          버전을 선택해 평가 지표와 학습 데이터 정보를
                          확인하세요.
                        </p>
                      </div>
                    </div>
                    <div className="model-version-workspace">
                      <div className="page-table-wrap">
                        <table className="page-table">
                          <thead>
                            <tr>
                              <th>버전</th>
                              <th>정확도</th>
                              <th>ROC AUC</th>
                              <th>등록 시각</th>
                              <th>학습 실행</th>
                            </tr>
                          </thead>
                          <tbody>
                            {models?.items.map((item) => (
                              <tr
                                key={item.version}
                                className={
                                  inspected?.version === item.version
                                    ? "selected"
                                    : ""
                                }
                              >
                                <td>
                                  <button
                                    className="model-run-name"
                                    onClick={() =>
                                      setInspectedVersion(item.version)
                                    }
                                  >
                                    v{item.version}
                                  </button>
                                  {Number(item.version) ===
                                    models.serving.model_version &&
                                    models.serving.status === "ok" && (
                                      <span className="model-state COMPLETED">
                                        현재 배포
                                      </span>
                                    )}
                                </td>
                                <td>
                                  {metricLabel(item.metrics?.accuracy, true)}
                                </td>
                                <td>{metricLabel(item.metrics?.roc_auc)}</td>
                                <td>{dateLabel(item.creation_timestamp)}</td>
                                <td>
                                  <code>{item.run_id.slice(0, 12)}…</code>
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                        {!models?.items.length && (
                          <PageState
                            title="등록된 모델이 없습니다"
                            description="파이프라인 화면에서 데이터 준비와 모델 학습을 실행하세요."
                          />
                        )}
                      </div>
                      {inspected && (
                        <aside className="model-version-detail">
                          <span>모델 v{inspected.version}</span>
                          <h3>학습·평가 결과</h3>
                          <dl>
                            <div>
                              <dt>학습 데이터</dt>
                              <dd>
                                {inspected.parameters?.dataset_version || "—"}
                              </dd>
                            </div>
                            <div>
                              <dt>학습 / 평가 건수</dt>
                              <dd>
                                {inspected.metrics?.training_rows ?? "—"} /{" "}
                                {inspected.metrics?.evaluation_rows ?? "—"}
                              </dd>
                            </div>
                            <div>
                              <dt>데이터 분리 seed</dt>
                              <dd>{inspected.parameters?.split_seed || "—"}</dd>
                            </div>
                            <div>
                              <dt>식별정보 학습 입력</dt>
                              <dd>
                                {inspected.parameters
                                  ?.personal_attributes_in_features === "False"
                                  ? "사용하지 않음"
                                  : "기록 확인 필요"}
                              </dd>
                            </div>
                          </dl>
                          {inspected.metrics_unavailable && (
                            <p role="alert">평가 지표를 불러오지 못했습니다.</p>
                          )}
                          <p>
                            합성 데이터에서 측정한 지표입니다. 실제 고객에 대한
                            성능으로 해석하지 않습니다.
                          </p>
                        </aside>
                      )}
                    </div>
                  </>
                )}
                {view === "serving" && (
                  <div className="model-inference-workspace">
                    <form
                      className="model-prediction-form"
                      onSubmit={async (event) => {
                        event.preventDefault();
                        setBusy("predict");
                        setActionError(null);
                        try {
                          setPrediction(
                            await modelOperationsApi.predict(inputs),
                          );
                        } catch (reason) {
                          setActionError((reason as Error).message);
                        } finally {
                          setBusy(null);
                        }
                      }}
                    >
                      <div>
                        <h3>추론 테스트</h3>
                        <p>
                          현재 배포 버전{" "}
                          {models?.serving.status === "ok"
                            ? `v${models.serving.model_version}`
                            : "없음"}
                          에 요청합니다.
                        </p>
                      </div>
                      {(
                        [
                          ["tenure_months", "이용 기간(개월)", 1, 72],
                          [
                            "monthly_spend",
                            "월 이용 금액(합성 단위)",
                            0,
                            10000,
                          ],
                          ["login_days_30d", "최근 30일 로그인 일수", 0, 30],
                          ["support_tickets_30d", "최근 30일 문의 건수", 0, 12],
                        ] as const
                      ).map(([key, label, min, max]) => (
                        <label key={key}>
                          {label}
                          <input
                            required
                            type="number"
                            min={min}
                            max={max}
                            step={key === "monthly_spend" ? "0.01" : "1"}
                            value={inputs[key]}
                            onChange={(event) => {
                              setInputs({
                                ...inputs,
                                [key]: Number(event.target.value),
                              });
                              setPrediction(null);
                            }}
                          />
                        </label>
                      ))}
                      <Button
                        disabled={!!busy || models?.serving.status !== "ok"}
                        type="submit"
                      >
                        {busy === "predict" ? "추론 중…" : "추론 실행"}
                      </Button>
                    </form>
                    <section className="model-prediction-result">
                      <span>추론 결과</span>
                      {prediction ? (
                        <>
                          <strong>
                            {(prediction.churn_probability * 100).toFixed(1)}
                            <small>%</small>
                          </strong>
                          <p role="status">
                            모델 v{prediction.model_version} · 합성 고객 이탈
                            확률{" "}
                            {(prediction.churn_probability * 100).toFixed(1)}%
                          </p>
                          <div className="model-probability-track">
                            <i
                              style={{
                                width: `${prediction.churn_probability * 100}%`,
                              }}
                            />
                          </div>
                          <small>
                            실제 고객 판단에 사용하지 않는 데모 결과입니다.
                          </small>
                        </>
                      ) : (
                        <p>이용 이력을 입력하고 추론을 실행하세요.</p>
                      )}
                      <code>POST /inference-api/predict</code>
                      <p>외부 호출에는 별도의 추론 API 토큰이 필요합니다.</p>
                    </section>
                  </div>
                )}
              </>
            )}
          </>
        )
      )}
    </div>
  );
}
