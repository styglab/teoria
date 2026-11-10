import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { expect, it, vi } from "vitest";
import { RuntimeRequirements } from "./RuntimeRequirements";
import { processingApi } from "./api";

it("queries published requirements on demand and preserves value, scope and source evidence", async () => {
  const query = vi
    .spyOn(processingApi, "runtimeRequirements")
    .mockResolvedValue({
      objects: [
        {
          properties: {
            view_version: "2026.11.10.1",
            total: 1,
            deferred_count: 2,
          },
          semantic_observations: [
            {
              observation_id: "memory",
              concept_id: "capacity",
              operator: "eq",
              scope: "per_module",
              information_kind: "requirement",
              value: { decimal: "32", unit: "GB" },
              value_raw: "32",
              unit_raw: "GB",
              source: { attribute_id: "a1", evidence: { node_id: "ram_row" } },
            },
          ],
        },
      ],
      outcome: {
        concepts: { capacity: "메모리 모듈 용량" },
        subjects: { server: "서버", module: "RDIMM" },
        compositions: [{
          composition_id: "memory_composition", parent_ref: "server", child_ref: "module",
          inclusion_role: "required", quantity: { value: "2", unit_raw: "개", operator: "eq", scope: "서버 구성" },
          evidence: [{ quote: "RDIMM x 2개" }],
        }],
      },
    });
  render(
    <MemoryRouter>
      <RuntimeRequirements runId="memory_fixture" documentId="doc" />
    </MemoryRouter>,
  );
  expect(query).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: /게시 의미로 조회/ }));
  expect(await screen.findByText("메모리 모듈 용량")).toBeInTheDocument();
  expect(screen.getByText("모듈당")).toBeInTheDocument();
  expect(screen.getByText("eq 32 GB")).toBeInTheDocument();
  expect(screen.getByText(/ram_row/)).toBeInTheDocument();
  expect(screen.getByRole("region", { name: "승인된 구성 수량" })).toHaveTextContent("eq 2 개");
  expect(screen.getByText("서버")).toBeInTheDocument();
  expect(screen.queryByText(/64 GB/)).not.toBeInTheDocument();
  expect(query).toHaveBeenCalledWith(
    "memory_fixture",
    "doc",
    0,
    expect.any(AbortSignal),
  );
  expect(
    screen.queryByRole("button", { name: /승인/ }),
  ).not.toBeInTheDocument();
});

it("shows an unavailable publication as an error and retries without claiming an empty success", async () => {
  const query = vi
    .spyOn(processingApi, "runtimeRequirements")
    .mockRejectedValueOnce(
      new Error("이 문서는 게시된 조회 기준에 포함되지 않았습니다."),
    )
    .mockResolvedValue({ objects: [] });
  render(
    <MemoryRouter>
      <RuntimeRequirements runId="memory_fixture" documentId="doc" />
    </MemoryRouter>,
  );
  fireEvent.click(screen.getByRole("button", { name: /게시 의미로 조회/ }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "게시된 조회 기준에 포함되지 않았습니다",
  );
  fireEvent.click(screen.getByRole("button", { name: "다시 조회" }));
  await waitFor(() => expect(query).toHaveBeenCalledTimes(2));
});
