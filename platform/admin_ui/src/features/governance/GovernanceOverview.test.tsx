import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";
import { adminApi } from "../../api/admin";
import { GovernanceOverview } from "./GovernanceOverview";

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

test("reports governance gaps from current OpenMetadata assets", async () => {
  vi.spyOn(adminApi, "metadataTables").mockResolvedValue({
    items: [
      { reference: { system: "openmetadata", entity_id: "one", entity_type: "table", fully_qualified_name: "svc.db.one", version: null }, name: "one", display_name: null, description: null, owners: [], tags: [], domains: [] },
      { reference: { system: "openmetadata", entity_id: "two", entity_type: "table", fully_qualified_name: "svc.db.two", version: null }, name: "two", display_name: null, description: "설명", owners: [{ name: "owner" }], tags: [{ tagFQN: "PII.None" }], domains: [] },
    ],
    total: 2,
    after: null,
    before: null,
  });
  render(<MemoryRouter><GovernanceOverview /></MemoryRouter>);
  expect(await screen.findByRole("heading", { name: "메타데이터 공백" })).toBeInTheDocument();
  expect(screen.getByText("전체 자산").parentElement).toHaveTextContent("2");
  expect(screen.getByText("소유자 미지정").parentElement).toHaveTextContent("1");
  expect(screen.getByRole("link", { name: /분류 공백 확인/ })).toHaveAttribute("href", "/admin/data-catalog?filter=tags");
});
