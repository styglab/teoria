import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { BindingManager } from "./BindingManager";

describe("BindingManager", () => {
  afterEach(() => vi.restoreAllMocks());

  it("shows stable ontology concepts and reviews draft bindings", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.includes("/ontology-authoring/")) return response({ items: [{ concept_id: "concept-1", concept_kind: "property", stable_key: "procurement.Contract.amount", ontology_version: "0.3.0", version_status: "published" }] });
      if (url.endsWith("/bindings/validation")) return response({ status: "valid", binding_count: 1, diagnostic_count: 0, diagnostics: [] });
      if (init?.method === "POST") return response({});
      return response({ items: [{ binding_id: "binding-1", ontology_ref_type: "property", ontology_ref_id: "revision-1", ontology_concept_id: "concept-1", ontology_stable_key: "procurement.Contract.amount", ontology_concept_kind: "property", target_type: "glossary_term", target_locator: "openmetadata://glossaryTerm/Procurement.ContractAmount", external_entity_id: "term-1", entity_type: "glossaryTerm", fully_qualified_name: "Procurement.ContractAmount", binding_type: "equivalent_to", purpose: "semantic_resolution", authority: "preferred", priority: 10, confidence: 1, status: "draft", created_by: "user:author", approved_by: null, created_at: "2026-10-05T00:00:00Z", last_verified_at: "2026-10-05T00:00:00Z" }] });
    });

    render(<BindingManager />);
    expect(await screen.findByText("procurement.Contract.amount")).toBeTruthy();
    expect(screen.getByText("Procurement.ContractAmount")).toBeTruthy();
    fireEvent.click(screen.getByText("Approve"));
    await waitFor(() => expect(fetchMock.mock.calls.some(([url, init]) => String(url).includes("binding-1/reviews") && init?.method === "POST")).toBe(true));
  });
});

function response(body: unknown): Promise<Response> {
  return Promise.resolve({ ok: true, status: 200, json: async () => body } as Response);
}
