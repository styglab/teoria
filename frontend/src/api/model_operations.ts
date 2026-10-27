import { getJson, postJson } from "./http_client";

import type { PipelinePage, RunDetail } from "./workflows";
export type { ModelRun, Pipeline, PipelinePage, RunDetail } from "./workflows";
export type ModelVersion = {
  name: string;
  version: string;
  status: string;
  run_id: string;
  creation_timestamp: number;
  experiment_id?: string;
  prefect_run_id?: string;
  pipeline_run_id?: string;
  metrics?: Record<string, number>;
  parameters?: Record<string, string>;
  metrics_unavailable?: boolean;
};
export type ModelCatalog = {
  model_name: string;
  demo_model_name: string;
  registered_models: Array<{
    name: string;
    description: string;
    last_updated_timestamp?: number;
    tags?: Array<{ key: string; value: string }>;
    aliases: Array<{ alias: string; version: string }>;
    latest_versions: Array<{ version: string }>;
  }>;
  next_page_token?: string;
  next_version_token?: string;
  items: ModelVersion[];
  serving: { status: string; model_name?: string; model_version?: number };
  synthetic: boolean;
};
export type InferenceService = {
  id: string;
  name: string;
  endpoint: string;
  method: string;
  description: string;
  model_name: string;
  model_version?: number;
  status: string;
  environment: string;
  request_schema: {
    properties: Record<
      string,
      { type: string; title?: string; minimum?: number; maximum?: number }
    >;
    required?: string[];
  };
  deployment_pipeline_id: string;
};
export const modelOperationsApi = {
  services: () =>
    getJson<{ items: InferenceService[] }>("/model-operations/services"),
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
  models: (options?: {
    model?: string;
    token?: string;
    versionToken?: string;
    q?: string;
  }) => {
    const query = new URLSearchParams();
    if (options?.q) query.set("q", options.q);
    if (options?.model) query.set("model_name", options.model);
    if (options?.token) query.set("page_token", options.token);
    if (options?.versionToken) query.set("version_token", options.versionToken);
    return getJson<ModelCatalog>(`/model-operations/models?${query}`);
  },
  run: (id: string, key: string, version?: number, deploy?: boolean) =>
    postJson<{ flow_run_id: string; name: string }>(
      `/model-operations/pipelines/${encodeURIComponent(id)}/runs`,
      {
        idempotency_key: key,
        ...(version ? { model_version: version } : {}),
        ...(deploy !== undefined ? { deploy } : {}),
      },
    ),
  predict: (body: Record<string, number>) =>
    postJson<{
      churn_probability: number;
      predicted_churn: boolean;
      model_version: number;
      synthetic_demo_only: boolean;
    }>("/model-operations/predict", body),
};
