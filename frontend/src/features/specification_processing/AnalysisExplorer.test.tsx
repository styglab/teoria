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
  fireEvent.click(screen.getByRole("button", { name: /프로세서 1개 속성/ }));
  const detail = screen.getByRole("region", { name: "분석 대상 상세" });
  expect(within(detail).getByText("코어 수")).toBeTruthy();
  expect(within(detail).getByText("2 개", { exact: true })).toBeTruthy();
  expect(within(detail).getByText("32", { exact: true })).toBeTruthy();
  fireEvent.click(
    within(detail).getAllByRole("button", { name: "원문 근거 n1" })[0],
  );
  expect(screen.getByText("프로세서는 32코어 이상")).toBeTruthy();
  expect(screen.getByRole("heading", { name: "대상 목록" })).toBeTruthy();
  fireEvent.change(screen.getByLabelText("분석 대상 검색"), {
    target: { value: "설치" },
  });
  expect(
    screen.getByRole("button", { name: /설치 작업 0개 속성/ }),
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
  fireEvent.change(screen.getByLabelText("분석 문서"), {
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
  fireEvent.click(screen.getByRole("button", { name: /프로세서 1개 속성/ }));
  expect(screen.queryByText("cpu_core_count")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "표준 매핑 비교" }));
  expect(screen.getByText("cpu_core_count")).toBeTruthy();
  expect(screen.queryByText("wrong_standard")).toBeNull();
  expect(screen.getByText("연결됨", { exact: true })).toBeTruthy();
  expect(
    screen.getByText(/사람의 검토·승인 상태를 나타내지 않습니다/),
  ).toBeTruthy();
});
it("distinguishes mapping failure from unmapped and opens evidence from the selected row", () => {
  render(
    <AnalysisExplorer
      value={{ documents: [document] }}
      mappingStatus="error"
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: /프로세서 1개 속성/ }));
  fireEvent.click(screen.getByRole("button", { name: "표준 매핑 비교" }));
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
      relation("cpu", "root"), relation("task", "root", "service_for"),
      relation("sw", "root", "software_for"), relation("manual", "root", "document_for"),
      relation("manual", "root"), relation("sw", "root"),
    ],
    requirements: [{ id: "clause", subject_ids: ["manual"], observation_type: "source_clause",
      text: "설치 작업의 종료와 함께 다음의 문서를 제출하여야 한다.", evidence }],
  };
  const graph = composition(value);
  expect(graph.children.get("root")).toEqual(["cpu"]);
  render(<AnalysisExplorer value={{ documents: [value] }} />);
  fireEvent.change(screen.getByLabelText("대상 유형"), { target: { value: "software" } });
  expect(screen.getByRole("button", { name: /Docker 0개 속성/ })).toBeTruthy();
  expect(screen.queryByRole("button", { name: /설치 작업 0개 속성/ })).toBeNull();
  fireEvent.change(screen.getByLabelText("대상 유형"), { target: { value: "all" } });
  fireEvent.click(screen.getByRole("button", { name: /HW\/SW 설치 및 사용 매뉴얼 0개 속성/ }));
  expect(screen.getByText(/문서 대상 · 명시/)).toBeTruthy();
  expect(screen.getByText("설치 작업의 종료와 함께 다음의 문서를 제출하여야 한다.")).toBeTruthy();
  expect(screen.queryByText(/미분류 항목/)).toBeNull();
});

it("starts with independent food items and offers packaging separately from composition", () => {
  const milk = { document_id: "milk", inventory_ids: ["large", "small"],
    entities: [
      { id: "scope", name: "급식 물품", kind: "group" },
      { id: "large", name: "우유/대", kind: "product" },
      { id: "small", name: "우유/소", kind: "product" },
      { id: "box", name: "상자", kind: "product" },
      { id: "paper", name: "종이", kind: "material" },
    ], relations: [relation("large", "scope", "in_procurement_scope"),
      relation("small", "scope", "in_procurement_scope"),
      relation("large", "box", "pack_unit_of"), relation("paper", "large", "packaging_for")],
    attributes: [],
  };
  expect(composition(milk).children.size).toBe(0);
  expect(composition(milk, "packaging").children.get("box")).toEqual(["large"]);
  render(<AnalysisExplorer value={{ documents: [milk] }} />);
  expect((screen.getByRole("combobox", { name: "탐색 방식" }) as HTMLSelectElement).value).toBe("list");
  expect(screen.getByRole("heading", { name: "대상 목록" })).toBeTruthy();
  expect(screen.getByRole("heading", { name: "우유/대" })).toBeTruthy();
  fireEvent.change(screen.getByLabelText("대상 유형"), { target: { value: "purchase" } });
  expect(screen.getByRole("button", { name: /우유\/소 0개 속성/ })).toBeTruthy();
  expect(screen.queryByRole("button", { name: /상자 0개 속성/ })).toBeNull();
  fireEvent.change(screen.getByLabelText("대상 유형"), { target: { value: "all" } });
  fireEvent.change(screen.getByLabelText("탐색 방식"), { target: { value: "packaging" } });
  expect(screen.getByRole("heading", { name: "포장 단위 관계" })).toBeTruthy();
  expect(screen.getByRole("button", { name: "상자 접기" })).toBeTruthy();
});

it("keeps a standalone software purchase visible without manufacturing hardware or inventory children", () => {
  render(<AnalysisExplorer value={{ documents: [{ document_id: "cad", inventory_ids: [],
    entities: [{ id: "root", name: "CAD 소프트웨어", kind: "software", document_roles: ["procurement_scope"] }],
    relations: [], attributes: [] }] }} />);
  fireEvent.change(screen.getByLabelText("대상 유형"), { target: { value: "purchase" } });
  expect(screen.getByRole("button", { name: /CAD 소프트웨어 0개 속성/ })).toBeTruthy();
  expect(screen.queryByText(/확인된 구성 계층/)).toBeNull();
});
