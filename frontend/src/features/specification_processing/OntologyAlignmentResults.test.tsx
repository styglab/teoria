import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { OntologyAlignmentResults } from "./OntologyAlignmentResults";

afterEach(cleanup);

it("shows proposals and unresolved observations separately from approved links", () => {
  const source = vi.fn();
  const document = { document_id: "d", entities: [{ id: "e", name: "진공펌프" }],
    attributes: [{ id: "a", property_raw: "출력" }], relations: [] };
  render(<OntologyAlignmentResults document={document} sourceButton={row => <button onClick={() => source(row)}>원문 보기</button>}
    normalization={{ ontology_alignment: { observations: [
      { document_id: "d", kind: "entity", observation_id: "e", status: "proposed", concept_label: "펌프", baseline: null },
      { document_id: "d", kind: "attribute", observation_id: "a", status: "held", reason: "property_owner_mismatch", baseline: {concept_id: "stable"}, baseline_concept_label: "기존 출력" },
      { document_id: "another", kind: "entity", observation_id: "secret", status: "proposed", concept_label: "다른 문서" },
    ] } }} />);
  fireEvent.click(screen.getByText("Ontology 의미 연결 비교 · 2건"));
  expect(screen.getByText("연결 검토 제안")).toBeTruthy();
  expect(screen.getByText("속성의 소유 대상이 다릅니다")).toBeTruthy();
  expect(screen.getByText("기존 출력")).toBeTruthy();
  expect(screen.queryByText("다른 문서")).toBeNull();
  expect(screen.getByText(/정확도 점수가 아닙니다/)).toBeTruthy();
  fireEvent.click(screen.getAllByRole("button", {name: "원문 보기"})[0]);
  expect(source).toHaveBeenCalledWith(document.entities[0]);
});

it("does not imply a missing comparison when this optional feature was not used", () => {
  const {container} = render(<OntologyAlignmentResults document={{}} sourceButton={() => null} />);
  expect(container.innerHTML).toBe("");
});
