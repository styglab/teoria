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
  const detail = screen.getByRole("region", { name: "구성품 상세" });
  expect(within(detail).getByText("코어 수")).toBeTruthy();
  expect(within(detail).getByText("2 개", { exact: true })).toBeTruthy();
  expect(within(detail).getByText("32", { exact: true })).toBeTruthy();
  fireEvent.click(
    within(detail).getAllByRole("button", { name: "원문 근거 n1" })[0],
  );
  expect(screen.getByText("프로세서는 32코어 이상")).toBeTruthy();
  expect(screen.getByText(/미분류 항목 · 1/)).toBeTruthy();
  fireEvent.change(screen.getByLabelText("구성품 검색"), {
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
