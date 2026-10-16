import { postJson } from "./http_client";
import type { RegistryRelease } from "./registry";

export type ContextNotice = {
  bid_notice_id: string;
  notice_name: string | null;
  notice_organization_name: string | null;
  notice_published_at: string | null;
  bid_deadline_at: string | null;
  bid_status: string | null;
  work_type: string | null;
  estimated_price: string | number | null;
  detail_url: string | null;
};

export type ContextQueryResult = {
  query_type: "contract_amount" | "bid_notice_search";
  question: string;
  interpretation: {
    organization: {
      organization_code: string;
      organization_name: string;
      query: string;
    } | null;
    period_from: string;
    period_to: string;
    period_years?: number;
    period_defaulted?: boolean;
    filters?: Record<string, unknown>;
    concept: {
      stable_key: string;
      name: string;
      description: string;
      value_type: string;
      unit: string | null;
    };
  };
  execution_plan: {
    capability_id: string;
    inputs: Record<string, unknown>;
    selection_reason: string;
  };
  result: {
    status: "complete" | "partial";
    contract_event_count?: number;
    amount_available_contract_count?: number;
    contract_amount?: number;
    currency?: string;
    amount_basis?: string;
    amount_completeness?: string;
    total_items?: number;
    returned_items?: number;
    notices?: ContextNotice[];
  };
  policy: {
    decision: "allowed";
    actor: string;
    roles: string[];
    max_period_years: number;
    max_pages?: number;
    validated_period_years?: number;
    default_period_days?: number;
  };
  validation: {
    published_artifact_checksum: string;
    approved_capability_binding: boolean;
    runtime_registry: RegistryRelease | null;
    executed_pages: number;
    failed_pages: number[];
    data_freshness: string | null;
    data_freshness_status: "available" | "unavailable";
    metadata_quality_status: "available" | "unavailable";
  };
  evidence: Array<{
    type: string;
    locator: string;
    authority: string;
    confidence: string | number | null;
    last_verified_at: string | null;
  }>;
  warnings: string[];
};

export const contextApi = {
  contextQuery: (question: string) =>
    postJson<ContextQueryResult>("/context/execute", { question }),
};
