import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
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
  fireEvent.click(screen.getByRole("button", { name: "표준 매핑 비교" }));
  expect(await screen.findByText("조회 실패", { exact: true })).toBeTruthy();
  expect(screen.getByText("원문 값")).toBeTruthy();
});
