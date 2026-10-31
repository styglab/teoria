import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { RouteBoundary } from "./RouteBoundary";
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
it("keeps a recovery action visible when a route crashes and resets at a new route", () => {
  vi.spyOn(console, "error").mockImplementation(() => {});
  const reload = vi.fn();
  vi.stubGlobal("location", { reload });
  function Broken(): never {
    throw new Error("controlled route failure");
  }
  const view = render(
    <RouteBoundary key="bad">
      <Broken />
    </RouteBoundary>,
  );
  expect(screen.getByRole("alert").textContent).toContain(
    "화면을 열지 못했습니다",
  );
  fireEvent.click(screen.getByRole("button", { name: "화면 다시 불러오기" }));
  expect(reload).toHaveBeenCalledOnce();
  view.rerender(
    <RouteBoundary key="other">
      <h1>다른 화면</h1>
    </RouteBoundary>,
  );
  expect(screen.getByRole("heading", { name: "다른 화면" })).toBeTruthy();
});
