import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import {
  DeploymentAvailability,
  deploymentApi,
} from "../platform/access_control/DeploymentAvailability";
import { WorkspaceChoices } from "./WorkspaceChoices";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

it.each([
  { semantic: true, mlops: true, formatid: true, enabled: true },
  { semantic: true, mlops: false, formatid: false, enabled: false },
  { semantic: false, mlops: true, formatid: false, enabled: true },
  { semantic: false, mlops: true, formatid: false, enabled: false },
  { semantic: false, mlops: false, formatid: true, enabled: false },
])("offers only usable workspaces: %j", async ({ enabled, ...modules }) => {
  vi.spyOn(deploymentApi, "status").mockResolvedValue(modules);
  render(
    <MemoryRouter>
      <DeploymentAvailability>
        <WorkspaceChoices modelOperationsEnabled={enabled} />
        <span>loaded</span>
      </DeploymentAvailability>
    </MemoryRouter>,
  );
  await screen.findByText("loaded");
  expect(!!screen.queryByRole("navigation", { name: "데이터 시작" })).toBe(
    modules.semantic,
  );
  expect(!!screen.queryByRole("navigation", { name: "Ontology 시작" })).toBe(
    modules.semantic,
  );
  expect(!!screen.queryByRole("navigation", { name: "MLOps 시작" })).toBe(
    modules.mlops && enabled,
  );
  if (modules.formatid || modules.semantic) {
    expect(
      screen.getByRole("link", { name: "물품 사전" }).getAttribute("href"),
    ).toBe("/admin/domains/goods/dictionary");
  }
  if (modules.semantic) {
    expect(
      screen
        .getByRole("link", { name: "실행 계약·Capability" })
        .getAttribute("href"),
    ).toBe("/admin/developer/capabilities");
  }
  expect(screen.queryByRole("link", { name: "파이프라인" })).toBeNull();
  expect(screen.queryByRole("link", { name: "FormatID" })).toBeNull();
});

it.each([
  { metadata: true, ontology: false, mlops: false },
  { metadata: false, ontology: true, mlops: false },
  { metadata: true, ontology: true, mlops: true },
])("uses explicit features independently of the semantic compatibility field: %j", async (features) => {
  vi.spyOn(deploymentApi, "status").mockResolvedValue({
    semantic: false, formatid: false, goods: false, ...features,
  });
  render(
    <MemoryRouter>
      <DeploymentAvailability>
        <WorkspaceChoices modelOperationsEnabled={features.mlops} />
        <span>features loaded</span>
      </DeploymentAvailability>
    </MemoryRouter>,
  );
  await screen.findByText("features loaded");
  expect(!!screen.queryByRole("navigation", { name: "데이터 시작" })).toBe(features.metadata);
  expect(!!screen.queryByRole("navigation", { name: "Ontology 시작" })).toBe(features.ontology);
  expect(!!screen.queryByRole("navigation", { name: "MLOps 시작" })).toBe(features.mlops);
  expect(screen.queryByRole("link", { name: "물품 사전" })).toBeNull();
});
