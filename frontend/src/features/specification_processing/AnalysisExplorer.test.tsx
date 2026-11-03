import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { AnalysisExplorer, composition } from "./AnalysisExplorer";
import { AttributeValue } from "./AttributeValue";
afterEach(cleanup);
it("separates existing assets and installation support while preserving their source and relations", () => {
  const value = {
    document_id: "roles",
    entities: [
      { id: "root", name: "구매 서버", kind: "equipment" },
      { id: "cpu", name: "CPU", kind: "equipment" },
      { id: "old", name: "기존 서버", kind: "equipment", document_roles: ["existing_target"] },
      { id: "part", name: "기존 부품", kind: "equipment" },
      { id: "install", name: "설치 지원", kind: "activity" },
    ],
    relations: [
      { source_id: "cpu", target_id: "root", kind: "component_of", basis: "explicit", evidence: [{ node_id: "n" }] },
      { source_id: "part", target_id: "old", kind: "physical_part_of", basis: "explicit", evidence: [{ node_id: "n" }] },
      { source_id: "install", target_id: "old", kind: "service_for", basis: "explicit", evidence: [{ node_id: "n" }] },
    ],
    attributes: [],
    parsed_document: { nodes: [{ node_id: "n", text: "기존 서버에 대한 설치 지원을 제공한다." }] },
  };
  const primary = composition(value, "composition", true);
  expect(primary.roots.map((e) => e.id)).toEqual(["root"]);
  expect(primary.related.map((e) => e.id)).toEqual(["old", "part", "install"]);
  render(<AnalysisExplorer value={{ documents: [value] }} />);
  const primaryTree = screen.getByRole("tree", { name: "구성 대상" });
  expect(within(primaryTree).getByRole("treeitem", { name: /CPU/ })).toBeTruthy();
  expect(within(primaryTree).queryByRole("treeitem", { name: /기존 서버/ })).toBeNull();
  const summary = screen.getByText("관련 대상·설치 지원·문서 · 3");
  const related = summary.closest("details")!;
  expect(related.open).toBe(false);
  fireEvent.click(summary);
  fireEvent.click(within(related).getByRole("treeitem", { name: /설치 지원/ }));
  fireEvent.click(screen.getByRole("button", { name: "관계" }));
  expect(screen.getAllByText(/기존 서버/).length).toBeGreaterThan(0);
  expect(within(related).getByRole("treeitem", { name: /기존 서버.*기존 대상/ })).toBeTruthy();
});
const evidence = [{ node_id: "n1" }];
const relation = (
  source_id: string,
  target_id: string,
  kind = "component_of",
  basis = "explicit",
) => ({ source_id, target_id, kind, basis, evidence });
const document = {
  document_id: "d1",
  entities: [
    { id: "root", name: "서버" },
    { id: "cpu", name: "프로세서" },
    { id: "task", name: "설치 작업" },
  ],
  relations: [relation("cpu", "root"), relation("task", "root", "service_for")],
  declared_quantities: [{ entity_id: "cpu", value_raw: "2", unit_raw: "개" }],
  attributes: [
    {
      subject_ids: ["cpu"],
      property_raw: "코어 수",
      value_raw: "32",
      unit_raw: "개",
      evidence: { node_id: "n1", fragment_id: "n1_f00" },
    },
  ],
  parsed_document: {
    nodes: [{ node_id: "n1", text: "프로세서는 32코어 이상", page: 2 }],
  },
};
it("selects a nested component and shows its own properties and original evidence", () => {
  render(<AnalysisExplorer value={{ documents: [document] }} />);
  fireEvent.click(screen.getByRole("treeitem", { name: /프로세서 1개 속성/ }));
  const detail = screen.getByRole("region", { name: "분석 대상 상세" });
  expect(within(detail).getByText("코어 수")).toBeTruthy();
  expect(within(detail).getByText("2 개", { exact: true })).toBeTruthy();
  expect(within(detail).getByText("32", { exact: true })).toBeTruthy();
  fireEvent.click(
    within(detail).getAllByRole("button", { name: "원문 보기" })[0],
  );
  expect(within(screen.getByRole("region", { name: "선택한 원문 근거" })).getByText("프로세서는 32코어 이상")).toBeTruthy();
  expect(screen.getByRole("heading", { name: "구성 관계" })).toBeTruthy();
  fireEvent.change(screen.getByLabelText("조회 범위"), {
    target: { value: "all" },
  });
  fireEvent.change(screen.getByLabelText("분석 대상 검색"), {
    target: { value: "설치" },
  });
  expect(
    screen.getByRole("treeitem", { name: /설치 작업 0개 속성/ }),
  ).toBeTruthy();
  expect(
    screen.queryByRole("button", { name: /프로세서 1개 속성/ }),
  ).toBeNull();
});
it("keeps interpreted links under review and excludes scope, cyclic and multiple-parent links", () => {
  const entities = ["a", "b", "c", "d", "e", "f"].map((id) => ({
    id,
    name: id,
  }));
  const graph = composition({
    entities,
    relations: [
      relation("a", "b"),
      relation("b", "a"),
      relation("c", "d", "in_procurement_scope"),
      relation("d", "e", "component_of", "interpreted"),
      relation("f", "d"),
      relation("f", "e"),
    ],
  });
  expect([...graph.children]).toEqual([["e", ["d"]]]);
  expect([...graph.pendingParents]).toEqual(["d"]);
  expect(graph.roots.map((e) => e.id)).toEqual(["e"]);
  expect(graph.unclassified.map((e) => e.id)).toEqual(["a", "b", "c", "f"]);
});

const lcmsConfiguration = () => {
  const names = ["질량분석기", "시스템 컨트롤러", "용매 운반용 펌프", "자동시료주입기",
    "컬럼오븐", "광다이오드어레이 검출기", "온라인 가스제거 유닛", "데이터 처리 시스템", "악세서리"];
  const item_ids = names.map((_, i) => `i${i + 1}`);
  return {
    document_id: "lcms",
    composition_inventory: { root_id: "scope", basis: "configuration_list", integrated_scope: true, item_ids },
    entities: [{ id: "scope", name: "액체크로마토그래프 질량분석기", kind: "equipment" },
      ...names.map((name, i) => ({ id: item_ids[i], name, kind: "equipment" })),
      ...[{ id: "pc", name: "PC SYSTEM" }, { id: "cpu", name: "CPU" },
        { id: "detector", name: "검출기" }, { id: "dynode", name: "변환 다이노드" }]
        .map((e) => ({ ...e, kind: "equipment" }))],
    relations: [...item_ids.map((id) => relation(id, "scope")),
      relation("pc", "i8", "component_of", "interpreted"), relation("cpu", "pc"),
      relation("detector", "i1", "component_of", "interpreted"), relation("dynode", "detector")],
    attributes: [], parsed_document: { nodes: [{ node_id: "n1", text: "8. 데이터 처리 시스템 (4) PC SYSTEM" }] },
  };
};

it("limits the default tree to three levels while preserving deep components and their source parents", () => {
  const value = { ...lcmsConfiguration(), attributes: [{ id: "cpu_cores", subject_ids: ["cpu"],
    property_raw: "코어 수", value_raw: "8", unit_raw: "core", evidence: { node_id: "n1" } }] };
  value.relations.reverse();
  const graph = composition(value);
  expect(graph.roots.map((e) => e.id)).toEqual(["scope"]);
  expect(graph.children.get("scope")).toEqual(value.composition_inventory.item_ids);
  expect(graph.children.get("i8")).toEqual(["pc"]);
  expect(graph.children.get("pc")).toEqual(["cpu"]);
  expect(graph.displayChildren.has("pc")).toBe(false);
  expect(graph.detailTargets.map((e) => e.id)).toEqual(["cpu", "dynode"]);
  expect(graph.unclassified).toEqual([]);
  expect(graph.children.get("i1")).toEqual(["detector"]);
  render(<AnalysisExplorer value={{ documents: [value] }} />);
  const pc = screen.getByRole("treeitem", { name: /PC SYSTEM/ });
  expect(pc.getAttribute("aria-level")).toBe("3");
  expect(pc.textContent).toContain("구성 관계 검토 중");
  const tree = screen.getByRole("tree", { name: "구성 대상" });
  expect(within(tree).queryByRole("treeitem", { name: /CPU/ })).toBeNull();
  expect(pc.hasAttribute("aria-expanded")).toBe(false);
  fireEvent.click(screen.getByRole("button", { name: "전체 펼치기" }));
  expect(within(tree).queryByRole("treeitem", { name: /CPU/ })).toBeNull();
  const summary = screen.getByText("세부 구성 · 2");
  expect(summary.closest("details")?.hasAttribute("open")).toBe(false);
  fireEvent.click(summary);
  const details = screen.getByRole("tree", { name: "세부 구성" });
  fireEvent.click(within(details).getByRole("treeitem", { name: /CPU/ }));
  const detail = screen.getByRole("region", { name: "분석 대상 상세" });
  expect(within(detail).getByText("코어 수")).toBeTruthy();
  expect(within(detail).getByText("8")).toBeTruthy();
  expect(within(detail).getByText("core")).toBeTruthy();
  fireEvent.click(within(detail).getByRole("button", { name: /원문 보기/ }));
  expect(within(screen.getByRole("region", { name: "선택한 원문 근거" }))
    .getByText("8. 데이터 처리 시스템 (4) PC SYSTEM")).toBeTruthy();
});

it("uses the pipeline hierarchy contract while preserving the full relation graph", () => {
  const value = lcmsConfiguration();
  const graph = composition({ ...value, composition_hierarchy: {
    schema_version: 1, max_primary_levels: 3, root_ids: ["scope"],
    primary_entity_ids: ["scope", ...value.composition_inventory.item_ids, "pc", "detector"],
    detail_entity_ids: ["cpu", "dynode"], levels: { scope: 1, i8: 2, pc: 3, cpu: 4, dynode: 4 },
  } });
  expect(graph.children.get("pc")).toEqual(["cpu"]);
  expect(graph.displayChildren.has("pc")).toBe(false);
  expect(graph.detailTargets.map((e) => e.id)).toEqual(["cpu", "dynode"]);
  expect(graph.treeIds.has("cpu")).toBe(true);
  expect(graph.unclassified).toEqual([]);
});

it("does not promote PC or its descendants when the parent proposal is held or missing", () => {
  for (const held of [false, true]) {
    const value = lcmsConfiguration();
    const pcLink = value.relations.find((r) => r.source_id === "pc")!;
    const graph = composition({ ...value, relations: value.relations.filter((r) => r !== pcLink),
      held_relations: held ? [{ ...pcLink, review_status: "held" }] : [] });
    expect(graph.roots.map((e) => e.id)).toEqual(["scope"]);
    expect(graph.unclassified.map((e) => e.id)).toEqual(["pc", "cpu"]);
  }
});

it("does not treat interpreted physical inclusion or packaging as established hierarchy", () => {
  const entities = [{ id: "a", name: "a" }, { id: "b", name: "b" }];
  expect(composition({ entities, relations: [relation("a", "b", "physical_part_of", "interpreted")] }).children.size).toBe(0);
  expect(composition({ entities, relations: [relation("a", "b", "pack_unit_of", "interpreted")] }, "packaging").children.size).toBe(0);
});
it("preserves comparison operators and conditions in property values", () => {
  render(
    <AnalysisExplorer
      value={{
        documents: [
          {
            ...document,
            attributes: [
              {
                subject_ids: ["root"],
                property_raw: "용량",
                value_raw: "64",
                operator_raw: "≥",
                qualifiers_raw: ["최소 보장"],
              },
            ],
          },
        ],
      }}
    />,
  );
  expect(screen.getByText("≥ 64", { exact: true })).toBeTruthy();
  expect(screen.getByText("조건: 최소 보장")).toBeTruthy();
});
it("switches documents without retaining the previous selection or source", () => {
  render(
    <AnalysisExplorer
      value={{
        documents: [
          document,
          {
            document_id: "d2",
            entities: [{ id: "other", name: "다른 장비" }],
            attributes: [],
          },
        ],
      }}
    />,
  );
  fireEvent.change(screen.getByLabelText("규격서 선택"), {
    target: { value: "1" },
  });
  expect(screen.getByRole("heading", { name: "다른 장비" })).toBeTruthy();
  expect(
    screen.queryByRole("button", { name: /프로세서 1개 속성/ }),
  ).toBeNull();
});

it("joins standard mappings by document and observation ID and keeps source labels separate", () => {
  render(
    <AnalysisExplorer
      value={{
        documents: [
          {
            ...document,
            attributes: [{ ...document.attributes[0], id: "a1" }],
          },
        ],
      }}
      normalization={{
        standard_version: "v1",
        attributes: [
          {
            document_id: "another",
            attribute_id: "a1",
            status: "applied",
            facts: [{ property_id: "wrong_standard" }],
          },
          {
            document_id: "d1",
            attribute_id: "a1",
            status: "applied",
            facts: [{ property_id: "cpu_core_count" }],
          },
        ],
      }}
      mappingStatus="available"
    />,
  );
  fireEvent.click(screen.getByRole("treeitem", { name: /프로세서 1개 속성/ }));
  expect(screen.queryByText("cpu_core_count")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "표준 매핑" }));
  expect(screen.getByText("cpu_core_count")).toBeTruthy();
  expect(screen.queryByText("wrong_standard")).toBeNull();
  expect(screen.getByText("연결됨", { exact: true })).toBeTruthy();
  expect(screen.getByText(/추출용 표준 초안/)).toBeTruthy();
});
it("distinguishes mapping failure from unmapped and opens evidence from the selected row", () => {
  render(
    <AnalysisExplorer
      value={{ documents: [document] }}
      mappingStatus="error"
    />,
  );
  fireEvent.click(screen.getByRole("treeitem", { name: /프로세서 1개 속성/ }));
  fireEvent.click(screen.getByRole("button", { name: "표준 매핑" }));
  expect(screen.getByText("조회 실패", { exact: true })).toBeTruthy();
  const row = screen.getByText("코어 수").closest("tr")!;
  fireEvent.keyDown(row, { key: "Enter" });
  expect(row.getAttribute("aria-selected")).toBe("true");
  expect(within(screen.getByRole("region", { name: "선택한 원문 근거" })).getByText("프로세서는 32코어 이상")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "근거 닫기" }));
  expect(screen.queryByRole("region", { name: "선택한 원문 근거" })).toBeNull();
});
it("filters missing source evidence without losing the full property count", () => {
  render(
    <AnalysisExplorer
      value={{
        documents: [
          {
            ...document,
            attributes: [
              {
                subject_ids: ["root"],
                property_raw: "확인 필요",
                value_raw: "값",
                evidence: { node_id: "missing" },
              },
            ],
          },
        ],
      }}
    />,
  );
  fireEvent.change(screen.getByLabelText("속성 필터"), {
    target: { value: "evidence" },
  });
  fireEvent.click(screen.getByText("확인 필요").closest("tr")!);
  expect(
    screen.getByText("이 산출물에서 해당 원문 노드를 찾지 못했습니다."),
  ).toBeTruthy();
  expect(screen.getByRole("heading", { name: "추출 속성 · 1" })).toBeTruthy();
});

it("separates software, support and submitted documents from the physical tree even for legacy composition", () => {
  const value = {
    ...document,
    entities: [
      { id: "root", name: "서버", kind: "equipment" },
      { id: "cpu", name: "프로세서", kind: "equipment" },
      { id: "task", name: "설치 작업", kind: "activity" },
      { id: "sw", name: "Docker", kind: "software" },
      { id: "manual", name: "HW/SW 설치 및 사용 매뉴얼", kind: "document" },
    ],
    relations: [
      relation("cpu", "root"),
      relation("task", "root", "service_for"),
      relation("sw", "root", "software_for"),
      relation("manual", "root", "document_for"),
      relation("manual", "root"),
      relation("sw", "root"),
    ],
    requirements: [
      {
        id: "clause",
        subject_ids: ["manual"],
        observation_type: "source_clause",
        text: "설치 작업의 종료와 함께 다음의 문서를 제출하여야 한다.",
        evidence,
      },
    ],
  };
  const graph = composition(value);
  expect(graph.children.get("root")).toEqual(["cpu"]);
  render(<AnalysisExplorer value={{ documents: [value] }} />);
  fireEvent.change(screen.getByLabelText("대상 유형"), {
    target: { value: "software" },
  });
  expect(
    screen.getByRole("treeitem", { name: /Docker 0개 속성/ }),
  ).toBeTruthy();
  expect(
    screen.queryByRole("button", { name: /설치 작업 0개 속성/ }),
  ).toBeNull();
  fireEvent.change(screen.getByLabelText("조회 범위"), {
    target: { value: "all" },
  });
  fireEvent.click(
    screen.getByRole("treeitem", {
      name: /HW\/SW 설치 및 사용 매뉴얼 0개 속성/,
    }),
  );
  fireEvent.click(screen.getByRole("button", { name: "관계" }));
  expect(screen.getByText(/문서 대상 · 명시/)).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "속성" }));
  expect(
    screen.getByText("설치 작업의 종료와 함께 다음의 문서를 제출하여야 한다."),
  ).toBeTruthy();
  expect(screen.queryByText(/미분류 항목/)).toBeNull();
});

it("starts with independent food items and offers packaging separately from composition", () => {
  const milk = {
    document_id: "milk",
    inventory_ids: ["large", "small"],
    entities: [
      { id: "scope", name: "급식 물품", kind: "group" },
      { id: "large", name: "우유/대", kind: "product" },
      { id: "small", name: "우유/소", kind: "product" },
      { id: "box", name: "상자", kind: "product" },
      { id: "paper", name: "종이", kind: "material" },
    ],
    relations: [
      relation("large", "scope", "in_procurement_scope"),
      relation("small", "scope", "in_procurement_scope"),
      relation("large", "box", "pack_unit_of"),
      relation("paper", "large", "packaging_for"),
    ],
    attributes: [],
  };
  expect(composition(milk).children.size).toBe(0);
  expect(composition(milk, "packaging").children.get("box")).toEqual(["large"]);
  render(<AnalysisExplorer value={{ documents: [milk] }} />);
  expect(
    (screen.getByRole("combobox", { name: "탐색 방식" }) as HTMLSelectElement)
      .value,
  ).toBe("list");
  expect(screen.getByRole("heading", { name: "대상 목록" })).toBeTruthy();
  expect(screen.getByRole("heading", { name: "우유/대" })).toBeTruthy();
  fireEvent.change(screen.getByLabelText("조회 범위"), {
    target: { value: "purchase" },
  });
  expect(
    screen.getByRole("treeitem", { name: /우유\/소 0개 속성/ }),
  ).toBeTruthy();
  expect(screen.queryByRole("button", { name: /상자 0개 속성/ })).toBeNull();
  fireEvent.change(screen.getByLabelText("조회 범위"), {
    target: { value: "all" },
  });
  fireEvent.change(screen.getByLabelText("탐색 방식"), {
    target: { value: "packaging" },
  });
  expect(screen.getByRole("heading", { name: "포장 단위 관계" })).toBeTruthy();
  expect(screen.getByRole("button", { name: "상자 접기" })).toBeTruthy();
});

it("keeps a standalone software purchase visible without manufacturing hardware or inventory children", () => {
  render(
    <AnalysisExplorer
      value={{
        documents: [
          {
            document_id: "cad",
            inventory_ids: [],
            entities: [
              {
                id: "root",
                name: "CAD 소프트웨어",
                kind: "software",
                document_roles: ["procurement_scope"],
              },
            ],
            relations: [],
            attributes: [],
          },
        ],
      }}
    />,
  );
  fireEvent.change(screen.getByLabelText("조회 범위"), {
    target: { value: "purchase" },
  });
  expect(
    screen.getByRole("treeitem", { name: /CAD 소프트웨어 0개 속성/ }),
  ).toBeTruthy();
  expect(screen.queryByText(/확인된 구성 계층/)).toBeNull();
});

it("keeps other requirements collapsed with source text instead of duty fields", () => {
  const clause = {
    id: "clause1",
    observation_type: "source_clause",
    category: "other",
    subject_ids: [],
    text: "제작사는 안전 관련 법령을 준수할 것",
    evidence,
  };
  render(
    <AnalysisExplorer
      value={{
        documents: [
          {
            ...document,
            entities: document.entities.map((e) => ({
              ...e,
              kind: e.id === "task" ? "activity" : "equipment",
            })),
            requirements: [clause],
          },
        ],
      }}
    />,
  );
  const detail = screen.getByRole("region", { name: "분석 대상 상세" });
  expect(
    within(detail).getByText("기타 요구사항 · 1").closest("details")?.open,
  ).toBe(false);
  expect(within(detail).getByText(clause.text)).toBeTruthy();
  expect(within(detail).queryByText(/구조화된 의무/)).toBeNull();
  expect((screen.getByLabelText("조회 범위") as HTMLSelectElement).value).toBe(
    "goods",
  );
  fireEvent.change(screen.getByLabelText("조회 범위"), { target: { value: "all" } });
  expect(
    screen.getByRole("treeitem", { name: /설치 작업 0개 속성/ }),
  ).toBeTruthy();
  fireEvent.click(
    within(
      within(detail).getByText("기타 요구사항 · 1").closest("details")!,
    ).getByRole("button", { name: "원문 보기" }),
  );
  expect(within(screen.getByRole("region", { name: "선택한 원문 근거" })).getByText("프로세서는 32코어 이상")).toBeTruthy();
});

it("finds a source alias without adding another product and keeps the original name collapsed", () => {
  const sourceName = "열화상카메라(정적상태진단시험)";
  const value = {
    ...document,
    entities: [
      {
        id: "root",
        name: "열화상카메라",
        name_raw: sourceName,
        kind: "equipment",
        aliases: [{ name: "Thermal camera", evidence }],
        descriptions: [{ text: "정적상태진단시험", evidence }],
      },
    ],
    attributes: [],
    relations: [],
  };
  render(<AnalysisExplorer value={{ documents: [value] }} />);
  fireEvent.change(screen.getByLabelText("분석 대상 검색"), {
    target: { value: "Thermal camera" },
  });
  expect(
    screen.getByRole("treeitem", { name: /열화상카메라 0개 속성/ }),
  ).toBeTruthy();
  const details = screen.getByText("원문 명칭·다른 표현").closest("details")!;
  expect(details.open).toBe(false);
  expect(within(details).getByText(`원문 명칭: ${sourceName}`)).toBeTruthy();
});

it("shows document-wide counts and directional relationships with navigable endpoints", () => {
  render(<AnalysisExplorer value={{ documents: [document] }} />);
  const summary = screen.getByLabelText("규격서 결과 요약");
  expect(summary.textContent).toContain("대상 3");
  expect(summary.textContent).toContain("관계 2");
  expect(summary.textContent).toContain("속성 1");
  fireEvent.click(within(summary).getByRole("button", { name: /관계 2/ }));
  const relations = screen.getByRole("region", { name: "선택한 엔티티 관계" });
  expect((screen.getByLabelText("관계 범위") as HTMLSelectElement).value).toBe(
    "document",
  );
  expect(within(relations).getAllByLabelText("관계 방향")).toHaveLength(2);
  expect(within(relations).getByText("구성품 · 명시")).toBeTruthy();
  fireEvent.click(within(relations).getByRole("button", { name: "프로세서" }));
  expect(screen.getByRole("heading", { name: "프로세서" })).toBeTruthy();
  expect((screen.getByLabelText("관계 범위") as HTMLSelectElement).value).toBe(
    "selected",
  );
  expect(screen.queryByRole("button", { name: "프로파일 승인" })).toBeNull();
});
it("presents held relations and incomplete attributes as read-only unresolved results with evidence", () => {
  const value = {
    ...document,
    extraction_status: "partial",
    attributes: [
      {
        id: "loose",
        subject_ids: ["missing"],
        property_raw: "확인할 용량",
        value_raw: "64",
        evidence: { node_id: "n1" },
      },
    ],
    held_relations: [
      {
        ...relation("cpu", "root", "supports"),
        review_status: "held",
        reasons: ["방향이 불명확함"],
      },
    ],
  };
  render(<AnalysisExplorer value={{ documents: [value] }} />);
  fireEvent.click(screen.getByRole("button", { name: "미해결 항목" }));
  const issues = screen.getByRole("region", { name: "문서 미해결 항목" });
  expect(within(issues).getByText("확인할 용량: 64")).toBeTruthy();
  expect(within(issues).queryByText(/방향이 불명확함/)).toBeNull();
  expect(screen.getByRole("button", { name: "미해결 항목 1" })).toBeTruthy();
  fireEvent.click(screen.getByText("부가 관계 검토 · 1", { selector: "summary" }));
  expect(within(screen.getByRole("region", { name: "부가 관계 검토" })).getByText(/방향이 불명확함/)).toBeTruthy();
  fireEvent.click(
    within(issues).getByRole("button", { name: "속성 원문 확인" }),
  );
  expect(within(screen.getByRole("region", { name: "선택한 원문 근거" })).getByText("프로세서는 32코어 이상")).toBeTruthy();
  expect(screen.queryByRole("button", { name: /승인|반려/ })).toBeNull();
});
it("does not count a supplementary-only hold as an unresolved product extraction", () => {
  render(<AnalysisExplorer value={{ documents: [{ ...document, extraction_status: "extracted", attributes: [],
    held_relations: [{ ...relation("cpu", "root", "compatible_with"), reasons: ["호환 여부 확인 필요"] }],
  }] }} />);
  expect(screen.getByRole("button", { name: "미해결 항목 0" })).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "미해결 항목" }));
  expect(within(screen.getByRole("region", { name: "문서 미해결 항목" })).queryByText(/호환 여부/)).toBeNull();
  expect(screen.getByText("부가 관계 검토 · 1", { selector: "summary" })).toBeTruthy();
});
it("retains failed documents in the document selector instead of presenting them as empty success", () => {
  render(
    <AnalysisExplorer
      value={{
        documents: [document],
        unavailable_documents: [
          {
            document_id: "failed",
            status: "failed",
            error_code: "parse_failed",
            source: { filename: "실패한 규격서.pdf" },
          },
        ],
      }}
    />,
  );
  fireEvent.change(screen.getByLabelText("규격서 선택"), {
    target: { value: "1" },
  });
  expect(screen.getByText("이 규격서의 구조화 결과가 없습니다")).toBeTruthy();
  expect(screen.getByText("parse_failed")).toBeTruthy();
  expect(screen.queryByRole("heading", { name: "서버" })).toBeNull();
});
it("shows normalized values next to original conditions while keeping mappings scoped to the document", () => {
  const value = {
    ...document,
    attributes: [
      {
        ...document.attributes[0],
        id: "a1",
        value_raw: "1",
        unit_raw: "TB",
        operator_raw: "이상",
      },
    ],
  };
  render(
    <AnalysisExplorer
      value={{ documents: [value] }}
      mappingStatus="available"
      normalization={{
        standard_version: "v2",
        attributes: [
          {
            document_id: "d1",
            attribute_id: "a1",
            status: "applied",
            facts: [
              {
                property_stable_key: "goods.capacity",
                value: { kind: "number", decimal: "1000", unit: "GB" },
              },
            ],
          },
        ],
      }}
    />,
  );
  fireEvent.click(screen.getByRole("treeitem", { name: /프로세서 1개 속성/ }));
  fireEvent.click(screen.getByRole("button", { name: "표준 매핑" }));
  expect(screen.getByText("이상 1", { exact: true })).toBeTruthy();
  expect(screen.getByText("1000 GB", { exact: true })).toBeTruthy();
});
it("moves tree focus independently from selection and expands with arrow keys", () => {
  render(<AnalysisExplorer value={{ documents: [document] }} />);
  const items = screen.getAllByRole("treeitem");
  items[0].focus();
  fireEvent.keyDown(items[0], { key: "ArrowDown" });
  expect(window.document.activeElement).toBe(items[1]);
  expect(items[1].getAttribute("aria-selected")).toBe("true");
  fireEvent.keyDown(items[1], { key: "Home" });
  expect(window.document.activeElement).toBe(items[0]);
  fireEvent.keyDown(items[0], { key: "ArrowLeft" });
  expect(items[0].getAttribute("aria-expanded")).toBe("false");
  fireEvent.keyDown(items[0], { key: "ArrowRight" });
  expect(items[0].getAttribute("aria-expanded")).toBe("true");
});
it("keeps missing standard mappings out of extraction issue counts", () => {
  const complete = {
    ...document,
    attributes: [
      {
        id: "a",
        subject_ids: ["cpu"],
        property_raw: "코어",
        value_raw: "32",
        evidence: { node_id: "n1" },
      },
    ],
    relations: [],
    held_relations: [],
  };
  render(
    <AnalysisExplorer
      value={{ documents: [complete] }}
      mappingStatus="available"
      normalization={{
        attributes: [
          {
            document_id: document.document_id,
            attribute_id: "a",
            status: "automatically_deferred",
          },
        ],
      }}
    />,
  );
  const summary = screen.getByLabelText("규격서 결과 요약");
  expect(within(summary).queryByText("표준 미매핑")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "표준 매핑" }));
  expect(within(summary).getByText("표준 미매핑")).toBeTruthy();
  expect(
    within(summary).getByRole("button", { name: "미해결 항목 0" }),
  ).toBeTruthy();
});

it("opens source verification first, names inventory quantities, and shows all original references together", () => {
  render(<AnalysisExplorer value={{ documents: [{
    document_id: "quantity", entities: [{ id: "item", name: "질량분석기" }], relations: [],
    attributes: [{ id: "q", subject_ids: ["item"], property_key: "quantity", property_raw: null,
      value_raw: "1", unit_raw: "set", evidence: { source_node_ids: ["name", "qty"] } }],
    parsed_document: { nodes: [{ node_id: "name", text: "질량분석기" }, { node_id: "qty", text: "1 set" }] },
  }] }} mappingStatus="available" normalization={{ attributes: [{ document_id: "quantity", attribute_id: "q", status: "automatically_deferred" }] }} />);
  expect(screen.getByRole("button", { name: "추출 결과" }).getAttribute("aria-pressed")).toBe("true");
  const detail = screen.getByRole("region", { name: "분석 대상 상세" });
  const row = within(detail).getByText("수량").closest("tr")!;
  expect(within(row).queryByText("원문 명칭 미기재")).toBeNull();
  expect(within(row).queryByText("내부 식별자")).toBeNull();
  expect(within(row).queryByText("보류·미매핑")).toBeNull();
  fireEvent.click(within(row).getByRole("button", { name: "원문 보기 · 2곳" }));
  const source = screen.getByRole("region", { name: "선택한 원문 근거" });
  const articles = source.querySelectorAll("article");
  expect(articles.length).toBe(2);
  expect(articles[0].textContent).toContain("질량분석기");
  expect(articles[1].textContent).toContain("1 set");
  expect(within(source).getByText("추출 정보").closest("details")?.open).toBe(false);
});

it("highlights the exact source passage and leaves unknown property names for inspection", () => {
  render(<AnalysisExplorer value={{ documents: [{
    document_id: "span", entities: [{ id: "item", name: "CPU" }], relations: [],
    attributes: [{ id: "clock", subject_ids: ["item"], property_key: "unrecognized_clock", value_raw: "3.50",
      unit_raw: "GHz", evidence: { node_id: "spec", char_start: 4, char_end: 11 } }],
    parsed_document: { nodes: [{ node_id: "spec", text: "CPU 3.50GHz 이상", page: 2 }] },
  }] }} />);
  fireEvent.change(screen.getByLabelText("속성 필터"), { target: { value: "unnamed" } });
  const row = screen.getByText("속성명 확인 필요").closest("tr")!;
  fireEvent.keyDown(row, { key: "Enter" });
  const source = screen.getByRole("region", { name: "선택한 원문 근거" });
  expect(source.querySelector("mark")?.textContent).toBe("3.50GHz");
  expect(source.querySelector("article")?.textContent).toContain("2쪽");
});

it("does not repeat source operators already contained in the extracted value", () => {
  const first = render(<AttributeValue attribute={{ value_raw: "±0.1", operator_raw: "±" }} mapping={undefined} standard={false} />);
  expect(first.container.textContent).toBe("±0.1");
  first.unmount();
  const second = render(<AttributeValue attribute={{ value_raw: "2 to 2000", operator_raw: "to", operator: "range" }} mapping={undefined} standard={false} />);
  expect(second.container.textContent).toBe("2 to 2000");
});

it("shows a suggested property name without presenting source descriptions as properties", () => {
  const text = "화합물을 신속하게 스크리닝하는 데 사용된다.";
  render(<AnalysisExplorer value={{ documents: [{
    document_id: "descriptions", entities: [{ id: "root", name: "분석 장치" }], relations: [],
    attributes: [{ id: "a", subject_ids: ["root"], property_raw: null, property_key: "mass_range",
      property_label: "질량 범위", property_label_origin: "model_suggestion", value_raw: "2 to 2000", unit_raw: "m/z",
      evidence: { node_id: "spec" } }],
    requirements: [{ id: "overview", observation_type: "source_clause", category: "description", subject_ids: ["root"],
      text, evidence: [{ node_id: "intro" }] }],
    parsed_document: { nodes: [{ node_id: "spec", text: "m/z 2 to 2000" }, { node_id: "intro", text }] },
  }] }} />);
  const detail = screen.getByRole("region", { name: "분석 대상 상세" });
  expect(within(detail).getByText("물품 설명 · 1").closest("details")?.open).toBe(false);
  expect(within(detail).queryByText("대상별 원문 요구조건 · 1")).toBeNull();
  const table = within(detail).getByRole("table");
  expect(within(table).queryByText(text)).toBeNull();
  fireEvent.click(within(table).getByText("질량 범위").closest("tr")!);
  expect(within(screen.getByRole("region", { name: "선택한 원문 근거" }))
    .getByText(/AI가 해석한 추출명/)).toBeTruthy();
});

it("separates scope from collapsed type filters and only offers observed types", () => {
  render(<AnalysisExplorer value={{ documents: [{
    document_id: "type_filters",
    entities: [
      { id: "root", name: "센서 장치", kind: "equipment" },
      { id: "support", name: "센서 설치", kind: "activity" },
    ],
    relations: [], attributes: [],
  }] }} />);
  const scope = screen.getByLabelText("조회 범위");
  const types = screen.getByLabelText("대상 유형");
  expect(types.closest("details")?.open).toBe(false);
  expect(within(scope).queryByRole("option", { name: "장비" })).toBeNull();
  expect(within(types).getAllByRole("option").map((option) => option.textContent))
    .toEqual(["전체 유형", "장비", "작업"]);
  fireEvent.change(scope, { target: { value: "all" } });
  fireEvent.change(types, { target: { value: "activity" } });
  expect((scope as HTMLSelectElement).value).toBe("all");
  expect(screen.getByRole("treeitem", { name: /센서 설치/ })).toBeTruthy();
  expect(screen.queryByRole("treeitem", { name: /센서 장치/ })).toBeNull();
  fireEvent.change(scope, { target: { value: "goods" } });
  expect((types as HTMLSelectElement).value).toBe("all");
  expect(screen.getByRole("treeitem", { name: /센서 장치/ })).toBeTruthy();
});

it("anchors navigation to supply rows and keeps work-only groups outside supplied composition", () => {
  const value = {
    document_id: "supply_work",
    composition_inventory: { basis: "supply_list", root_id: "root", item_ids: ["sensor", "sender", "job"] },
    entities: [
      { id: "root", name: "環境監視 장치", kind: "equipment" },
      { id: "sender", name: "데이터 전송장치", kind: "equipment", document_roles: ["supply_target"] },
      { id: "sensor", name: "센서 및 분석장치", kind: "equipment", document_roles: ["supply_target"] },
      { id: "gas", name: "환경가스 측정 장치", kind: "equipment" },
      { id: "work", name: "환경감시 센서", kind: "group", document_roles: ["work_scope_target"] },
      { id: "probe", name: "온습도센서", kind: "equipment" },
      { id: "job", name: "센서 교체 및 설치공사", kind: "activity" },
    ],
    relations: [relation("gas", "sensor", "component_of", "interpreted"),
      relation("probe", "work"), relation("job", "work", "service_for")],
    held_relations: [relation("sender", "work")], attributes: [],
  };
  const graph = composition(value, "composition", true);
  expect(graph.roots.map((e) => e.id)).toEqual(["sensor", "sender"]);
  expect(graph.related.map((e) => e.id)).toEqual(["work", "probe", "job"]);
  expect(graph.children.get("sensor")).toEqual(["gas"]);
  render(<AnalysisExplorer value={{ documents: [value] }} />);
  expect(screen.getByRole("heading", { name: "구매 물품·구성" })).toBeTruthy();
  const tree = screen.getByRole("tree", { name: "구성 대상" });
  expect(within(tree).getByRole("treeitem", { name: /데이터 전송장치/ }).getAttribute("aria-level")).toBe("1");
  expect(within(tree).queryByRole("treeitem", { name: /환경감시 센서/ })).toBeNull();
});

it("shows inventory reading uncertainty and does not assign a parent's purchase quantity to a child", () => {
  render(<AnalysisExplorer value={{ documents: [{
    document_id: "inventory_status",
    inventory_assessment: { status: "reading_failed" },
    entities: [{ id: "root", name: "시험장치", kind: "equipment" },
      { id: "sensor", name: "측정센서", kind: "equipment" }],
    relations: [relation("sensor", "root")],
    declared_quantities: [{ entity_id: "root", value_raw: "8", unit_raw: "식" }],
    attributes: [],
  }] }} />);
  expect(screen.getByLabelText("구매 기준 확인 상태").textContent).toBe("기준 목록 판독 확인 필요");
  fireEvent.click(screen.getByRole("treeitem", { name: /^측정센서/ }));
  const detail = screen.getByRole("region", { name: "분석 대상 상세" });
  expect(within(detail).getByText("구매 기준 수량: 별도 기재 없음")).toBeTruthy();
  expect(within(detail).queryByText(/8 식/)).toBeNull();
});

it("uses the sole purchased server as root even when the inventory has no extra purchase rows", () => {
  const value = {
    document_id: "single_server", classification_code: "4321150102",
    composition_inventory: { basis: "supply_list", root_id: "root", item_ids: [] },
    entities: [
      { id: "root", name: "대형언어모델 추론실험용 서버", kind: "equipment", document_roles: ["procurement_scope", "supply_target"] },
      { id: "cpu", name: "CPU", kind: "equipment" },
      { id: "ram", name: "메모리", kind: "equipment" },
      { id: "gpu", name: "GPU", kind: "equipment" },
    ],
    relations: [relation("cpu", "root"), relation("ram", "root"), relation("gpu", "root")], attributes: [],
  };
  const graph = composition(value, "composition", true);
  expect(graph.roots.map((e) => e.id)).toEqual(["root"]);
  expect(graph.children.get("root")).toEqual(["cpu", "ram", "gpu"]);
  render(<AnalysisExplorer value={{ documents: [value] }} />);
  expect(screen.getByRole("treeitem", { name: /^대형언어모델 추론실험용 서버/ }).getAttribute("aria-level")).toBe("1");
  expect(screen.getByRole("treeitem", { name: /^메모리/ }).getAttribute("aria-level")).toBe("2");
});

it("keeps purchased upgrade parts as independent roots and the existing server as a related target", () => {
  const value = {
    document_id: "upgrade", classification_code: "4321150102",
    composition_inventory: { basis: "supply_list", root_id: "scope", item_ids: ["gpu", "ram"] },
    entities: [
      { id: "scope", name: "서버 증설 구매", kind: "group", document_roles: ["procurement_scope"] },
      { id: "gpu", name: "GPU", kind: "equipment", document_roles: ["supply_target"] },
      { id: "ram", name: "메모리", kind: "equipment", document_roles: ["supply_target"] },
      { id: "old", name: "기존 서버", kind: "equipment", document_roles: ["existing_target"] },
    ],
    relations: [relation("gpu", "old"), relation("ram", "old", "physical_part_of")], attributes: [],
  };
  for (const primaryOnly of [true, false]) {
    const graph = composition(value, "composition", primaryOnly);
    expect(graph.roots.map((e) => e.id)).toEqual(["gpu", "ram"]);
    expect(graph.scopes.map((e) => e.id)).toEqual(["scope"]);
  }
  render(<AnalysisExplorer value={{ documents: [value] }} />);
  const tree=screen.getByRole("tree", { name: "구성 대상" });
  expect(within(tree).queryByRole("treeitem", { name: /기존 서버/ })).toBeNull();
  expect(within(tree).queryByRole("treeitem", { name: /서버 증설 구매/ })).toBeNull();
  expect(screen.getByText("구매 범위·공통 규격 · 1").closest("details")?.open).toBe(false);
});

it("does not start again at a purchased component when a purchased parent is known", () => {
  const value = {
    composition_inventory: { basis: "supply_list", root_id: "server", item_ids: ["server", "gpu"] },
    entities: [
      { id: "server", name: "서버", kind: "equipment", document_roles: ["supply_target"] },
      { id: "gpu", name: "GPU", kind: "equipment", document_roles: ["supply_target"] },
    ], relations: [relation("gpu", "server")],
  };
  const graph=composition(value, "composition", true);
  expect(graph.roots.map((e) => e.id)).toEqual(["server"]);
  expect(graph.children.get("server")).toEqual(["gpu"]);
});

it("never invents a server from classification or a title when purchase identity is unconfirmed", () => {
  const value = {
    classification_code: "4321150102",
    composition_inventory: { basis: "unresolved", root_id: "scope", item_ids: [] },
    entities: [
      { id: "scope", name: "서버 구매 사업", kind: "equipment", document_roles: ["procurement_scope"] },
      { id: "gpu", name: "GPU", kind: "equipment" },
    ], relations: [],
  };
  const graph=composition(value, "composition", true);
  expect(graph.roots).toEqual([]);
  expect(graph.unclassified.map((e) => e.id)).toEqual(["gpu"]);
  expect(graph.scopes.map((e) => e.id)).toEqual(["scope"]);
});

it("keeps a purchase target with an ambiguous parent in review instead of promoting it", () => {
  const graph=composition({
    composition_inventory: { basis: "supply_list", root_id: "scope", item_ids: ["gpu"] },
    entities: [
      { id: "scope", name: "증설 구매", kind: "group", document_roles: ["procurement_scope"] },
      { id: "gpu", name: "GPU", kind: "equipment", document_roles: ["supply_target"] },
      { id: "parent", name: "설비", kind: "equipment" },
    ], relations: [], held_relations: [relation("gpu", "parent", "component_of", "ambiguous")],
  }, "composition", true);
  expect(graph.roots).toEqual([]);
  expect(graph.unclassified.map((e) => e.id)).toContain("gpu");
});
