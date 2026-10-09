import "@testing-library/jest-dom/vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { adminApi } from "../../api/admin";
import { CapabilityStudio } from "./CapabilityStudio";

vi.spyOn(adminApi, "capabilityCoverage").mockResolvedValue({
  summary: { capability_count: 1, capability_bound_count: 1, input_count: 1, bound_input_count: 1, output_count: 1, bound_output_count: 0, capability_coverage_rate: 1 },
  items: [{ capability_id: "get_bid_notice", status: "partial", capability_bound: true, inputs: { total: 1, bound: 1, unbound_fields: [] }, outputs: { total: 1, bound: 0, unbound_fields: ["public_procurement.bid_notice"] } }],
});

test("shows one capability with readiness and next actions", async () => {
  render(<CapabilityStudio capabilities={[{ id: "get_bid_notice", name: "입찰공고 조회", description: "공고와 근거를 조회합니다.", inputs: ["notice_id"], steps: ["procurement.get_notice"], returns: ["public_procurement.bid_notice"] }]} sources={[{ id: "procurement", name: "조달 DB", description: null, type: "database", provider: null, items: 1, item_label: "operation" }]} mappings={[]} lineage={[]} validation={{ status: "valid", diagnostic_count: 0, diagnostics: [] }} />);
  expect(screen.getByRole("heading", { name: "입찰공고 조회" })).toBeInTheDocument();
  expect(screen.getByText("데이터 준비도")).toBeInTheDocument();
  await waitFor(() => expect(screen.getByText("2/3 Capability·입출력 의미 연결")).toBeInTheDocument());
  expect(screen.getByText("Bindings 열기")).toBeInTheDocument();
  expect(screen.queryByText("릴리스 준비 완료")).not.toBeInTheDocument();
});
