import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { ProcessingStagesSummary } from "./ProcessingStagesSummary";

afterEach(cleanup);

it("keeps completed extraction separate from pending meaning and draft application", () => {
  render(
    <ProcessingStagesSummary
      stages={{
        schema_version: 1,
        extraction: { status: "completed", counts: {} },
        expression_registration: {
          status: "completed",
          counts: { approved: 4 },
        },
        meaning: {
          status: "review_required",
          counts: { comparison_observations: 2 },
        },
        application: {
          status: "completed",
          basis: "extraction_draft",
          counts: {},
        },
      }}
    />,
  );
  const row = (name: string) => within(screen.getByText(name).parentElement!);
  expect(row("원문 추출").getByText("완료")).toBeTruthy();
  expect(row("의미 연결").getByText("검토 필요")).toBeTruthy();
  expect(row("기준 적용").getByText("완료 · 추출 규칙 초안")).toBeTruthy();
  expect(screen.getByText(/Ontology 비교 2건은 제안/)).toBeTruthy();
  expect(screen.getByText(/Ontology 의미 승인·게시와 별개/)).toBeTruthy();
});

it("does not infer approval or extraction quality for historical runs", () => {
  render(<ProcessingStagesSummary />);
  expect(screen.getByText(/단계별 상태가 기록되지 않은 실행/)).toBeTruthy();
  expect(screen.queryByText("연결 확인")).toBeNull();
  expect(screen.queryByText("완료")).toBeNull();
});
