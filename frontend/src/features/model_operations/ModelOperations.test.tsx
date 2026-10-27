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
import { modelOperationsApi } from "../../api/model_operations";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});
const catalog = {
  model_name: "demo",
  items: [
    {
      name: "demo",
      version: "2",
      status: "READY",
      run_id: "run-1",
      creation_timestamp: 0,
    },
  ],
  serving: { status: "ok", model_version: 2 },
  synthetic: true,
};
function setup() {
  vi.spyOn(modelOperationsApi, "pipelines").mockResolvedValue({
    enabled: true,
    items: [
      {
        id: "demo-deploy-customer-churn",
        name: "고정 모델 배포",
        available: true,
        paused: false,
        deployment_id: "deployment-1",
        requires_model_version: true,
      },
    ],
    runs: [],
  });
  vi.spyOn(modelOperationsApi, "models").mockResolvedValue(catalog);
  vi.spyOn(modelOperationsApi, "runDetail").mockResolvedValue({
    run: {
      id: "run-1",
      name: "demo-run",
      deployment_id: "deployment-1",
      state_type: "COMPLETED",
      start_time: "2026-10-27T00:00:00Z",
      created: "2026-10-27T00:00:00Z",
      pipeline_id: "demo-deploy-customer-churn",
      parameters: { model_version: "2" },
      message: "Completed",
    },
    tasks: [
      {
        id: "task-1",
        name: "서빙 상태 확인",
        state_type: "COMPLETED",
        deployment_id: "deployment-1",
        start_time: null,
        created: "2026-10-27T00:00:00Z",
        message: "",
        total_run_time: 3,
      },
    ],
    logs: [
      {
        id: "log-1",
        timestamp: "2026-10-27T00:00:03Z",
        level: 20,
        task_run_id: "task-1",
        message: "샘플 추론 검증 통과",
      },
    ],
    tasks_limited: false,
    logs_limited: false,
  });
}
it("requires a selected version before requesting a deployment", async () => {
  vi.spyOn(globalThis.crypto, "randomUUID").mockImplementation(() => {
    throw new Error("secure-context API unavailable");
  });
  setup();
  const run = vi
    .spyOn(modelOperationsApi, "run")
    .mockResolvedValue({ flow_run_id: "run-1", name: "demo-run" });
  render(
    <MemoryRouter>
      <ModelOperations view="pipelines" />
    </MemoryRouter>,
  );
  await screen.findByRole("heading", { name: "고정 모델 배포" });
  expect(
    (screen.getByRole("button", { name: "실행" }) as HTMLButtonElement)
      .disabled,
  ).toBe(true);
  fireEvent.change(
    await screen.findByRole("combobox", { name: "배포할 모델 버전" }),
    { target: { value: "2" } },
  );
  fireEvent.click(screen.getByRole("button", { name: "실행" }));
  await waitFor(() =>
    expect(run).toHaveBeenCalledWith(
      "demo-deploy-customer-churn",
      expect.any(String),
      2,
    ),
  );
  expect(await screen.findByText("실행 요청 완료: demo-run")).toBeTruthy();
});
it("sends activity features to the inference endpoint", async () => {
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
  await screen.findByText("정상 · v2", { exact: false });
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

it("shows actual tasks and logs for a selected run", async () => {
  setup();
  render(
    <MemoryRouter initialEntries={["/?run=run-1"]}>
      <ModelOperations view="pipelines" />
    </MemoryRouter>,
  );
  expect(await screen.findByText("서빙 상태 확인")).toBeTruthy();
  fireEvent.click(screen.getByRole("tab", { name: /실행 로그/ }));
  expect(await screen.findByText("샘플 추론 검증 통과")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "실행 상세 닫기" }));
  expect(screen.queryByRole("region", { name: "실행 상세" })).toBeNull();
});
it("keeps pipeline controls visible when MLflow metrics are unavailable", async () => {
  setup();
  vi.mocked(modelOperationsApi.models).mockRejectedValue(
    new Error("MLflow unavailable"),
  );
  render(
    <MemoryRouter>
      <ModelOperations view="pipelines" />
    </MemoryRouter>,
  );
  expect(
    await screen.findByRole("heading", { name: "고정 모델 배포" }),
  ).toBeTruthy();
  expect(await screen.findByRole("alert")).toHaveProperty(
    "textContent",
    expect.stringContaining("MLflow unavailable"),
  );
});
it("resets the history page when a filter changes", async () => {
  setup();
  render(
    <MemoryRouter initialEntries={["/?page=1"]}>
      <ModelOperations view="pipelines" />
    </MemoryRouter>,
  );
  await waitFor(() =>
    expect(modelOperationsApi.pipelines).toHaveBeenCalledWith(
      expect.objectContaining({ page: 1 }),
    ),
  );
  fireEvent.change(screen.getByRole("combobox", { name: "상태" }), {
    target: { value: "FAILED" },
  });
  await waitFor(() =>
    expect(modelOperationsApi.pipelines).toHaveBeenCalledWith(
      expect.objectContaining({ page: 0, state: "FAILED" }),
    ),
  );
});
