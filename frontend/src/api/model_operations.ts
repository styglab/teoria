import { getJson, postJson } from "./http_client";

export type ModelRun = {
  id: string;
  name: string;
  deployment_id: string;
  state_type: string;
  start_time: string | null;
  end_time?: string | null;
  created: string;
  expected_start_time?: string;
  total_run_time?: number;
  run_count?: number;
};
export type Pipeline = {
  id: string;
  name: string;
  available: boolean;
  paused: boolean;
  deployment_id: string | null;
  requires_model_version: boolean;
  description?: string;
  work_pool_name?: string;
  latest_run?: ModelRun | null;
};
export type PipelinePage = {
  enabled: boolean;
  items: Pipeline[];
  runs: ModelRun[];
  total?: number;
  offset?: number;
  limit?: number;
};
export type RunDetail = {
  run: ModelRun & {
    pipeline_id: string;
    parameters: Record<string, string>;
    message: string;
  };
  tasks: Array<ModelRun & { message: string }>;
  logs: Array<{
    id: string;
    timestamp: string;
    level: number;
    task_run_id: string | null;
    message: string;
  }>;
  tasks_limited: boolean;
  logs_limited: boolean;
};
export type ModelVersion = {
  name: string;
  version: string;
  status: string;
  run_id: string;
  creation_timestamp: number;
  metrics?: Record<string, number>;
  parameters?: Record<string, string>;
  metrics_unavailable?: boolean;
};
export type ModelCatalog = {
  model_name: string;
  items: ModelVersion[];
  serving: { status: string; model_version?: number };
  synthetic: boolean;
};
export const modelOperationsApi = {
  status: () => getJson<{ enabled: boolean }>("/model-operations/status"),
  pipelines: (options?: {
    pipeline?: string;
    state?: string;
    page?: number;
    size?: number;
  }) => {
    const query = new URLSearchParams();
    if (options?.pipeline) query.set("pipeline_id", options.pipeline);
    if (options?.state) query.set("state", options.state);
    query.set("offset", String((options?.page || 0) * (options?.size || 25)));
    query.set("limit", String(options?.size || 25));
    return getJson<PipelinePage>(`/model-operations/pipelines?${query}`);
  },
  runDetail: (id: string) =>
    getJson<RunDetail>(`/model-operations/runs/${encodeURIComponent(id)}`),
  models: () => getJson<ModelCatalog>("/model-operations/models"),
  run: (id: string, key: string, version?: number) =>
    postJson<{ flow_run_id: string; name: string }>(
      `/model-operations/pipelines/${encodeURIComponent(id)}/runs`,
      { idempotency_key: key, ...(version ? { model_version: version } : {}) },
    ),
  predict: (body: Record<string, number>) =>
    postJson<{
      churn_probability: number;
      predicted_churn: boolean;
      model_version: number;
      synthetic_demo_only: boolean;
    }>("/model-operations/predict", body),
};
