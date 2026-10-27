import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { ModelOperations } from "./ModelOperations";
import {
  modelOperationsApi,
  type InferenceService,
} from "../../api/model_operations";
import {
  workflowsApi,
  type Pipeline,
  type RunDetail,
} from "../../api/workflows";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});
const pipeline: Pipeline = {
  id: "openmetadata-postgres-metadata-sync",
  name: "메타데이터 동기화",
  category: "메타데이터",
  available: true,
  paused: false,
  deployment_id: "metadata",
  requires_model_version: false,
  input_kind: "none",
  can_run: true,
  can_manage_schedule: true,
  schedules: [
    {
      id: "schedule-1",
      active: true,
      schedule: { cron: "0 5 * * *", timezone: "Asia/Seoul" },
    },
  ],
};
export const service: InferenceService = {
  id: "churn",
  name: "고객 이탈 예측",
  endpoint: "/inference-api/predict",
  method: "POST",
  description: "합성 검증",
  model_name: "demo",
  model_version: 2,
  status: "ok",
  environment: "검증",
  deployment_pipeline_id: "demo-deploy-customer-churn",
  request_schema: {
    properties: {
      tenure_months: { type: "integer", minimum: 1, maximum: 72 },
      monthly_spend: { type: "number", minimum: 0 },
      login_days_30d: { type: "integer", minimum: 0, maximum: 30 },
      support_tickets_30d: { type: "integer", minimum: 0 },
    },
    required: [
      "tenure_months",
      "monthly_spend",
      "login_days_30d",
      "support_tickets_30d",
    ],
  },
};
const detail: RunDetail = {
  run: {
    id: "run-1",
    name: "metadata-run",
    deployment_id: "metadata",
    state_type: "RUNNING",
    start_time: null,
    created: "2026-10-27T00:00:00Z",
    pipeline_id: pipeline.id,
    parameters: {},
    message: "",
  },
  tasks: [
    {
      id: "task-1",
      name: "자산 동기화",
      state_type: "RUNNING",
      deployment_id: "metadata",
      start_time: null,
      created: "2026-10-27T00:00:00Z",
      message: "",
    },
  ],
  logs: [
    {
      id: "log-1",
      timestamp: "2026-10-27T00:00:01Z",
      level: 20,
      task_run_id: "task-1",
      message: "동기화 시작",
    },
  ],
  tasks_limited: false,
  logs_limited: false,
  can_cancel: true,
};
function setup() {
  vi.spyOn(workflowsApi, "pipelines").mockResolvedValue({
    enabled: true,
    items: [pipeline],
    runs: [],
    total: 0,
  });
  vi.spyOn(workflowsApi, "runDetail").mockResolvedValue(detail);
  vi.spyOn(modelOperationsApi, "services").mockResolvedValue({
    items: [service],
  });
  vi.spyOn(modelOperationsApi, "models").mockImplementation(
    async (options) => ({
      model_name: options?.model || "demo",
      demo_model_name: "demo",
      registered_models: [
        {
          name: "demo",
          description: "Churn",
          aliases: [],
          latest_versions: [{ version: "2" }],
        },
        {
          name: "forecast",
          description: "Revenue",
          aliases: [],
          latest_versions: [{ version: "2" }],
        },
      ],
      items: [
        {
          name: options?.model || "demo",
          version: "2",
          status: "READY",
          run_id: "run-1",
          creation_timestamp: 0,
          metrics: { rmse: 1.2 },
        },
      ],
      serving: { status: "ok", model_name: "demo", model_version: 2 },
      synthetic: true,
    }),
  );
}
function renderPipeline(path = `/?pipeline=${pipeline.id}`) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <ModelOperations view="pipelines" />
    </MemoryRouter>,
  );
}

it("uses a sidebar catalog without demo cards or an MLflow dependency", async () => {
  setup();
  renderPipeline();
  expect(
    await screen.findByRole("heading", { name: "메타데이터 동기화" }),
  ).toBeTruthy();
  expect(
    screen.getByRole("complementary", { name: "파이프라인 목록" }),
  ).toBeTruthy();
  expect(screen.queryByText("독립 작업")).toBeNull();
  expect(modelOperationsApi.models).not.toHaveBeenCalled();
});
it("edits cron and timezone and applies the actual schedule", async () => {
  setup();
  const save = vi
    .spyOn(workflowsApi, "schedule")
    .mockResolvedValue({ active: true });
  renderPipeline();
  await screen.findByRole("heading", { name: "메타데이터 동기화" });
  fireEvent.click(screen.getByRole("button", { name: "스케줄" }));
  fireEvent.click(await screen.findByRole("button", { name: "스케줄 변경" }));
  fireEvent.change(screen.getByRole("textbox", { name: "Cron 주기" }), {
    target: { value: "0 6 * * *" },
  });
  fireEvent.change(screen.getByRole("textbox", { name: "시간대" }), {
    target: { value: "UTC" },
  });
  fireEvent.click(screen.getByRole("button", { name: "변경 적용" }));
  await waitFor(() =>
    expect(save).toHaveBeenCalledWith(pipeline.id, "schedule-1", {
      cron: "0 6 * * *",
      timezone: "UTC",
    }),
  );
});
it("submits manual execution after input is reviewed", async () => {
  setup();
  const run = vi
    .spyOn(workflowsApi, "run")
    .mockResolvedValue({ flow_run_id: "run-1", name: "metadata-run" });
  renderPipeline();
  fireEvent.click(await screen.findByRole("button", { name: "수동 실행" }));
  expect(await screen.findByRole("dialog", { name: "수동 실행" })).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "실행 요청" }));
  await waitFor(() =>
    expect(run).toHaveBeenCalledWith(pipeline.id, expect.any(String), {}),
  );
  expect(await screen.findByText("자산 동기화")).toBeTruthy();
});
it("supports cancelling a run and inspecting its logs", async () => {
  setup();
  const cancel = vi
    .spyOn(workflowsApi, "cancel")
    .mockResolvedValue({ status: "cancellation_requested" });
  renderPipeline(`/?pipeline=${pipeline.id}&tab=history&run=run-1`);
  fireEvent.click(await screen.findByRole("button", { name: "실행 중지" }));
  await waitFor(() => expect(cancel).toHaveBeenCalledWith("run-1"));
  fireEvent.click(await screen.findByRole("tab", { name: /실행 로그/ }));
  expect(await screen.findByText("동기화 시작")).toBeTruthy();
});
it("resets history pagination when a state filter changes", async () => {
  setup();
  vi.mocked(workflowsApi.pipelines).mockResolvedValue({
    enabled: true,
    items: [pipeline],
    runs: [],
    total: 61,
  });
  renderPipeline(`/?pipeline=${pipeline.id}&tab=history&page=1`);
  fireEvent.change(await screen.findByRole("combobox", { name: "상태" }), {
    target: { value: "FAILED" },
  });
  await waitFor(() =>
    expect(workflowsApi.pipelines).toHaveBeenLastCalledWith(
      expect.objectContaining({
        pipeline: pipeline.id,
        page: 0,
        state: "FAILED",
      }),
    ),
  );
});
it("browses models in the sidebar and shows metrics on the versions tab", async () => {
  setup();
  render(
    <MemoryRouter>
      <ModelOperations view="models" />
    </MemoryRouter>,
  );
  fireEvent.click(await screen.findByRole("button", { name: /forecast/ }));
  fireEvent.click(await screen.findByRole("button", { name: "버전" }));
  expect(await screen.findByText("rmse")).toBeTruthy();
  expect(modelOperationsApi.models).toHaveBeenLastCalledWith(
    expect.objectContaining({ model: "forecast" }),
  );
});
it("shows inference test fields from the selected service schema", async () => {
  setup();
  const predict = vi.spyOn(modelOperationsApi, "predict").mockResolvedValue({
    churn_probability: 0.4,
    predicted_churn: false,
    model_version: 2,
    synthetic_demo_only: true,
  });
  render(
    <MemoryRouter>
      <ModelOperations view="serving" />
    </MemoryRouter>,
  );
  fireEvent.click(await screen.findByRole("button", { name: "추론 테스트" }));
  fireEvent.click(screen.getByRole("button", { name: "추론 실행" }));
  await waitFor(() =>
    expect(predict).toHaveBeenCalledWith({
      tenure_months: 12,
      monthly_spend: 50,
      login_days_30d: 8,
      support_tickets_30d: 3,
    }),
  );
  expect(await screen.findByText(/합성 고객 이탈 확률 40.0%/)).toBeTruthy();
});
it("keeps automatic deployment opt-in in the run dialog", async () => {
  setup();
  vi.mocked(workflowsApi.pipelines).mockResolvedValue({
    enabled: true,
    items: [
      {
        ...pipeline,
        id: "demo-customer-churn-pipeline",
        name: "모델 학습·배포",
        category: "모델",
        input_kind: "model",
      },
    ],
    runs: [],
  });
  const run = vi
    .spyOn(workflowsApi, "run")
    .mockResolvedValue({ flow_run_id: "run-1", name: "demo-run" });
  renderPipeline("/?pipeline=demo-customer-churn-pipeline");
  fireEvent.click(await screen.findByRole("button", { name: "수동 실행" }));
  const checkbox = await screen.findByRole("checkbox", {
    name: /평가 통과 후 자동 배포/,
  });
  expect((checkbox as HTMLInputElement).checked).toBe(false);
  fireEvent.click(checkbox);
  fireEvent.click(screen.getByRole("button", { name: "실행 요청" }));
  await waitFor(() =>
    expect(run).toHaveBeenCalledWith(
      "demo-customer-churn-pipeline",
      expect.any(String),
      { deploy: true },
    ),
  );
});
