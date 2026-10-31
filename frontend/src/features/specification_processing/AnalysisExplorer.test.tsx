import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { AnalysisExplorer, composition } from "./AnalysisExplorer";
afterEach(cleanup);
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
    within(detail).getAllByRole("button", { name: "원문 근거 n1" })[0],
  );
  expect(screen.getByText("프로세서는 32코어 이상")).toBeTruthy();
  expect(screen.getByRole("heading", { name: "구성 관계" })).toBeTruthy();
  fireEvent.change(screen.getByLabelText("대상 유형"), {
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
it("never turns scope, interpreted, cyclic, or multiple-parent relations into composition", () => {
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
  expect(graph.children.size).toBe(0);
  expect(graph.unclassified).toHaveLength(6);
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
  expect(screen.getByText("cpu_core_count")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "표준 적용 결과" }));
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
  fireEvent.click(screen.getByRole("button", { name: "표준 적용 결과" }));
  expect(screen.getByText("조회 실패", { exact: true })).toBeTruthy();
  const row = screen.getByText("코어 수").closest("tr")!;
  fireEvent.keyDown(row, { key: "Enter" });
  expect(row.getAttribute("aria-selected")).toBe("true");
  expect(screen.getByText("프로세서는 32코어 이상")).toBeTruthy();
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
  expect(screen.getByRole("heading", { name: "문서 속성 · 1" })).toBeTruthy();
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
  fireEvent.change(screen.getByLabelText("대상 유형"), {
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
  fireEvent.change(screen.getByLabelText("대상 유형"), {
    target: { value: "purchase" },
  });
  expect(
    screen.getByRole("treeitem", { name: /우유\/소 0개 속성/ }),
  ).toBeTruthy();
  expect(screen.queryByRole("button", { name: /상자 0개 속성/ })).toBeNull();
  fireEvent.change(screen.getByLabelText("대상 유형"), {
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
  fireEvent.change(screen.getByLabelText("대상 유형"), {
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
  expect((screen.getByLabelText("대상 유형") as HTMLSelectElement).value).toBe(
    "all",
  );
  expect(
    screen.getByRole("treeitem", { name: /설치 작업 0개 속성/ }),
  ).toBeTruthy();
  fireEvent.click(
    within(
      within(detail).getByText("기타 요구사항 · 1").closest("details")!,
    ).getByRole("button", { name: "원문 근거 n1" }),
  );
  expect(screen.getByText("프로세서는 32코어 이상")).toBeTruthy();
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
  expect(summary.textContent).toContain("엔티티 3");
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
  expect(within(issues).getByText(/방향이 불명확함/)).toBeTruthy();
  fireEvent.click(
    within(issues).getByRole("button", { name: "속성 원문 확인" }),
  );
  expect(screen.getByText("프로세서는 32코어 이상")).toBeTruthy();
  expect(screen.queryByRole("button", { name: /승인|반려/ })).toBeNull();
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
  fireEvent.click(screen.getByRole("button", { name: "표준 적용 결과" }));
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
  expect(within(summary).getByText("표준 미매핑")).toBeTruthy();
  expect(
    within(summary).getByRole("button", { name: "미해결 항목 0" }),
  ).toBeTruthy();
});
