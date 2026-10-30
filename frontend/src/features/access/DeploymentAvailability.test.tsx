import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import {
  DeploymentAvailability,
  deploymentApi,
} from "./DeploymentAvailability";
import { WorkspaceSidebar } from "../../app/WorkspaceSidebar";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

it("shows MLOps without offering disabled Metadata or FormatID navigation", async () => {
  vi.spyOn(deploymentApi, "status").mockResolvedValue({
    mlops: true,
    semantic: false,
    formatid: false,
  });
  render(
    <MemoryRouter>
      <DeploymentAvailability>
        <WorkspaceSidebar
          expanded={false}
          modelOperationsEnabled
          onToggle={vi.fn()}
        />
      </DeploymentAvailability>
    </MemoryRouter>,
  );
  expect(
    await screen.findByRole("link", { name: "모델 레지스트리" }),
  ).toBeTruthy();
  expect(screen.getByRole("link", { name: "추론 서비스" })).toBeTruthy();
  expect(screen.queryByRole("link", { name: "데이터 자산" })).toBeNull();
  expect(screen.queryByRole("link", { name: "온톨로지" })).toBeNull();
  expect(screen.queryByRole("link", { name: "FormatID" })).toBeNull();
});

it("keeps feature pages unloaded if configuration cannot be read", async () => {
  vi.spyOn(deploymentApi, "status").mockRejectedValue(new Error("unavailable"));
  render(
    <DeploymentAvailability>
      <div>feature content</div>
    </DeploymentAvailability>,
  );
  expect(await screen.findByRole("alert")).toBeTruthy();
  expect(screen.queryByText("feature content")).toBeNull();
});
