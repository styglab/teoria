import { getJson, postJson, patchJson } from "./http_client";
export type ModelRun = {
  id: string;
  name: string;
  deployment_id: string;
  state_type: string;
  state_name?: string;
  requested_by?: string;
  model_version?: number;
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
  category?: string;
  input_kind?: "none" | "manifest" | "model" | "version";
  schedules?: Array<{
    id: string;
    active: boolean;
    schedule: {
      cron?: string;
      interval?: number;
      rrule?: string;
      timezone?: string;
    };
  }>;
  next_run?: ModelRun | null;
  running_runs?: ModelRun[];
  can_run?: boolean;
  can_manage_schedule?: boolean;
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
  subflows?: ModelRun[];
  can_cancel?: boolean;
  tasks_limited: boolean;
  logs_limited: boolean;
};

export const workflowsApi = {
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
    return getJson<PipelinePage>(`/workflows/pipelines?${query}`);
  },
  runDetail: (id: string) =>
    getJson<RunDetail>(`/workflows/runs/${encodeURIComponent(id)}`),
  run: (
    id: string,
    key: string,
    options?: { deploy?: boolean; manifest?: Record<string, unknown> },
  ) =>
    postJson<{ flow_run_id: string; name: string }>(
      `/workflows/pipelines/${encodeURIComponent(id)}/runs`,
      { idempotency_key: key, ...options },
    ),
  cancel: (id: string) =>
    postJson<{ status: string }>(
      `/workflows/runs/${encodeURIComponent(id)}/cancel`,
      {},
    ),
  schedule: (
    pipeline: string,
    id: string,
    change: boolean | { active?: boolean; cron?: string; timezone?: string },
  ) =>
    patchJson<{ active: boolean }>(
      `/workflows/pipelines/${encodeURIComponent(pipeline)}/schedules/${encodeURIComponent(id)}`,
      typeof change === "boolean" ? { active: change } : change,
    ),
};
