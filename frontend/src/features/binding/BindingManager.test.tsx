import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { BindingManager } from "./BindingManager";
import { bindingApi, type SemanticBinding } from "../../api/binding";
import { ontologyApi } from "../../api/ontology";
import { metadataApi } from "../../api/metadata";

describe("BindingManager", () => {
  afterEach(() => { cleanup(); vi.restoreAllMocks(); });

  it("shows stable ontology concepts and reviews draft bindings", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.includes("/ontology-authoring/")) return response({ items: [{ concept_id: "concept-1", concept_kind: "property", stable_key: "procurement.Contract.currentAmount", ontology_version: "0.1.1", version_status: "published" }] });
      if (url.endsWith("/bindings/validation")) return response({ status: "valid", binding_count: 1, diagnostic_count: 0, diagnostics: [] });
      if (init?.method === "POST") return response({});
      return response({ items: [{ binding_id: "binding-1", ontology_ref_type: "property", ontology_ref_id: "revision-1", ontology_concept_id: "concept-1", ontology_stable_key: "procurement.Contract.currentAmount", ontology_concept_kind: "property", target_type: "glossary_term", target_locator: "openmetadata://glossaryTerm/Procurement.ContractAmount", external_entity_id: "term-1", entity_type: "glossaryTerm", fully_qualified_name: "Procurement.ContractAmount", binding_type: "equivalent_to", purpose: "semantic_resolution", authority: "preferred", priority: 10, confidence: 1, status: "draft", created_by: "user:author", approved_by: null, created_at: "2026-10-05T00:00:00Z", last_verified_at: "2026-10-05T00:00:00Z" }] });
    });

    render(<MemoryRouter><BindingManager /></MemoryRouter>);
    expect(await screen.findByText("procurement.Contract.currentAmount")).toBeTruthy();
    expect(screen.getByText("Procurement.ContractAmount")).toBeTruthy();
    fireEvent.click(screen.getByText("승인"));
    await waitFor(() => expect(fetchMock.mock.calls.some(([url, init]) => String(url).includes("binding-1/reviews") && init?.method === "POST")).toBe(true));
  });

  it("opens the exact draft from a suggestion even outside the latest asset context", async () => {
    const bindings = vi.spyOn(bindingApi, "bindings").mockResolvedValue({ items: [] });
    vi.spyOn(ontologyApi, "ontologyConcepts").mockResolvedValue({ items: [] });
    vi.spyOn(bindingApi, "bindingValidation").mockResolvedValue({ status: "valid", binding_count: 0, diagnostic_count: 0, diagnostics: [] });
    const context = vi.spyOn(metadataApi, "assetContext");
    render(<MemoryRouter initialEntries={["/?binding=draft-id&assetId=table-id"]}><BindingManager /></MemoryRouter>);
    await waitFor(() => expect(bindings).toHaveBeenCalledWith(undefined, ["draft-id"]));
    expect(context).not.toHaveBeenCalled();
  });

  it("paginates bindings and resets the page for search, size, and status changes", async () => {
    const items: SemanticBinding[] = Array.from({ length: 51 }, (_, index) => ({
      binding_id: `binding-${index}`, ontology_ref_type: "object", ontology_ref_id: "revision",
      ontology_concept_id: `concept-${index}`, ontology_stable_key: `goods.Item${index}`,
      ontology_concept_kind: "object", target_type: "glossary_term", target_locator: "openmetadata://term",
      external_entity_id: `term-${index}`, entity_type: "glossaryTerm", fully_qualified_name: `Goods.Item${index}`,
      binding_type: "equivalent_to", purpose: "semantic_resolution", authority: "preferred",
      priority: 100, confidence: null, status: "approved", created_by: "author", approved_by: "reviewer",
      created_at: "2026-10-27", last_verified_at: null,
    }));
    vi.spyOn(bindingApi, "bindings").mockImplementation(async status => ({ items: status ? items.slice(0, 2) : items }));
    vi.spyOn(ontologyApi, "ontologyConcepts").mockResolvedValue({ items: [] });
    vi.spyOn(bindingApi, "bindingValidation").mockResolvedValue({ status: "valid", binding_count: 51, diagnostic_count: 0, diagnostics: [] });
    render(<MemoryRouter><BindingManager /></MemoryRouter>);
    expect(await screen.findByText("1–25 / 51개")).toBeTruthy();
    expect(screen.queryByText("goods.Item25")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "다음 페이지" }));
    expect(screen.getByText("goods.Item25")).toBeTruthy();
    expect(screen.queryByText("goods.Item0")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "다음 페이지" }));
    expect(screen.getByText("51–51 / 51개")).toBeTruthy();
    expect((screen.getByRole("button", { name: "다음 페이지" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "이전 페이지" }));
    expect(screen.getByText("26–50 / 51개")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("페이지당"), { target: { value: "50" } });
    expect(screen.getByText("1–50 / 51개")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "다음 페이지" }));
    fireEvent.change(screen.getByRole("textbox", { name: "의미 연결 검색" }), { target: { value: "Item0" } });
    expect(screen.getByText("goods.Item0")).toBeTruthy();
    expect(screen.getByText("1–1 / 1개")).toBeTruthy();
    fireEvent.change(screen.getByRole("textbox", { name: "의미 연결 검색" }), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "다음 페이지" }));
    fireEvent.click(screen.getByRole("button", { name: "승인됨" }));
    expect(await screen.findByText("1–2 / 2개")).toBeTruthy();
    expect(screen.getByText("goods.Item0")).toBeTruthy();
  });
});

function response(body: unknown): Promise<Response> {
  return Promise.resolve({ ok: true, status: 200, json: async () => body } as Response);
}
