import "@testing-library/jest-dom/vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { AdminApiError } from "../../api/http_client";
import { authApi } from "../../api/auth";
import { metadataApi } from "../../api/metadata";
import { AdminAccess, AdminAccessProvider } from "./AdminAccess";
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  window.sessionStorage.clear();
});
test("checks administrator credentials independently of public metadata and logs out", async () => {
  const session = vi
    .spyOn(authApi, "session")
    .mockRejectedValueOnce(new AdminApiError("인증 거부", 401, "unauthorized"))
    .mockResolvedValueOnce({
      actor: "user:reviewer",
      roles: ["metadata_admin"],
    });
  const metadata = vi.spyOn(metadataApi, "metadataStatus");
  render(
    <AdminAccessProvider>
      <AdminAccess>
        <p>승인 작업</p>
      </AdminAccess>
    </AdminAccessProvider>,
  );
  expect(screen.queryByText("승인 작업")).not.toBeInTheDocument();
  fireEvent.click(screen.getAllByRole("button", { name: "관리자 연결" })[0]);
  fireEvent.change(screen.getByLabelText("관리자 토큰"), {
    target: { value: "invalid-token" },
  });
  fireEvent.click(screen.getByRole("button", { name: "연결" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("토큰을 거절");
  expect(window.sessionStorage.getItem("teoria-admin-token")).toBeNull();
  fireEvent.change(screen.getByLabelText("관리자 토큰"), {
    target: { value: 'TEORIA_ADMIN_API_TOKEN="synthetic-test-token"' },
  });
  fireEvent.click(screen.getByRole("button", { name: "연결" }));
  expect(await screen.findByText("승인 작업")).toBeInTheDocument();
  expect(session).toHaveBeenCalledTimes(2);
  expect(metadata).not.toHaveBeenCalled();
  expect(window.sessionStorage.getItem("teoria-admin-token")).toBe(
    "synthetic-test-token",
  );
  fireEvent.click(screen.getByRole("button", { name: "로그아웃" }));
  await waitFor(() =>
    expect(screen.queryByText("승인 작업")).not.toBeInTheDocument(),
  );
  expect(window.sessionStorage.getItem("teoria-admin-token")).toBeNull();
});

test("explains insufficient permission without treating it as a connection failure", async () => {
  vi.spyOn(authApi, "session").mockRejectedValue(
    new AdminApiError("권한 없음", 403, "admin_role_required"),
  );
  render(
    <AdminAccessProvider>
      <AdminAccess>
        <p>승인 작업</p>
      </AdminAccess>
    </AdminAccessProvider>,
  );
  fireEvent.click(screen.getAllByRole("button", { name: "관리자 연결" })[0]);
  fireEvent.change(screen.getByLabelText("관리자 토큰"), {
    target: { value: "synthetic-token" },
  });
  fireEvent.click(screen.getByRole("button", { name: "연결" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "관리자 연결 권한이 없습니다",
  );
  expect(window.sessionStorage.getItem("teoria-admin-token")).toBeNull();
});
