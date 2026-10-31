import { type Page } from "@playwright/test";
const source = { sha256: "a".repeat(64), original_name: "GPU 서버 규격서.pdf" };
export const document = {
  catalog_id: "server_a",
  filename: "GPU 서버 규격서.pdf",
  classification_code: "4321150102",
  notice_number: "fixture_notice",
  source_sha256: source.sha256,
  run_id: "fixture_run",
  document_id: "document_a",
  status: "extracted",
  latest_status: "extracted",
  latest_run_status: "completed",
  latest_run_id: "fixture_run",
  latest_started_at: "2026-10-31T09:00:00Z",
  started_at: "2026-10-31T09:00:00Z",
  attempt_count: 2,
  result_available: true,
  result_summary: {},
};
export const second = {
  ...document,
  catalog_id: "server_b",
  filename: "연산 서버 규격서.pdf",
  document_id: "document_b",
};
export function fixtureResult(id: string, large = false) {
  const doc = id === "server_b" ? second : document;
  const entities = large
    ? Array.from({ length: 1000 }, (_, i) => ({
        id: `entity_${i}`,
        name: `구성품 ${i}`,
        kind: "equipment",
        evidence: [{ node_id: "n1" }],
      }))
    : [
        {
          id: "server",
          name: "GPU 서버",
          kind: "equipment",
          evidence: [{ node_id: "n1" }],
        },
        {
          id: "cpu",
          name: "CPU",
          kind: "equipment",
          evidence: [{ node_id: "n1" }],
        },
      ];
  const subject = large ? "entity_0" : "cpu";
  return {
    document: doc,
    result: {
      document_id: doc.document_id,
      result_kind: "profile",
      extracted: {
        documents: [
          {
            document_id: doc.document_id,
            source,
            entities,
            inventory_ids: [entities[0].id],
            relations: large
              ? []
              : [
                  {
                    id: "component",
                    source_id: "cpu",
                    target_id: "server",
                    kind: "component_of",
                    basis: "explicit",
                    evidence: [{ node_id: "n1" }],
                  },
                ],
            attributes: [
              {
                id: "cores",
                subject_ids: [subject],
                property_raw: "코어 수",
                property_key: "core_count",
                value_raw: "16",
                unit_raw: "core",
                operator: "gte",
                operator_raw: "이상",
                semantic_scope: "per_processor",
                evidence: { node_id: "n1" },
              },
            ],
            parsed_document: {
              nodes: [
                {
                  node_id: "n1",
                  kind: "paragraph",
                  text: "GPU 서버의 CPU는 프로세서당 16코어 이상이어야 한다.",
                  page: 2,
                },
              ],
            },
            extraction_status: "extracted",
          },
        ],
        unavailable_documents: [],
      },
      normalization: {
        artifact_kind: "goods_normalized_observations",
        standard_version: "server_profile_v1",
        profile_revision_id: "fixture_profile",
        package_checksum: "fixture_package",
        ontology: { version_id: "goods_v1", checksum: "fixture_ontology" },
        documents: [
          {
            document_id: doc.document_id,
            entities: [
              {
                source_entity_id: subject,
                observation_id: "cpu_observation",
                concept_id: "processor",
              },
            ],
          },
        ],
        attributes: [
          {
            document_id: doc.document_id,
            attribute_id: "cores",
            status: "applied",
            facts: [
              {
                property_id: "cpu_cores",
                property_label: "프로세서당 코어 수",
                subject_ids: [subject],
                operator: "gte",
                operator_raw: "이상",
                role: "requirement_candidate",
                semantic_scope:
                  id === "server_b" ? "whole_system" : "per_processor",
                value: { decimal: "16", unit: "core" },
                qualifiers_raw: ["장착된 각 프로세서 기준"],
              },
            ],
          },
        ],
      },
    },
  };
}
export async function mockCatalog(
  page: Page,
  { large = false }: { large?: boolean } = {},
) {
  await page.addInitScript(() =>
    sessionStorage.setItem("teoria-admin-token", "synthetic-browser-token"),
  );
  const unexpected: string[] = [];
  await page.route("**/admin-api/**", async (route) => {
    const url = new URL(route.request().url());
    let body: unknown;
    const path = url.pathname;
    if (path.endsWith("/deployment"))
      body = { mlops: true, semantic: true, formatid: true };
    else if (path.endsWith("/auth/session"))
      body = { actor: "fixture_operator", roles: ["metadata_admin"] };
    else if (path.endsWith("/model-operations/status"))
      body = { enabled: false };
    else if (path.endsWith("/metadata/status"))
      body = {
        enabled: true,
        available: true,
        provider: "openmetadata",
        base_url: null,
        database_service: "fixture",
        reason: null,
      };
    else if (path.endsWith("/metadata/table-search/counts"))
      body = { all: 0, description: 0, owner: 0, tags: 0 };
    else if (
      path.endsWith("/metadata/table-search") ||
      path.endsWith("/metadata/schemas")
    )
      body = { items: [], total: 0 };
    else if (path.endsWith("/catalog/classifications"))
      body = {
        items: [
          { classification_code: "4321150102", documents: 240, results: 200 },
          { classification_code: null, documents: 8, results: 0 },
        ],
        total: 2,
        documents: 248,
      };
    else if (path.endsWith("/catalog/documents"))
      body = { items: [document, second], total: 240 };
    else if (path.endsWith("/history"))
      body = {
        items: [
          {
            run_id: "fixture_run",
            status: "extracted",
            started_at: document.started_at,
          },
        ],
        total: 1,
      };
    else if (path.endsWith("/server_a/result"))
      body = fixtureResult("server_a", large);
    else if (path.endsWith("/server_b/result"))
      body = fixtureResult("server_b");
    else {
      unexpected.push(path);
      body = { detail: "unmocked_fixture_endpoint" };
    }
    await route.fulfill({
      status: unexpected.includes(path) ? 501 : 200,
      contentType: "application/json",
      body: JSON.stringify(body),
    });
  });
  return unexpected;
}
