import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { adminApi, type MetadataTableSamples } from "../../api/admin";
import { TableDataEvidence } from "./TableDataEvidence";

afterEach(() => { cleanup(); vi.restoreAllMocks(); });
const sample: MetadataTableSamples = {
  available: true, columns: ["identifier"], rows: [["[REDACTED]"]], stored_row_count: 1,
  truncated: false, values_included: false, reason: null, scope: "stored_sample",
};

test("fetches masked samples only on request and reports missing profile", async () => {
  const samples = vi.spyOn(adminApi, "metadataTableSamples").mockResolvedValue(sample);
  vi.spyOn(adminApi, "metadataTableProfile").mockResolvedValue({available: false, table_metrics: {}, column_metrics: [], reason: "not_collected"});
  render(<TableDataEvidence tableId="table-1" />);
  expect(samples).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "샘플 확인" }));
  await waitFor(() => expect(screen.getByText("[REDACTED]")).toBeInTheDocument());
  expect(samples).toHaveBeenCalledWith("table-1", false);
  fireEvent.click(screen.getByRole("button", { name: "프로파일 확인" }));
  await waitFor(() => expect(screen.getByText("수집된 프로파일이 없습니다.")).toBeInTheDocument());
});

test("clears sample values after a permission failure", async () => {
  vi.spyOn(adminApi, "metadataTableSamples")
    .mockResolvedValueOnce({ ...sample, rows: [["synthetic-value"]], values_included: true })
    .mockRejectedValueOnce(new Error("샘플 값을 조회할 권한이 없습니다."));
  render(<TableDataEvidence tableId="table-1" />);
  fireEvent.click(screen.getByRole("button", { name: "샘플 값 보기" }));
  await waitFor(() => expect(screen.getByText("synthetic-value")).toBeInTheDocument());
  fireEvent.click(screen.getByRole("button", { name: "샘플 값 보기" }));
  await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
  expect(screen.queryByText("synthetic-value")).not.toBeInTheDocument();
});

test("does not render a previous table's late sample response", async () => {
  let resolveOld!: (value: MetadataTableSamples) => void;
  vi.spyOn(adminApi, "metadataTableSamples").mockImplementation(() => new Promise(resolve => { resolveOld = resolve; }));
  const view = render(<TableDataEvidence tableId="table-1" />);
  fireEvent.click(screen.getByRole("button", { name: "샘플 확인" }));
  view.rerender(<TableDataEvidence tableId="table-2" />);
  resolveOld({ ...sample, rows: [["previous-table-value"]] });
  await waitFor(() => expect(screen.getByRole("button", { name: "샘플 확인" })).not.toBeDisabled());
  expect(screen.queryByText("previous-table-value")).not.toBeInTheDocument();
});
