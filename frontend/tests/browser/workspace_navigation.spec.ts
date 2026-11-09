import { expect, test, type Page } from "@playwright/test";

async function mockWorkspace(page: Page, semantic: boolean, mlops: boolean) {
  const requests: string[] = [];
  await page.addInitScript(() => sessionStorage.setItem("teoria-admin-token", "synthetic-browser-token"));
  await page.route("**/admin-api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    requests.push(path);
    let body: unknown = { items: [], total: 0, runs: [], next_cursor: null };
    if (path.endsWith("/deployment")) body = { semantic, mlops, formatid: false };
    else if (path.endsWith("/auth/session")) body = { actor: "fixture_operator", roles: ["metadata_admin"] };
    else if (path.endsWith("/model-operations/status")) body = { enabled: mlops };
    else if (path.endsWith("/model-operations/models")) body = {
      model_name: "demo", registered_models: [], items: [], serving: { status: "unavailable" }, synthetic: true,
    };
    else if (path.endsWith("/metadata/status")) body = { enabled: true, available: true, provider: "openmetadata" };
    else if (path.endsWith("/capabilities")) body = { capabilities: [] };
    else if (path.endsWith("/sources")) body = { sources: [] };
    else if (path.endsWith("/mappings")) body = { mappings: [] };
    else if (path.endsWith("/lineage")) body = { links: [] };
    else if (path.endsWith("/validation")) body = { status: "valid", diagnostic_count: 0, diagnostics: [] };
    else if (path.endsWith("/registry-release")) body = { status: "draft", version: null };
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });
  return requests;
}

test("home and navigation separate data, ontology and additional MLOps", async ({ page }, testInfo) => {
  await mockWorkspace(page, true, true);
  await page.goto("/admin/overview");
  const choices = page.getByRole("region", { name: "작업 공간 선택" });
  await expect(choices.getByRole("heading", { name: "데이터", exact: true })).toBeVisible();
  await expect(choices.getByRole("heading", { name: "Ontology" })).toBeVisible();
  await expect(choices.getByRole("heading", { name: "MLOps" })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("workspaces.png"), fullPage: true });
  await choices.getByRole("link", { name: "실행 계약·Capability" }).click();
  await expect(page).toHaveURL(/\/admin\/developer\/capabilities$/);
  await expect(page.getByText("등록된 Capability가 없습니다.")).toBeVisible();
  const location = page.getByRole("navigation", { name: "현재 위치" });
  await expect(location).toContainText("Ontology");
  await expect(page.getByRole("navigation", { name: "공통 운영" }).getByRole("link", { name: "파이프라인" })).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "탐색 메뉴 열기" }).click();
  await page.getByRole("navigation", { name: "공통 운영" }).getByRole("link", { name: "연결 및 설정" }).click();
  await expect(page.getByRole("heading", { name: "연결 및 설정" })).toBeVisible();
  await expect(page.getByRole("button", { name: "메뉴 닫기" })).not.toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false);
});

test("MLOps alone uses common operations without metadata requests", async ({ page }) => {
  const requests = await mockWorkspace(page, false, true);
  await page.goto("/admin/overview");
  await expect(page.getByRole("heading", { name: "MLOps" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Ontology" })).toHaveCount(0);
  await page.getByRole("navigation", { name: "공통 운영" }).getByRole("link", { name: "연결 및 설정" }).click();
  await expect(page.getByRole("heading", { name: "공통 파이프라인" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "메타데이터 연결" })).toHaveCount(0);
  expect(requests.some((path) => path.includes("/metadata/") || path.endsWith("/sources") || path.endsWith("/capabilities"))).toBe(false);
});
