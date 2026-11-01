import { test, expect } from "@playwright/test";
import { mockCatalog, document } from "./catalog_fixtures";

test.beforeEach(async ({ page }) => {
  await mockCatalog(page);
});
test("desktop list, focused input and opened select", async ({ page }) => {
  await page.goto("/admin/specifications");
  await expect(
    page.getByRole("link", { name: document.filename, exact: true }),
  ).toBeVisible();
  await page.getByLabel("파일명·공고번호").click();
  await expect(page).toHaveScreenshot("catalog-input.png");
  await page.getByLabel("최근 처리 상태").click();
  await expect(page).toHaveScreenshot("catalog-select.png");
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/status=running/);
  expect(
    await page
      .getByLabel("파일명·공고번호")
      .evaluate((e) => getComputedStyle(e).outlineStyle),
  ).toBe("none");
});
test("mobile cards and collapsed filters", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/admin/specifications");
  await expect(
    page.getByRole("link", { name: document.filename, exact: true }),
  ).toBeVisible();
  await expect(page.getByLabel("규격서 카드 목록")).toBeVisible();
  await expect(page.getByLabel("파일명·공고번호")).not.toBeVisible();
  await expect(page).toHaveScreenshot("catalog-mobile.png");
  await page.getByText("검색·필터", { exact: true }).click();
  await expect(page.getByLabel("파일명·공고번호")).toBeVisible();
  expect(
    await page.evaluate(
      () => window.document.documentElement.scrollWidth > innerWidth,
    ),
  ).toBe(false);
});
test("result name, tree, source and comparison reasons", async ({ page }) => {
  await page.goto("/admin/specifications?document=server_a");
  await expect(
    page.getByRole("heading", { name: document.filename, exact: true }),
  ).toBeVisible();
  await page.getByRole("treeitem", { name: /CPU/ }).click();
  await expect(
    page.getByText("코어 수", { exact: true }).first(),
  ).toBeVisible();
  await expect(page).toHaveScreenshot("document-result.png");
  await page.getByRole("treeitem", { name: /CPU/ }).click();
  await page
    .getByRole("region", { name: "분석 대상 상세" })
    .getByRole("button", { name: "원문 보기", exact: true })
    .first()
    .click();
  await expect(
    page.getByRole("region", { name: "선택한 원문 근거" }),
  ).toBeVisible();
  await expect(page).toHaveScreenshot("document-source.png");
  await page.goto("/admin/specifications?compare=server_a,server_b");
  await expect(page.getByText("적용 범위 다름").first()).toBeVisible();
  await expect(page).toHaveScreenshot("document-compare.png");
});
test("keeps old rows during a failed request, retries and restores selection on return", async ({
  page,
}) => {
  await page.goto("/admin/specifications");
  await page
    .getByRole("link", { name: document.filename, exact: true })
    .waitFor();
  await page.getByLabel(`${document.filename} 비교 선택`).check();
  await page
    .getByRole("link", { name: document.filename, exact: true })
    .click();
  await page
    .getByRole("heading", { name: document.filename, exact: true })
    .waitFor();
  await page.getByRole("link", { name: "← 규격서 목록" }).click();
  await expect(page.getByLabel(`${document.filename} 비교 선택`)).toBeChecked();
  let fail = true;
  await page.route("**/catalog/documents?**", async (route) => {
    if (fail)
      await route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({ detail: "processing_results_unavailable" }),
      });
    else await route.fallback();
  });
  await page.getByLabel("파일명·공고번호").fill("CPU");
  await page.getByRole("button", { name: "검색", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("문서 목록");
  await expect(
    page.getByRole("link", { name: document.filename, exact: true }),
  ).toBeVisible();
  fail = false;
  await page.getByRole("button", { name: "문서 다시 조회" }).click();
  await expect(page.getByRole("alert")).toHaveCount(0);
});
test("browses one thousand targets and searches without rebuilding every attribute count", async ({
  page,
}) => {
  await mockCatalog(page, { large: true });
  const started = Date.now();
  await page.goto("/admin/specifications?document=server_a");
  await expect(page.getByRole("treeitem")).toHaveCount(1000);
  const ready = Date.now() - started;
  const searchStarted = Date.now();
  await page.getByLabel("분석 대상 검색").fill("구성품 999");
  await expect(page.getByRole("treeitem")).toHaveCount(1);
  await page.getByRole("treeitem").click();
  console.info(
    JSON.stringify({
      targets: 1000,
      load_ms: ready,
      search_and_select_ms: Date.now() - searchStarted,
    }),
  );
  test.info().annotations.push({
    type: "1000-target-load-ms",
    description: String(ready),
  });
});

test("restores the list scroll position after document navigation", async ({
  page,
}) => {
  const items = Array.from({ length: 25 }, (_, index) => ({
    ...document,
    catalog_id: `extra_${index}`,
    filename: `규격서 ${index}.pdf`,
  }));
  await page.route("**/catalog/documents?**", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ items, total: 240 }),
    }),
  );
  const { fixtureResult } = await import("./catalog_fixtures");
  await page.route("**/catalog/documents/extra_15/result", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        ...fixtureResult("server_a"),
        document: items[15],
      }),
    }),
  );
  await page.goto("/admin/specifications");
  const link = page.getByRole("link", { name: "규격서 15.pdf", exact: true });
  await link.scrollIntoViewIfNeeded();
  const position = await page
    .locator(".spec-catalog")
    .evaluate((e) => e.scrollTop);
  expect(position).toBeGreaterThan(100);
  await link.click();
  await page
    .getByRole("heading", { name: "규격서 15.pdf", exact: true })
    .waitFor();
  await page.getByRole("link", { name: "← 규격서 목록" }).click();
  await expect
    .poll(() => page.locator(".spec-catalog").evaluate((e) => e.scrollTop))
    .toBeCloseTo(position, 0);
});

test("mobile target to requirement to source navigation", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/admin/specifications?document=server_a");
  await page.getByRole("treeitem", { name: /CPU/ }).click();
  await expect(
    page.getByRole("region", { name: "분석 대상 상세" }),
  ).toBeVisible();
  await expect(page).toHaveScreenshot("document-mobile.png");
  await page
    .getByRole("region", { name: "분석 대상 상세" })
    .getByRole("button", { name: "원문 보기", exact: true })
    .first()
    .click();
  await expect(
    page.getByRole("region", { name: "선택한 원문 근거" }),
  ).toBeVisible();
  await expect(page).toHaveScreenshot("document-source-mobile.png");
  await page.getByRole("button", { name: "근거 닫기", exact: true }).click();
  await page
    .getByRole("button", { name: "← 분석 대상 목록", exact: true })
    .click();
  await expect(page.getByRole("treeitem", { name: /CPU/ })).toBeVisible();
  expect(
    await page.evaluate(
      () => window.document.documentElement.scrollWidth > innerWidth,
    ),
  ).toBe(false);
});

test("shared search field has one focus frame on the data catalog", async ({
  page,
}) => {
  await page.goto("/admin/data-catalog");
  const search = page.getByRole("textbox", { name: "전체 자산 검색" });
  await search.click();
  expect(await search.evaluate((e) => getComputedStyle(e).borderTopWidth)).toBe(
    "0px",
  );
  expect(await search.evaluate((e) => getComputedStyle(e).boxShadow)).toBe(
    "none",
  );
  expect(
    await search.evaluate(
      (e) => getComputedStyle(e.parentElement!).borderTopWidth,
    ),
  ).toBe("1px");
  await expect(page.getByText("0개", { exact: true }).first()).toBeVisible();
  await expect(page).toHaveScreenshot("metadata-search-focus.png");
});
