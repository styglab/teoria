import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { OntologyAuthoring } from "./OntologyAuthoring";

describe("OntologyAuthoring", () => {
  afterEach(() => vi.restoreAllMocks());
  beforeEach(() => {
    vi.stubGlobal("ResizeObserver", class {
      observe() {}
      unobserve() {}
      disconnect() {}
    });
  });

  it("discovers the unified ontology and shows objects, links, and rules", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith("/ontology-authoring/ontologies")) return response({ items: [{ namespace: "teoria", name: "Teoria Business Ontology", description: "", version_count: 1, latest_version: "0.1.0", latest_status: "draft" }] });
      if (url.endsWith("/ontology-authoring/ontologies/teoria/versions")) return response({ items: [{ ontology_version_id: "version-1", version: "0.1.0", status: "draft", created_at: "2026-10-06" }] });
      if (url.endsWith("/ontology-authoring/versions/version-1")) return response({ ontology_version_id: "version-1", version: "0.1.0", status: "draft", created_at: "2026-10-06", namespace: "teoria", ontology_name: "Teoria Business Ontology", objects: [{ business_object_id: "object-1", concept_id: "concept-1", stable_key: "party.BusinessEntity", code: "BusinessEntity", name: "업체", description: "업체", identity_policy: { properties: ["businessEntityId"] }, properties: [] }], relationships: [{ concept_id: "link-1", stable_key: "party.HAS_REGISTRATION", code: "HAS_REGISTRATION", name: "사업자등록 보유", source_object_id: "object-1", target_object_id: "object-1", source_cardinality: "one", target_cardinality: "many", temporal: true }], rules: [{ concept_id: "rule-1", stable_key: "party.ENTITY_RULE", code: "ENTITY_RULE", name: "업체 규칙", description: "규칙", evaluator_key: "party.rule.v1" }], metrics: [] });
      if (url.endsWith("/ontology-authoring/versions/version-1/validation")) return response({ status: "valid", diagnostic_count: 0, diagnostics: [], binding_impact: { compatible: true, incompatible_binding_count: 0, incompatible_bindings: [] } });
      if (url.endsWith("/ontology-authoring/versions/version-1/binding-impact")) return response({ compatible: true, incompatible_binding_count: 0, incompatible_bindings: [] });
      throw new Error(`unexpected request: ${url}`);
    });

    render(<OntologyAuthoring />);
    expect(await screen.findByText("Graph")).toBeTruthy();
    expect(await screen.findByLabelText("도메인 필터")).toBeTruthy();
    fireEvent.click(screen.getByText("Objects"));
    expect(await screen.findByText("party.BusinessEntity")).toBeTruthy();
    expect(screen.getAllByText("업체").length).toBeGreaterThan(0);
    fireEvent.click(screen.getByText("Links"));
    expect(screen.getByText("party.HAS_REGISTRATION")).toBeTruthy();
    fireEvent.click(screen.getByText("Rules"));
    expect(screen.getByText("party.ENTITY_RULE")).toBeTruthy();
    fireEvent.click(screen.getByText("Review"));
    expect(await screen.findByText("구조 검증 통과")).toBeTruthy();
    expect(screen.getByText("호환 가능")).toBeTruthy();
  });
});

function response(body: unknown): Promise<Response> {
  return Promise.resolve({ ok: true, status: 200, json: async () => body } as Response);
}
