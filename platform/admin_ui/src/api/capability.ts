import { getJson } from "./http_client";

export type CapabilitySummary = {
  id: string;
  name: string;
  description: string;
  kind?: string;
  exposure?: string;
  processor?: string | null;
  effects?: Record<string, unknown>;
  inputs: string[];
  steps: string[];
  returns: string[];
};

export type CapabilityCoverageItem = {
  capability_id: string;
  status: "covered" | "partial" | "unbound";
  capability_bound: boolean;
  inputs: { total: number; bound: number; unbound_fields: string[] };
  outputs: { total: number; bound: number; unbound_fields: string[] };
};

export type CapabilityCoverage = {
  summary: {
    capability_count: number;
    capability_bound_count: number;
    input_count: number;
    bound_input_count: number;
    output_count: number;
    bound_output_count: number;
    capability_coverage_rate: number | null;
  };
  items: CapabilityCoverageItem[];
};

export const capabilityApi = {
  capabilities: () =>
    getJson<{ capabilities: CapabilitySummary[] }>("/capabilities"),
  capabilityCoverage: () =>
    getJson<CapabilityCoverage>("/bindings/capability-coverage"),
};
