import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { adminApi } from "../../api/admin";
import { ContextConsole } from "./ContextConsole";

test("executes the representative context question and explains the plan", async () => {
  vi.spyOn(adminApi, "contextQuery").mockResolvedValue({
    query_type: "contract_amount", question: "질문", interpretation: { organization: { organization_code: "Z1", organization_name: "기관", query: "기관" }, period_from: "2022-01-01", period_to: "2026-10-07", period_years: 5, concept: { stable_key: "procurement.Contract.currentAmount", name: "계약금액", description: "계약 금액", value_type: "decimal", unit: "KRW" } },
    execution_plan: { capability_id: "search_public_procurement_contracts", inputs: {}, selection_reason: "approved_binding" }, result: { status: "complete", contract_event_count: 2, amount_available_contract_count: 2, contract_amount: 1000, currency: "KRW", amount_basis: "current_contract_amount", amount_completeness: "complete" }, policy: { decision: "allowed", actor: "user:test", roles: [], max_period_years: 10, max_pages: 100, validated_period_years: 5 }, validation: { published_artifact_checksum: "checksum", approved_capability_binding: true, runtime_registry: null, executed_pages: 1, failed_pages: [], data_freshness: "2026-10-06T17:05:33Z", data_freshness_status: "available", metadata_quality_status: "unavailable" }, evidence: [], warnings: [],
  });
  render(<ContextConsole />);
  fireEvent.click(screen.getByRole("button", { name: "질문 실행" }));
  await waitFor(() => expect(screen.getByText("1,000원")).toBeInTheDocument());
  expect(screen.getByText("search_public_procurement_contracts")).toBeInTheDocument();
});
