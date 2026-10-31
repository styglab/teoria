import { getJson } from "./http_client";

export type MetadataStatus = {
  enabled: boolean;
  available: boolean;
  provider: "openmetadata";
  base_url: string | null;
  database_service: string | null;
  reason: string | null;
};

export type MetadataEntity = {
  reference: {
    system: "openmetadata";
    entity_id: string;
    entity_type: string;
    fully_qualified_name: string | null;
    version: number | null;
  };
  name: string;
  display_name: string | null;
  description: string | null;
  owners: Array<Record<string, unknown>>;
  tags: Array<Record<string, unknown>>;
  domains: Array<Record<string, unknown>>;
};

export type MetadataPage = {
  items: MetadataEntity[];
  total: number;
  after: string | null;
  before: string | null;
};

export type AssetContextResult = {
  observed_at: string;
  technical: MetadataTableDetail;
  operations: {
    status: string;
    source: string;
    reason?: string;
    data?: Array<{
      pipeline_id: string;
      status: string | null;
      last_success_at: string | null;
      window_start: string | null;
      window_end: string | null;
      cursor_date: string | null;
      checkpoint_updated_at: string | null;
      error_code: string | null;
    }>;
  };
  business: {
    status: string;
    source: string;
    reason?: string;
    glossary_terms: string[];
    data?: {
      bindings: Array<{
        binding_id: string;
        namespace: string;
        stable_key: string;
        status: string;
        entity_type: string;
        fully_qualified_name: string;
      }>;
      suggestions: Array<{
        suggestion_id: string;
        suggestion_type: string;
        status: string;
        target_ref: string;
        reviewer: string | null;
        reviewed_at: string | null;
        application_status: string | null;
      }>;
      bindings_truncated: boolean;
      suggestions_truncated: boolean;
    };
  };
};

export type MetadataTableDetail = MetadataEntity & {
  database: Record<string, unknown> | null;
  database_schema: Record<string, unknown> | null;
  columns: Array<{
    name: string;
    displayName?: string;
    description?: string;
    dataType?: string;
    fullyQualifiedName?: string;
    tags?: Array<Record<string, unknown>>;
  }>;
  glossary_terms: Array<Record<string, unknown>>;
  test_suite: Record<string, unknown> | null;
};

export type MetadataTableSamples = {
  available: boolean;
  columns: string[];
  rows: unknown[][];
  stored_row_count: number;
  truncated: boolean;
  values_included: boolean;
  reason: string | null;
  scope: "stored_sample";
};

export type MetadataTableProfile = {
  available: boolean;
  table_metrics: Record<string, number | null>;
  column_metrics: Array<{
    name: string;
    metrics: Record<string, number | null>;
  }>;
  reason: string | null;
};

export type CatalogFilter = "all" | "description" | "owner" | "tags";
export type CatalogCounts = Record<CatalogFilter, number>;
export type CatalogSearch = {
  databaseSchema?: string;
  query?: string;
  missing?: CatalogFilter;
  sort?: "asc" | "desc";
  offset?: number;
  limit?: number;
};
function searchParams(options: CatalogSearch) {
  const params = new URLSearchParams();
  if (options.databaseSchema)
    params.set("database_schema", options.databaseSchema);
  if (options.query) params.set("q", options.query);
  if (options.missing) params.set("missing", options.missing);
  if (options.sort) params.set("sort", options.sort);
  if (options.offset !== undefined)
    params.set("offset", String(options.offset));
  if (options.limit !== undefined) params.set("limit", String(options.limit));
  return params;
}

export const metadataApi = {
  searchTables: (options: CatalogSearch, signal?: AbortSignal) =>
    getJson<MetadataPage>(
      `/metadata/table-search?${searchParams(options)}`,
      signal,
    ),
  tableCounts: (
    options: Pick<CatalogSearch, "databaseSchema" | "query">,
    signal?: AbortSignal,
  ) =>
    getJson<CatalogCounts>(
      `/metadata/table-search/counts?${searchParams(options)}`,
      signal,
    ),
  metadataStatus: () => getJson<MetadataStatus>("/metadata/status"),
  metadataTables: (options?: {
    databaseSchema?: string;
    after?: string;
    limit?: number;
  }) => {
    const params = new URLSearchParams();
    if (options?.databaseSchema)
      params.set("database_schema", options.databaseSchema);
    if (options?.after) params.set("after", options.after);
    if (options?.limit) params.set("limit", String(options.limit));
    return getJson<MetadataPage>(
      `/metadata/tables${params.size ? `?${params}` : ""}`,
    );
  },
  metadataSchemas: (after?: string) =>
    getJson<MetadataPage>(
      `/metadata/schemas?limit=100${after ? `&after=${encodeURIComponent(after)}` : ""}`,
    ),
  metadataTable: (fqn: string) =>
    getJson<MetadataTableDetail>(`/metadata/tables/${encodeURIComponent(fqn)}`),
  assetContext: (tableId: string) =>
    getJson<AssetContextResult>(
      `/metadata/asset-context/${encodeURIComponent(tableId)}`,
    ),
  metadataLineage: (tableId: string) =>
    getJson<Record<string, unknown>>(
      `/metadata/tables/${encodeURIComponent(tableId)}/lineage`,
    ),
  metadataTableSamples: (id: string, includeValues = false) =>
    getJson<MetadataTableSamples>(
      `/metadata/tables/${encodeURIComponent(id)}/sample-data?limit=10&include_values=${includeValues}`,
    ),
  metadataTableProfile: (id: string) =>
    getJson<MetadataTableProfile>(
      `/metadata/tables/${encodeURIComponent(id)}/profile`,
    ),
};
