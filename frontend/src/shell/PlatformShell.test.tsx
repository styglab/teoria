import "@testing-library/jest-dom/vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { capabilityApi } from "../platform/ontology/runtime/capability/api";
import { registryApi } from "../platform/ontology/runtime/capability/api";
import { metadataApi } from "../platform/data/metadata/catalog/api";
import { authApi } from "../platform/access_control/api";
import { workflowsApi } from "../platform/workflow_management/api";
import { modelOperationsApi } from "../platform/mlops/api";
import { PlatformShell } from "./PlatformShell";
import { deploymentApi } from "../platform/access_control/DeploymentAvailability";
beforeEach(() => {
  vi.spyOn(deploymentApi, "status").mockResolvedValue({
    semantic: true,
    formatid: true,
    mlops: true,
  });
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  window.sessionStorage.clear();
});
test("a registry API failure does not block the metadata catalog", async () => {
  vi.spyOn(capabilityApi, "capabilities").mockRejectedValue(
    new Error("unavailable"),
  );
  vi.spyOn(registryApi, "sources").mockResolvedValue({ sources: [] });
  vi.spyOn(registryApi, "mappings").mockResolvedValue({ mappings: [] });
  vi.spyOn(registryApi, "lineage").mockResolvedValue({ links: [] });
  vi.spyOn(registryApi, "validation").mockResolvedValue({
    status: "valid",
    diagnostic_count: 0,
    diagnostics: [],
  });
  vi.spyOn(registryApi, "registryRelease").mockResolvedValue({
    version: "test",
    status: "published",
  } as never);
  vi.spyOn(metadataApi, "metadataSchemas").mockResolvedValue({
    items: [],
    total: 0,
    after: null,
    before: null,
  });
  vi.spyOn(metadataApi, "metadataStatus").mockResolvedValue({
    enabled: true,
    available: true,
    provider: "openmetadata",
    base_url: null,
    database_service: "service",
    reason: null,
  });
  vi.spyOn(metadataApi, "metadataTables").mockResolvedValue({
    items: [],
    total: 0,
    after: null,
    before: null,
  });
  render(
    <MemoryRouter initialEntries={["/admin/data-catalog"]}>
      <PlatformShell />
    </MemoryRouter>,
  );
  expect(
    await screen.findByRole("heading", { name: "전체 자산" }),
  ).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Teoria 개요" })).toHaveAttribute(
    "href",
    "/admin/overview",
  );
  expect(screen.getByRole("button", { name: "데이터" })).toHaveAttribute(
    "aria-expanded",
    "true",
  );
  fireEvent.click(screen.getByRole("button", { name: "Ontology" }));
  expect(screen.getByRole("link", { name: /데이터 자산/ })).toHaveAttribute(
    "href",
    "/admin/data-catalog",
  );
  expect(screen.getByRole("link", { name: /온톨로지/ })).toHaveAttribute(
    "href",
    "/admin/semantic-model/ontology",
  );
  expect(
    screen.queryByRole("link", { name: "메타데이터 공백" }),
  ).not.toBeInTheDocument();
  expect(screen.getByRole("link", { name: /검토함/ })).toHaveAttribute(
    "href",
    "/admin/changes/review",
  );
  expect(screen.queryByText("unavailable")).not.toBeInTheDocument();
});

function mockWorkspace(modelEnabled = true) {
  vi.spyOn(capabilityApi, "capabilities").mockResolvedValue({
    capabilities: [],
  });
  vi.spyOn(registryApi, "sources").mockResolvedValue({ sources: [] });
  vi.spyOn(registryApi, "mappings").mockResolvedValue({ mappings: [] });
  vi.spyOn(registryApi, "lineage").mockResolvedValue({ links: [] });
  vi.spyOn(registryApi, "validation").mockResolvedValue({
    status: "valid",
    diagnostic_count: 0,
    diagnostics: [],
  });
  vi.spyOn(registryApi, "registryRelease").mockResolvedValue({
    version: "test",
    status: "published",
  } as never);
  vi.spyOn(metadataApi, "metadataSchemas").mockResolvedValue({
    items: [],
    total: 0,
    after: null,
    before: null,
  });
  vi.spyOn(metadataApi, "metadataStatus").mockResolvedValue({
    enabled: true,
    available: true,
    provider: "openmetadata",
    base_url: null,
    database_service: "service",
    reason: null,
  });
  vi.spyOn(metadataApi, "metadataTables").mockResolvedValue({
    items: [],
    total: 0,
    after: null,
    before: null,
  });
  window.sessionStorage.setItem("teoria-admin-token", "synthetic-test-token");
  vi.spyOn(authApi, "session").mockResolvedValue({
    actor: "test:admin",
    roles: ["metadata_admin"],
  });
  vi.spyOn(modelOperationsApi, "status").mockResolvedValue({
    enabled: modelEnabled,
  });
  vi.spyOn(modelOperationsApi, "pipelines").mockResolvedValue({
    enabled: modelEnabled,
    items: [],
    runs: [],
  });
  vi.spyOn(workflowsApi, "pipelines").mockResolvedValue({
    enabled: true,
    items: [],
    runs: [],
  });
  vi.spyOn(modelOperationsApi, "deployments").mockResolvedValue({ items: [] });
  vi.spyOn(modelOperationsApi, "models").mockResolvedValue({
    model_name: "demo",
    registered_models: [],
    items: [],
  });
}
test("registry and serving routes have separate menus and screens", async () => {
  mockWorkspace();
  render(
    <MemoryRouter initialEntries={["/admin/models"]}>
      <PlatformShell />
    </MemoryRouter>,
  );
  expect(
    await screen.findByRole("heading", { name: "모델 레지스트리", level: 2 }),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "추론 실행" }),
  ).not.toBeInTheDocument();
  fireEvent.click(await screen.findByRole("link", { name: "추론 서비스" }));
  expect(
    await screen.findByRole("heading", { name: "모델 서빙", level: 1 }),
  ).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "추론 테스트" })).not.toBeInTheDocument();
  expect(screen.queryByText("고객 이탈 예측")).not.toBeInTheDocument();
  expect(
    screen.queryByRole("heading", { name: "등록 모델 버전" }),
  ).not.toBeInTheDocument();
  expect(screen.queryByText("Registry 검증됨")).not.toBeInTheDocument();
});
function LocationProbe() {
  const location = useLocation();
  return (
    <output data-testid="location">
      {location.pathname + location.search + location.hash}
    </output>
  );
}
test("old combined model links redirect without losing their query or fragment", async () => {
  mockWorkspace();
  render(
    <MemoryRouter
      initialEntries={["/admin/model-operations?source=bookmark#versions"]}
    >
      <PlatformShell />
      <LocationProbe />
    </MemoryRouter>,
  );
  await waitFor(() =>
    expect(screen.getByTestId("location")).toHaveTextContent(
      "/admin/models?source=bookmark#versions",
    ),
  );
  expect(
    await screen.findByRole("heading", { name: "모델 레지스트리", level: 2 }),
  ).toBeInTheDocument();
});
test("mobile navigation overlays the workspace and closes after navigation", async () => {
  const original = window.innerWidth;
  Object.defineProperty(window, "innerWidth", {
    value: 390,
    configurable: true,
  });
  try {
    mockWorkspace(false);
    render(
      <MemoryRouter initialEntries={["/admin/data-catalog"]}>
        <PlatformShell />
      </MemoryRouter>,
    );
    expect(
      await screen.findByRole("heading", { name: "전체 자산" }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "탐색 메뉴 열기" }));
    expect(
      screen.getByRole("button", { name: "메뉴 닫기" }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("link", { name: "데이터 자산" }));
    await waitFor(() =>
      expect(
        screen.queryByRole("button", { name: "메뉴 닫기" }),
      ).not.toBeInTheDocument(),
    );
  } finally {
    Object.defineProperty(window, "innerWidth", {
      value: original,
      configurable: true,
    });
  }
});
