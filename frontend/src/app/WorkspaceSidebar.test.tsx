import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { WorkspaceSidebar } from "./WorkspaceSidebar";

afterEach(cleanup);
it("groups task navigation separately from platform administration", () => {
  render(
    <MemoryRouter initialEntries={["/admin/models"]}>
      <WorkspaceSidebar expanded modelOperationsEnabled onToggle={vi.fn()} />
    </MemoryRouter>,
  );
  const primary = screen.getByRole("navigation", { name: "주요 메뉴" });
  expect(
    within(primary).getByRole("button", { name: "의미 모델" }),
  ).toBeTruthy();
  expect(
    within(primary).getByRole("button", { name: "모델 운영" }),
  ).toBeTruthy();
  expect(within(primary).getByRole("link", { name: "검토함" })).toBeTruthy();
  const apps = within(primary).getByRole("button", { name: "앱" });
  const groups = within(primary).getAllByRole("button");
  expect(groups.at(-1)).toBe(apps);
  fireEvent.click(apps);
  expect(within(primary).getByRole("link", { name: "FormatID" })).toBeTruthy();
  expect(
    within(primary)
      .getByRole("link", { name: "모델 레지스트리" })
      .getAttribute("aria-current"),
  ).toBe("page");
  expect(
    within(primary).queryByRole("link", { name: "연결 및 설정" }),
  ).toBeNull();
  expect(
    within(screen.getByRole("navigation", { name: "플랫폼 관리" })).getByRole(
      "link",
      { name: "연결 및 설정" },
    ),
  ).toBeTruthy();
  expect(primary.querySelectorAll('[aria-current="page"]').length).toBe(1);
});
it("hides optional model work areas and keeps collapsed links accessible", () => {
  render(
    <MemoryRouter>
      <WorkspaceSidebar
        expanded={false}
        modelOperationsEnabled={false}
        onToggle={vi.fn()}
      />
    </MemoryRouter>,
  );
  expect(screen.queryByRole("link", { name: "모델 레지스트리" })).toBeNull();
  expect(screen.queryByRole("link", { name: "추론 서비스" })).toBeNull();
  expect(screen.getByRole("link", { name: "파이프라인" })).toBeTruthy();
  expect(
    screen.getByRole("link", { name: "데이터 자산" }).getAttribute("href"),
  ).toBe("/admin/data-catalog");
  expect(screen.getByRole("button", { name: "사이드바 펼치기" })).toBeTruthy();
});
