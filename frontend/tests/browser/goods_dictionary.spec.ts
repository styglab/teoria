import { test, expect } from "@playwright/test";
import { mockCatalog } from "./catalog_fixtures";

const definition = {
  key: "memory_capacity",
  kind: "characteristic",
  preferred_name: "메모리 용량",
  definition: "서버 주기억장치의 저장 용량을 의미한다.",
  value_kind: "number",
  applicable_item_type_ids: ["server"],
  quantity_dimension: "information",
  canonical_unit: "GB",
  allowed_units: ["GB"],
  references: ["source:document#row1"],
};
const revision = "12345678-1234-1234-1234-123456789abc";

test("reviews an expression mapping with source impact, then approves a fixed application version", async ({
  page,
}, testInfo) => {
  await mockCatalog(page);
  let approved = false;
  let release: Record<string, unknown> | null = null;
  let approval: Record<string, unknown> | null = null;
  await page.route(
    "**/admin-api/v1/admin/goods/dictionary/**",
    async (route) => {
      const url = new URL(route.request().url());
      const path = url.pathname;
      let body: unknown = {};
      if (path.endsWith("/classifications"))
        body = {
          items: [{ classification_code: "4321150102", expression_count: 1 }],
          total: 1,
        };
      else if (path.endsWith("/catalog"))
        body = {
          items: [
            {
              mapping_id: revision,
              source_name: "메모리 용량",
              concept_id: revision,
              concept_key: definition.key,
              revision: 2,
              kind: "characteristic",
              status: approved ? "approved" : "draft",
              content: definition,
            },
          ],
          total: 1,
        };
      else if (path.endsWith("/audit"))
        body = {
          items: [
            {
              event_id: "event",
              action: approved ? "approve" : "proposed",
              actor: "fixture:reviewer",
              rationale: "원문 근거를 검토함",
              created_at: "2026-11-04T00:00:00Z",
            },
          ],
        };
      else if (path.endsWith("/related-context"))
        body = {
          documents: [
            {
              document_id: "server_doc",
              source_sha256: "d".repeat(64),
              operation_id: "source_run",
            },
          ],
        };
      else if (path.endsWith("/decisions")) {
        approved = true;
        body = {};
        expect(route.request().postDataJSON()).toEqual({
          action: "approve",
          rationale: "원문 근거와 적용 범위 및 단위를 확인했습니다.",
        });
      } else if (path.endsWith("/snapshot"))
        body = { schema_version: 2, checksum: "a".repeat(64), ontologies: [], mappings: [{}] };
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(body),
      });
    },
  );
  await page.route(
    "**/admin-api/v1/admin/specification-processing/application-standards**",
    async (route) => {
      const path = new URL(route.request().url()).pathname;
      let body: unknown;
      if (path.endsWith("/sources"))
        body = {
          items: [
            {
              run_id: "source_run",
              classification_code: "4321150102",
              status: "partial",
            },
          ],
          total: 1,
        };
      else if (path.endsWith("/sources/source_run"))
        body = { source_run_id: "source_run", ready: true, reason: null,
          definition_count: 1, rule_count: 1, standard_kind: "extraction_draft" };
      else if (route.request().method() === "POST") {
        approval = route.request().postDataJSON();
        release = {
          release_id: revision,
          name: "서버 적용 기준 v1",
          source_run_id: "source_run",
          classification_code: "4321150102",
          standard_kind: "extraction_draft",
          status: "approved",
          approved_by: "fixture:reviewer",
          rationale: "미해결 항목과 사전 정의를 함께 검토했습니다.",
          standard_ref: {
            uri: "s3://fixture/standard.json",
            sha256: "b".repeat(64),
          },
          dictionary_ref: {
            uri: "s3://fixture/dictionary.json",
            sha256: "c".repeat(64),
          },
          dictionary_checksum: "a".repeat(64),
        };
        body = release;
      } else body = { items: release ? [release] : [], total: release ? 1 : 0 };
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(body),
      });
    },
  );
  await page.goto(
    "/admin/domains/goods/dictionary?classification=4321150102&tab=mapping",
  );
  await expect(
    page.getByRole("heading", { name: "메모리 용량" }),
  ).toBeVisible();
  await expect(page.getByText(/server_doc/)).toBeVisible();
  await expect(
    page.getByRole("button", { name: "승인", exact: true }),
  ).toBeDisabled();
  await page
    .getByLabel("검토 사유")
    .fill("원문 근거와 적용 범위 및 단위를 확인했습니다.");
  await page.getByRole("button", { name: "승인", exact: true }).click();
  await expect(page.getByRole("button", { name: "사용 중단" })).toBeVisible();
  await page.screenshot({
    path: testInfo.outputPath("dictionary.png"),
    fullPage: true,
  });
  await page.goto("/admin/specifications/standards");
  await page.getByLabel("버전 이름").fill("서버 적용 기준 v1");
  await page.getByLabel("표준관리 실행").selectOption("source_run");
  await page
    .getByLabel("승인 근거")
    .fill("미해결 항목과 사전 정의를 함께 검토했습니다.");
  await page
    .getByRole("button", { name: "검토한 기준을 규격서 처리 기준으로 승인" })
    .click();
  expect(approval).toBeNull();
  await page.getByRole("checkbox").check();
  await page
    .getByRole("button", { name: "검토한 기준을 규격서 처리 기준으로 승인" })
    .click();
  await expect(
    page.getByText("서버 적용 기준 v1", { exact: true }),
  ).toBeVisible();
  expect(approval).toMatchObject({
    expected_dictionary_checksum: "a".repeat(64),
    source_run_id: "source_run",
  });
  expect(approval).not.toHaveProperty("actor");
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth > innerWidth,
    ),
  ).toBe(false);
});

test("product-first dictionary and legacy URLs keep domain and Ontology context", async ({
  page,
}) => {
  await mockCatalog(page);
  const queries: URLSearchParams[] = [];
  await page.route(
    "**/admin-api/v1/admin/goods/dictionary/**",
    async (route) => {
      const url = new URL(route.request().url());
      let body: unknown = { items: [], total: 0 };
      if (url.pathname.endsWith("/classifications"))
        body = {
          items: [{ classification_code: "4321150102", expression_count: 3 }],
          total: 1,
        };
      if (url.pathname.endsWith("/catalog")) queries.push(url.searchParams);
      await route.fulfill({ json: body });
    },
  );
  await page.goto("/admin/semantic-model/goods-dictionary");
  await expect(page).toHaveURL(/\/admin\/domains\/goods\/dictionary$/);
  expect(queries).toHaveLength(0);
  await page.getByLabel("등록된 품목").selectOption("4321150102");
  await expect
    .poll(() => queries.at(-1)?.get("classification"))
    .toBe("4321150102");
  await page.getByRole("button", { name: "검토 대기", exact: true }).click();
  await expect.poll(() => queries.at(-1)?.get("unresolved")).toBe("true");
  await page
    .getByRole("button", { name: "온톨로지 정의 조회", exact: true })
    .first()
    .click();
  await expect.poll(() => queries.at(-1)?.has("classification")).toBe(false);
  const scoped: URLSearchParams[] = [];
  await page.route("**/admin-api/v1/admin/bindings**", async (route) => {
    const url = new URL(route.request().url());
    scoped.push(url.searchParams);
    await route.fulfill({
      json: url.pathname.endsWith("/validation")
        ? {
            status: "valid",
            binding_count: 0,
            diagnostic_count: 0,
            diagnostics: [],
          }
        : { items: [] },
    });
  });
  await page.route(
    "**/admin-api/v1/admin/ontology-authoring/**",
    async (route) => route.fulfill({ json: { items: [] } }),
  );
  await page.goto(
    "/admin/semantic-model/bindings?namespace=teoria&binding_concept=12345678-1234-1234-1234-123456789abc",
  );
  await expect(
    page.getByRole("heading", { name: "데이터·용어 연결", exact: true }),
  ).toBeVisible();
  await expect(page).toHaveURL(/view=connections/);
  await expect
    .poll(() =>
      scoped
        .find((q) => q.has("ontology_concept_id"))
        ?.get("ontology_namespace"),
    )
    .toBe("teoria");
  await expect(
    page
      .getByRole("navigation", { name: "주요 메뉴" })
      .getByRole("link", { name: "의미 연결", exact: true }),
  ).toHaveCount(0);
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth > innerWidth,
    ),
  ).toBe(false);
});

test("mobile dictionary keeps management tabs and empty-library authoring reachable",async({page})=>{
  await mockCatalog(page);
  await page.route("**/admin-api/v1/admin/goods/dictionary/**",async route=>route.fulfill({json:{items:[],total:0}}));
  await page.setViewportSize({width:390,height:844});
  await page.goto('/admin/domains/goods/dictionary?classification=4321150102');
  const review=page.getByRole('button',{name:'검토 대기',exact:true});
  await review.scrollIntoViewIfNeeded();await expect(review).toBeVisible();await review.click();
  await page.getByRole('button',{name:'온톨로지 정의 조회',exact:true}).first().click();
  const author=page.getByRole('link',{name:'온톨로지에서 정의 작성·검토',exact:true});
  await author.scrollIntoViewIfNeeded();await expect(author).toBeVisible();
  await expect(author).toHaveAttribute('href','/admin/semantic-model/ontology');
  await expect(page.getByRole('button',{name:'새 정의 제안',exact:true})).toHaveCount(0);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)).toBe(false);
});
