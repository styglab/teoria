import { test, expect } from "@playwright/test";
import { mockCatalog } from "./catalog_fixtures";

test("reprocesses registered originals using an approved fixed standard", async ({ page }) => {
  await mockCatalog(page);
  const original = { document_id: "original_doc", filename: "원본 규격서.pdf", source_uri: "s3://fixture/original.pdf", sha256: "c".repeat(64) };
  const release = {
    release_id: "00000000-0000-4000-8000-000000000001", name: "검토한 적용 기준", status: "approved",
    source_run_id: "previous_run", classification_code: null, standard_kind: "extraction_draft",
    standard_ref: { uri: "s3://fixture/standard.json", sha256: "a".repeat(64) },
    dictionary_ref: { uri: "s3://fixture/dictionary.json", sha256: "b".repeat(64) },
    approved_by: "fixture:reviewer",
  };
  let manifest: Record<string, unknown> | null = null;
  await page.route("**/admin-api/v1/admin/specification-processing/**", async route => {
    const path = new URL(route.request().url()).pathname;
    let body: unknown = { items: [], total: 0 };
    if (path.endsWith("/status")) body = { uploads_enabled: false, results_enabled: true };
    else if (path.endsWith("/inputs")) body = { source_run_id: "previous_run", documents: [original], classification_code: null };
    else if (path.endsWith(`/application-standards/${release.release_id}`)) body = release;
    else if (path.endsWith("/operations")) body = { days: 7, runs: {}, documents: {}, quality_evaluation: "not_attached" };
    await route.fulfill({ json: body });
  });
  await page.route("**/admin-api/v1/admin/workflows/**", async route => {
    if (route.request().method() === "POST") {
      manifest = route.request().postDataJSON().manifest;
      await route.fulfill({ json: { flow_run_id: "new_flow", name: "new_run" } });
    } else await route.fulfill({ json: { enabled: true, items: [], runs: [] } });
  });
  await page.goto(`/admin/specifications?new=1&reprocess=previous_run&release=${release.release_id}`);
  await expect(page.getByText(original.filename, { exact: true })).toBeVisible();
  await expect(page.getByLabel("승인된 처리 기준")).toHaveValue(release.release_id);
  await page.getByRole("button", { name: "문서 처리 실행", exact: true }).click();
  await expect(page.getByRole("link", { name: "처리 결과 확인", exact: true })).toBeVisible();
  expect(manifest).toMatchObject({ mode: "document_processing", documents: [original], application_release_id: release.release_id,
    standard: release.standard_ref, dictionary_standard: release.dictionary_ref,
    dictionary_auto_approve: false, dictionary_meaning_auto_approve: false });
  expect(manifest).not.toHaveProperty("actor");
});
