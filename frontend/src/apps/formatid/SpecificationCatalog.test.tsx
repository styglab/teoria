import { clearCatalogCache } from "./catalog_queries";
import { afterEach, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { documentCatalogApi, type DocumentResult } from "./api";
import {
  SpecificationCatalog,
  comparisonRows,
  CatalogDocumentView,
} from "./SpecificationCatalog";
afterEach(() => {
  cleanup();
  clearCatalogCache();
  vi.restoreAllMocks();
});
const doc = {
  catalog_id: "a",
  filename: "서버 규격서.pdf",
  classification_code: "4321150102",
  notice_number: null,
  source_sha256: "a".repeat(64),
  run_id: "good",
  document_id: "d",
  status: "extracted",
  latest_status: "failed",
  latest_run_status: "failed",
  latest_run_id: "bad",
  latest_started_at: "2026-10-31",
  started_at: "2026-10-30",
  attempt_count: 2,
  result_available: true,
  result_summary: {},
};
function result(
  id = "a",
  scope = "per_cpu",
  checksum = "same",
): DocumentResult {
  return {
    document: { ...doc, catalog_id: id },
    result: {
      document_id: "d",
      result_kind: "profile",
      extracted: {
        documents: [
          {
            document_id: "d",
            entities: [{ id: "cpu", name: "CPU" }],
            attributes: [],
          },
        ],
      },
      normalization: {
        artifact_kind: "goods_normalized_observations",
        profile_revision_id: "p",
        package_checksum: "pkg",
        ontology: { version_id: "v", checksum },
        documents: [
          {
            document_id: "d",
            entities: [{ source_entity_id: "cpu", concept_id: "processor" }],
          },
        ],
        attributes: [
          {
            document_id: "d",
            status: "applied",
            facts: [
              {
                property_id: "cores",
                subject_ids: ["cpu"],
                role: "required",
                semantic_scope: scope,
                value: { decimal: "16", unit: "core" },
              },
            ],
          },
        ],
      },
    },
  };
}
it("loads metadata pages and sends classification and search filters to the server", async () => {
  vi.spyOn(documentCatalogApi, "classifications").mockResolvedValue({
    items: [
      { classification_code: "4321150102", documents: 300, results: 250 },
    ],
    total: 1,
    documents: 300,
  });
  const list = vi
    .spyOn(documentCatalogApi, "documents")
    .mockResolvedValue({ items: [doc], total: 300 });
  const load = vi.spyOn(documentCatalogApi, "result");
  render(
    <MemoryRouter>
      <SpecificationCatalog />
    </MemoryRouter>,
  );
  expect(await screen.findByRole("link", { name: doc.filename })).toBeTruthy();
  expect(screen.getByText("이전 정상 결과 유지")).toBeTruthy();
  expect(load).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "4321150102 300건" }));
  await waitFor(() =>
    expect(list.mock.calls.at(-1)?.[0].get("classification")).toBe(
      "4321150102",
    ),
  );
  fireEvent.change(screen.getByLabelText("파일명·공고번호"), {
    target: { value: "CPU" },
  });
  fireEvent.click(screen.getByRole("button", { name: "검색" }));
  await waitFor(() =>
    expect(list.mock.calls.at(-1)?.[0].get("query")).toBe("CPU"),
  );
  await waitFor(() =>
    expect(
      screen
        .getByRole("button", { name: "다음 페이지" })
        .hasAttribute("disabled"),
    ).toBe(false),
  );
  fireEvent.click(screen.getByRole("button", { name: "다음 페이지" }));
  await waitFor(() =>
    expect(list.mock.calls.at(-1)?.[0].get("offset")).toBe("25"),
  );
});
it("preserves source failure status while displaying an earlier available document result and lazy history", async () => {
  vi.spyOn(documentCatalogApi, "result").mockResolvedValue(result());
  const history = vi
    .spyOn(documentCatalogApi, "history")
    .mockResolvedValue({ items: [], total: 0 });
  render(
    <MemoryRouter>
      <CatalogDocumentView id="a" />
    </MemoryRouter>,
  );
  expect(
    await screen.findByRole("heading", { name: doc.filename }),
  ).toBeTruthy();
  expect(screen.getByText(/최근 처리: 실패/)).toBeTruthy();
  expect(history).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "처리 이력 2회" }));
  await waitFor(() =>
    expect(history).toHaveBeenCalledWith("a", 0, expect.any(AbortSignal)),
  );
});
it("aligns only matching authority, concept, scope and units and retains repeated target values", () => {
  const one = result();
  const two = result("b");
  expect(comparisonRows([one, two])).toHaveLength(1);
  expect(comparisonRows([one, result("b", "whole_system")])).toHaveLength(2);
  expect(
    comparisonRows([one, result("b", "per_cpu", "different")]),
  ).toHaveLength(2);
  const facts = two.result!.normalization!.attributes as Array<{
    facts: unknown[];
  }>;
  facts[0].facts.push(facts[0].facts[0]);
  expect(comparisonRows([one, two])[0].cells[1]).toHaveLength(2);
});
it("never equates local draft identifiers without a verified standard digest", () => {
  const one = result();
  const two = result("b");
  for (const item of [one, two]) {
    item.result!.result_kind = "extraction_standard";
    delete item.result!.normalization!.standard_ref;
  }
  expect(comparisonRows([one, two])).toHaveLength(2);
});
it("resolves profile subject observation IDs and keeps unknown scopes separate", () => {
  const one = result(),
    two = result("b");
  for (const item of [one, two]) {
    const norm = item.result!.normalization!;
    const mappings = norm.documents as Array<{
      entities: Record<string, unknown>[];
    }>;
    mappings[0].entities[0].observation_id = "observation";
    const rows = norm.attributes as Array<{ facts: Record<string, unknown>[] }>;
    delete rows[0].facts[0].subject_ids;
    rows[0].facts[0].subject_observation_ids = ["observation"];
  }
  expect(comparisonRows([one, two])).toHaveLength(1);
  const rows = two.result!.normalization!.attributes as Array<{
    facts: Record<string, unknown>[];
  }>;
  rows[0].facts[0].semantic_scope = "unknown";
  expect(comparisonRows([one, two])).toHaveLength(2);
});
it("explains missing comparison cells without equating incompatible values", async () => {
  const { comparisonGap } = await import("./document_comparison");
  const one = result();
  const scoped = comparisonRows([one, result("b", "whole_system")]);
  expect(
    comparisonGap(scoped.find((row) => row.cells[0].length)!, 1, scoped),
  ).toBe("적용 범위 다름");
  const versions = comparisonRows([one, result("b", "per_cpu", "new")]);
  expect(
    comparisonGap(versions.find((row) => row.cells[0].length)!, 1, versions),
  ).toBe("적용 표준 다름");
  const two = result("b");
  const attributes = two.result!.normalization!.attributes as Array<{
    facts: Array<{ value: { unit: string } }>;
  }>;
  attributes[0].facts[0].value.unit = "thread";
  const units = comparisonRows([one, two]);
  expect(
    comparisonGap(units.find((row) => row.cells[0].length)!, 1, units),
  ).toBe("단위 다름");
});
it("keeps a classification error separate from a successful document list", async () => {
  vi.spyOn(documentCatalogApi, "classifications").mockRejectedValue(
    new Error("offline"),
  );
  vi.spyOn(documentCatalogApi, "documents").mockResolvedValue({
    items: [doc],
    total: 1,
  });
  render(
    <MemoryRouter>
      <SpecificationCatalog />
    </MemoryRouter>,
  );
  expect(await screen.findByRole("link", { name: doc.filename })).toBeTruthy();
  expect(screen.getByRole("alert").textContent).toContain("분류 목록");
  fireEvent.click(screen.getByRole("button", { name: "새로고침" }));
  await waitFor(() =>
    expect(screen.getByRole("alert").textContent).toContain("분류 목록"),
  );
});
