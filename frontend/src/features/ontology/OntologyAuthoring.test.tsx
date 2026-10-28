import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { OntologyAuthoring } from "./OntologyAuthoring";
import { MemoryRouter } from "react-router-dom";
import { ontologyApi, type OntologyVersionDetail } from "../../api/ontology";

describe("OntologyAuthoring", () => {
  afterEach(() => { cleanup(); vi.restoreAllMocks(); });
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

    render(<MemoryRouter><OntologyAuthoring /></MemoryRouter>);
    expect(await screen.findByText("party.BusinessEntity")).toBeTruthy();
    expect(screen.getAllByText("업체").length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole("button", { name: /업체.*party.BusinessEntity/ }));
    expect(screen.getByText("식별 기준")).toBeTruthy();
    expect(screen.getByText("businessEntityId")).toBeTruthy();
    fireEvent.change(screen.getByRole("textbox", { name: "온톨로지 검색" }), { target: { value: "no_matching_concept" } });
    expect(screen.getByText("조건에 맞는 업무 개념이 없습니다")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "검색 초기화" }));
    expect(screen.getByText("party.BusinessEntity")).toBeTruthy();
    fireEvent.click(screen.getByText("관계", { selector: "button" }));
    expect(screen.getByText("party.HAS_REGISTRATION")).toBeTruthy();
    fireEvent.click(screen.getByText("규칙", { selector: "button" }));
    expect(screen.getByText("party.ENTITY_RULE")).toBeTruthy();
    fireEvent.click(screen.getByText("관계도"));
    expect(await screen.findByLabelText("도메인 필터")).toBeTruthy();
    fireEvent.click(screen.getByText("버전 검토"));
    expect(await screen.findByText("구조 검증 통과")).toBeTruthy();
    expect(screen.getByText("호환 가능")).toBeTruthy();
  });

  it("opens the persisted draft in its owning ontology instead of the published version", async () => {
    vi.spyOn(ontologyApi, "authoredOntologies").mockResolvedValue({ items: [] });
    const versions = vi.spyOn(ontologyApi, "ontologyVersions").mockResolvedValue({ items: [
      { ontology_version_id: "published", version: "1", status: "published", created_at: "2026-10-01" },
      { ontology_version_id: "draft-id", version: "2", status: "draft", created_at: "2026-10-14" },
    ] });
    const detail = vi.spyOn(ontologyApi, "ontologyVersion").mockResolvedValue({
      ontology_version_id: "draft-id", version: "2", namespace: "second_domain", ontology_name: "새 업무", status: "draft", created_at: "2026-10-14",
      objects: [], relationships: [], rules: [], metrics: [],
    } as OntologyVersionDetail);
    render(<MemoryRouter initialEntries={["/?version=draft-id"]}><OntologyAuthoring /></MemoryRouter>);
    expect(await screen.findByText("새 업무 v2")).toBeTruthy();
    expect(versions).toHaveBeenCalledWith("second_domain");
    expect(detail.mock.calls.every(([id]) => id === "draft-id")).toBe(true);
  });

  it("paginates concepts, relationships, and rules after filtering", async () => {
    const detail: OntologyVersionDetail = {
      ontology_version_id: "version-1", version: "1", namespace: "teoria", ontology_name: "업무 모델",
      status: "published", created_at: "2026-10-27", metrics: [],
      objects: Array.from({ length: 51 }, (_, index) => ({
        business_object_id: `object-${index}`, concept_id: `concept-${index}`, stable_key: `goods.Item${index}`,
        code: `Item${index}`, name: `개념 ${index}`, description: "", identity_policy: {}, properties: [],
      })),
      relationships: Array.from({ length: 51 }, (_, index) => ({
        concept_id: `link-${index}`, stable_key: `goods.Link${index}`, code: `Link${index}`, name: `관계 ${index}`,
        source_object_id: "object-0", target_object_id: "object-1", source_cardinality: "one", target_cardinality: "many", temporal: false,
      })),
      rules: Array.from({ length: 51 }, (_, index) => ({
        concept_id: `rule-${index}`, stable_key: `goods.Rule${index}`, code: `Rule${index}`, name: `규칙 ${index}`,
        description: "", evaluator_key: null,
      })),
    };
    vi.spyOn(ontologyApi, "authoredOntologies").mockResolvedValue({ items: [{namespace:"teoria",name:"업무 모델",description:"",version_count:1,latest_version:"1",latest_status:"published"}] });
    vi.spyOn(ontologyApi, "ontologyVersions").mockResolvedValue({ items: [detail] });
    vi.spyOn(ontologyApi, "ontologyVersion").mockResolvedValue(detail);
    render(<MemoryRouter><OntologyAuthoring /></MemoryRouter>);
    expect(await screen.findByText("1–25 / 51개")).toBeTruthy();
    for (const [tab, prefix] of [["업무 개념", "Item"], ["관계", "Link"], ["규칙", "Rule"]]) {
      fireEvent.click(screen.getByRole("button", { name: new RegExp(`^${tab}\\s*51$`) }));
      expect(screen.getByText(`goods.${prefix}0`)).toBeTruthy();
      expect(screen.queryByText(`goods.${prefix}25`)).toBeNull();
      fireEvent.click(screen.getByRole("button", { name: "다음 페이지" }));
      expect(screen.getByText(`goods.${prefix}25`)).toBeTruthy();
      expect(screen.queryByText(`goods.${prefix}0`)).toBeNull();
      fireEvent.click(screen.getByRole("button", { name: "다음 페이지" }));
      expect(screen.getByText("51–51 / 51개")).toBeTruthy();
      expect((screen.getByRole("button", { name: "다음 페이지" }) as HTMLButtonElement).disabled).toBe(true);
      fireEvent.change(screen.getByRole("textbox", { name: "온톨로지 검색" }), { target: { value: `${prefix}0` } });
      expect(screen.getByText(`goods.${prefix}0`)).toBeTruthy();
      expect(screen.getByText("1–1 / 1개")).toBeTruthy();
      fireEvent.change(screen.getByRole("textbox", { name: "온톨로지 검색" }), { target: { value: "" } });
      fireEvent.click(screen.getByRole("button", { name: "다음 페이지" }));
    }
    fireEvent.change(screen.getByLabelText("페이지당"), { target: { value: "50" } });
    expect(screen.getByText("1–50 / 51개")).toBeTruthy();
    fireEvent.change(screen.getByRole("textbox", { name: "온톨로지 검색" }), { target: { value: "missing" } });
    expect(screen.getByText("0개")).toBeTruthy();
    expect((screen.getByRole("button", { name: "다음 페이지" }) as HTMLButtonElement).disabled).toBe(true);
  });
});

function response(body: unknown): Promise<Response> {
  return Promise.resolve({ ok: true, status: 200, json: async () => body } as Response);
}
