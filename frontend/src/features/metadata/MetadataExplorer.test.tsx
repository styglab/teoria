import "@testing-library/jest-dom/vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { metadataApi } from "../../api/metadata";
import { authApi } from "../../api/auth";
import { AdminApiError } from "../../api/http_client";
import { AdminAccessProvider } from "../access/AdminAccess";
import { MetadataExplorer } from "./MetadataExplorer";
const available = {
  enabled: true,
  available: true,
  provider: "openmetadata" as const,
  base_url: null,
  database_service: "service",
  reason: null,
};
const table = {
  reference: {
    system: "openmetadata" as const,
    entity_id: "asset",
    entity_type: "table",
    fully_qualified_name: "service.db.schema.hidden",
    version: null,
  },
  name: "hidden",
  display_name: null,
  description: "설명",
  tags: [],
  owners: [{ name: "Metadata Team" }],
  domains: [],
};
beforeEach(() => {
  vi.spyOn(metadataApi, "metadataStatus").mockResolvedValue(available);
  vi.spyOn(metadataApi, "metadataSchemas").mockResolvedValue({
    items: [],
    total: 0,
    after: null,
    before: null,
  });
  vi.spyOn(metadataApi, "tableCounts").mockResolvedValue({
    all: 51,
    description: 20,
    owner: 3,
    tags: 40,
  });
  vi.spyOn(metadataApi, "searchTables").mockResolvedValue({
    items: [table],
    total: 51,
    after: null,
    before: null,
  });
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  window.sessionStorage.clear();
});
function show(entry = "/") {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <AdminAccessProvider>
        <MetadataExplorer />
      </AdminAccessProvider>
    </MemoryRouter>,
  );
}
test("uses the shared login for structured unauthorized errors and refreshes after authentication", async () => {
  vi.mocked(metadataApi.metadataStatus).mockRejectedValueOnce(
    new AdminApiError("로그인이 필요합니다", 401),
  );
  vi.spyOn(authApi, "session").mockResolvedValue({
    actor: "reviewer",
    roles: ["metadata_admin"],
  });
  show();
  expect(
    await screen.findByText("관리자 인증이 필요합니다"),
  ).toBeInTheDocument();
  fireEvent.click(screen.getAllByRole("button", { name: "관리자 연결" })[0]);
  const input = screen.getByLabelText("관리자 토큰");
  expect(input).toHaveAttribute("type", "password");
  fireEvent.change(input, { target: { value: "Bearer synthetic-token" } });
  fireEvent.click(screen.getByRole("button", { name: "연결" }));
  expect(await screen.findByText("Metadata Team")).toBeInTheDocument();
  expect(screen.getByText("관리자 · reviewer")).toBeInTheDocument();
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});
test("requests only the selected server page and does not scan all table pages", async () => {
  const scan = vi.spyOn(metadataApi, "metadataTables");
  show("/?page=1&size=25");
  await screen.findByText("Metadata Team");
  expect(metadataApi.searchTables).toHaveBeenCalledWith(
    expect.objectContaining({ offset: 25, limit: 25 }),
    expect.any(AbortSignal),
  );
  expect(scan).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "다음 페이지" }));
  await waitFor(() =>
    expect(metadataApi.searchTables).toHaveBeenLastCalledWith(
      expect.objectContaining({ offset: 50 }),
      expect.any(AbortSignal),
    ),
  );
  expect(metadataApi.tableCounts).toHaveBeenCalledTimes(1);
});
test("search and missing-owner filters run on the server and reset pagination", async () => {
  show("/?page=1");
  await screen.findByText("Metadata Team");
  vi.mocked(metadataApi.searchTables).mockResolvedValue({
    items: [],
    total: 0,
    after: null,
    before: null,
  });
  fireEvent.change(screen.getByRole("textbox", { name: "전체 자산 검색" }), {
    target: { value: "beyond first page" },
  });
  await waitFor(() =>
    expect(metadataApi.searchTables).toHaveBeenLastCalledWith(
      expect.objectContaining({ query: "beyond first page", offset: 0 }),
      expect.any(AbortSignal),
    ),
  );
  fireEvent.click(screen.getByRole("button", { name: /^소유자 미지정/ }));
  await waitFor(() =>
    expect(metadataApi.searchTables).toHaveBeenLastCalledWith(
      expect.objectContaining({
        missing: "owner",
        query: "beyond first page",
        offset: 0,
      }),
      expect.any(AbortSignal),
    ),
  );
  expect(
    await screen.findByText("조건에 맞는 자산이 없습니다."),
  ).toBeInTheDocument();
});
test("cancels stale searches and preserves authoritative schema filtering", async () => {
  vi.mocked(metadataApi.metadataSchemas).mockResolvedValue({
    items: [
      {
        ...table,
        name: "schema",
        reference: {
          ...table.reference,
          entity_type: "databaseSchema",
          fully_qualified_name: "service.db.schema",
        },
      },
    ],
    total: 1,
    after: null,
    before: null,
  });
  show();
  await screen.findByText("Metadata Team");
  const signal = vi.mocked(metadataApi.searchTables).mock.calls[0][1]!;
  fireEvent.click(screen.getByRole("button", { name: /^schema/ }));
  expect(signal.aborted).toBe(true);
  await waitFor(() =>
    expect(metadataApi.searchTables).toHaveBeenLastCalledWith(
      expect.objectContaining({ databaseSchema: "service.db.schema" }),
      expect.any(AbortSignal),
    ),
  );
});
test("does not report search failure as an empty catalog", async () => {
  vi.mocked(metadataApi.searchTables).mockRejectedValue(
    new Error("source unavailable"),
  );
  show();
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "source unavailable",
  );
  expect(screen.queryByText("등록된 자산이 없습니다.")).not.toBeInTheDocument();
});
test("count failure leaves the independently loaded catalog available", async () => {
  vi.mocked(metadataApi.tableCounts).mockRejectedValue(
    new Error("count unavailable"),
  );
  show();
  expect(await screen.findByText("Metadata Team")).toBeInTheDocument();
  expect(
    await screen.findByText(/누락 항목 집계를 조회하지 못했습니다/),
  ).toBeInTheDocument();
});
