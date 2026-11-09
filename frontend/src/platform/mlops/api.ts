import { getJson, postJson } from "../../api/http_client";

import type { PipelinePage, RunDetail } from "../workflow_management/api";
export type {
  ModelRun,
  Pipeline,
  PipelinePage,
  RunDetail,
} from "../workflow_management/api";
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
  model_name: string | null;
  demo_model_name?: string;
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
  serving?: { status: string; model_name?: string; model_version?: number };
  synthetic?: boolean;
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
  services: (signal?: AbortSignal) =>
    getJson<{ items: InferenceService[] }>(
      "/model-operations/services",
      signal,
    ),
  status: (signal?: AbortSignal) =>
    getJson<{ enabled: boolean }>("/model-operations/status", signal),
  pipelines: (
    options?: {
      pipeline?: string;
      state?: string;
      page?: number;
      size?: number;
    },
    signal?: AbortSignal,
  ) => {
    const query = new URLSearchParams();
    if (options?.pipeline) query.set("pipeline_id", options.pipeline);
    if (options?.state) query.set("state", options.state);
    query.set("offset", String((options?.page || 0) * (options?.size || 25)));
    query.set("limit", String(options?.size || 25));
    return getJson<PipelinePage>(
      `/model-operations/pipelines?${query}`,
      signal,
    );
  },
  runDetail: (id: string, signal?: AbortSignal) =>
    getJson<RunDetail>(
      `/model-operations/runs/${encodeURIComponent(id)}`,
      signal,
    ),
  models: (
    options?: {
      model?: string;
      token?: string;
      versionToken?: string;
      q?: string;
    },
    signal?: AbortSignal,
  ) => {
    const query = new URLSearchParams();
    if (options?.q) query.set("q", options.q);
    if (options?.model) query.set("model_name", options.model);
    if (options?.token) query.set("page_token", options.token);
    if (options?.versionToken) query.set("version_token", options.versionToken);
    return getJson<ModelCatalog>(`/model-operations/models?${query}`, signal);
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
};
