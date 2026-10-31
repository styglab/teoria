import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { MemoryRouter, useLocation } from "react-router-dom";
import { SpecificationWorkspace } from "./SpecificationWorkspace";
import { processingApi } from "../../api/specification_processing";
import { workflowsApi } from "../../api/workflows";
import * as access from "../access/AdminAccess";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});
function setup() {
  vi.spyOn(access, "useAdminAccess").mockReturnValue({
    principal: { actor: "operator", roles: ["metadata_admin"] },
    requestLogin: vi.fn(),
  });
  vi.spyOn(processingApi, "status").mockResolvedValue({
    uploads_enabled: true,
    results_enabled: true,
  });
  vi.spyOn(processingApi, "runs").mockResolvedValue({ items: [], total: 0 });
}
it("uploads selected files and submits a typed manual run without auto approval", async () => {
  setup();
  const upload = vi.spyOn(processingApi, "upload").mockResolvedValue({
    document_id: "doc_1",
    filename: "sample.pdf",
    source_uri: "file:///app/specification_inputs/doc_1.pdf",
    sha256: "a".repeat(64),
  });
  const run = vi
    .spyOn(workflowsApi, "run")
    .mockResolvedValue({ flow_run_id: "flow-id", name: "processing-run" });
  render(
    <MemoryRouter initialEntries={["/?new=1"]}>
      <SpecificationWorkspace />
    </MemoryRouter>,
  );
  const input = await screen.findByLabelText(/규격서 파일/);
  const file = new File(["synthetic pdf"], "sample.pdf", {
    type: "application/pdf",
  });
  fireEvent.change(input, { target: { files: [file] } });
  fireEvent.submit(
    screen.getByRole("button", { name: "문서 처리 실행" }).closest("form")!,
  );
  await waitFor(() =>
    expect(run).toHaveBeenCalledWith(
      "specification-standard-management",
      expect.stringMatching(/^[a-f0-9-]{36}$/),
      expect.objectContaining({
        manifest: expect.objectContaining({
          dictionary_auto_approve: false,
          documents: [expect.objectContaining({ document_id: "doc_1" })],
        }),
      }),
    ),
  );
  expect(upload).toHaveBeenCalledWith(file);
  expect(
    await screen.findByRole("link", { name: "실행 상태 확인" }),
  ).toBeTruthy();
});
it("loads extracted properties and opens checksum-verified source evidence", async () => {
  setup();
  vi.spyOn(processingApi, "detail").mockResolvedValue({
    run: {
      run_id: "sample_run",
      mode: "standard_management",
      status: "completed",
      classification_code: null,
      summary: {},
      started_at: "2026-10-28",
      finished_at: null,
      error_code: null,
    },
    documents: [],
    artifacts: [
      {
        key: "extracted.json",
        uri: "file:///app/specification_artifacts/extracted.json",
        sha256: "a".repeat(64),
        size_bytes: 100,
        media_type: "application/json",
      },
    ],
  });
  const artifact = vi.spyOn(processingApi, "artifact").mockResolvedValue({
    documents: [
      {
        document_id: "doc_1",
        parsed_document: {
          nodes: [{ node_id: "n1", text: "메모리 용량 32GB", page: 1 }],
        },
        attributes: [
          {
            property_raw: "메모리",
            property_key: "memory",
            value_raw: "32GB",
            subject_ids: ["item_1"],
            evidence: { source_node_ids: ["n1"] },
          },
        ],
        entities: [{ id: "item_1", name: "서버", kind: "equipment" }],
        relations: [],
      },
    ],
  });
  render(
    <MemoryRouter initialEntries={["/?run=sample_run"]}>
      <SpecificationWorkspace />
    </MemoryRouter>,
  );
  expect(await screen.findByText("32GB", { exact: true })).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "원문 근거 n1" }));
  expect(
    screen.getByText("메모리 용량 32GB").closest("article")?.className,
  ).toContain("is-selected");
  expect(artifact).toHaveBeenCalledWith("sample_run", "extracted.json");
});

it("keeps document observations visible when the separate normalization request fails", async () => {
  setup();
  vi.spyOn(processingApi, "detail").mockResolvedValue({
    run: {
      run_id: "r1",
      mode: "document_processing",
      status: "completed",
      classification_code: null,
      summary: {},
      started_at: "2026-10-28",
      finished_at: null,
      error_code: null,
    },
    documents: [],
    artifacts: ["extracted.json", "normalized.json"].map((key) => ({
      key,
      uri: `file:///app/specification_artifacts/${key}`,
      sha256: "a".repeat(64),
      size_bytes: 100,
      media_type: "application/json",
    })),
  });
  vi.spyOn(processingApi, "artifact").mockImplementation(async (_run, key) => {
    if (key === "normalized.json") throw new Error("storage unavailable");
    return {
      documents: [
        {
          document_id: "doc_1",
          entities: [{ id: "root", name: "원문 장비" }],
          attributes: [
            {
              id: "a1",
              subject_ids: ["root"],
              property_raw: "원문 속성",
              value_raw: "원문 값",
            },
          ],
        },
      ],
    };
  });
  render(
    <MemoryRouter initialEntries={["/?run=r1"]}>
      <SpecificationWorkspace />
    </MemoryRouter>,
  );
  expect(await screen.findByText("원문 값")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "표준 적용 결과" }));
  expect(await screen.findByText("조회 실패", { exact: true })).toBeTruthy();
  expect(screen.getByText("원문 값")).toBeTruthy();
});

function LocationProbe() {
  return <output aria-label="현재 URL">{useLocation().search}</output>;
}
function mockDocumentResults() {
  setup();
  vi.spyOn(processingApi, "detail").mockResolvedValue({
    run: {
      run_id: "results",
      mode: "standard_management",
      status: "completed",
      classification_code: null,
      summary: {},
      started_at: "2026-10-31",
      finished_at: null,
      error_code: null,
    },
    documents: ["d1", "d2"].map((id) => ({
      document_id: id,
      status: "extracted",
      source_sha256: "a".repeat(64),
      result_summary: {},
    })),
    artifacts: ["extracted.json", "meaning_candidates.json"].map((key) => ({
      key,
      uri: `file:///app/${key}`,
      sha256: "a".repeat(64),
      size_bytes: 100,
      media_type: "application/json",
    })),
  });
  return vi.spyOn(processingApi, "artifact").mockResolvedValue({
    documents: [
      {
        document_id: "d1",
        entities: [{ id: "one", name: "첫 번째 규격서 장비" }],
        attributes: [],
        relations: [],
      },
      {
        document_id: "d2",
        entities: [{ id: "two", name: "두 번째 규격서 장비" }],
        attributes: [],
        relations: [],
      },
    ],
  });
}
it("opens legacy review links as results without fetching proposals or providing approval controls", async () => {
  const artifact = mockDocumentResults();
  const write = vi.spyOn(workflowsApi, "run");
  render(
    <MemoryRouter
      initialEntries={["/?run=results&tab=review&review_revision=old"]}
    >
      <SpecificationWorkspace />
      <LocationProbe />
    </MemoryRouter>,
  );
  expect(
    await screen.findByRole("heading", { name: "첫 번째 규격서 장비" }),
  ).toBeTruthy();
  expect(screen.getByRole("button", { name: "규격서 결과" })).toBeTruthy();
  expect(
    screen.queryByRole("button", {
      name: /표준 후보 검토|프로파일 승인|검토 요청|Draft 생성/,
    }),
  ).toBeNull();
  await waitFor(() =>
    expect(screen.getByLabelText("현재 URL").textContent).not.toContain(
      "review",
    ),
  );
  expect(artifact).toHaveBeenCalledWith("results", "extracted.json");
  expect(artifact).not.toHaveBeenCalledWith(
    "results",
    "meaning_candidates.json",
  );
  expect(write).not.toHaveBeenCalled();
});
it("opens the selected document from its result row and preserves its selection in the URL", async () => {
  mockDocumentResults();
  render(
    <MemoryRouter initialEntries={["/?run=results&tab=documents"]}>
      <SpecificationWorkspace />
      <LocationProbe />
    </MemoryRouter>,
  );
  fireEvent.click(await screen.findByRole("button", { name: "d2" }));
  expect(
    await screen.findByRole("heading", { name: "두 번째 규격서 장비" }),
  ).toBeTruthy();
  expect(screen.getByLabelText("현재 URL").textContent).toContain(
    "document=d2",
  );
  expect(
    (screen.getByLabelText("규격서 선택") as HTMLSelectElement).value,
  ).toBe("1");
});
