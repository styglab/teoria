import { afterEach, expect, test, vi } from "vitest";
import { AdminApiError, getJson, postJson } from "./http_client";

afterEach(() => {
  vi.unstubAllGlobals();
  window.sessionStorage.clear();
});

test("preserves structured errors even when the server omits a message", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          detail: { code: "asset_assessment_not_configured" },
        }),
        { status: 503 },
      ),
    ),
  );
  try {
    await postJson("/intelligence/asset-assessments", {});
    throw new Error("Expected rejection");
  } catch (error) {
    expect(error).toBeInstanceOf(AdminApiError);
    expect(error).toMatchObject({
      status: 503,
      code: "asset_assessment_not_configured",
    });
  }
});

test("keeps HTTP status when authentication errors have a human message", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          detail: { code: "unauthorized", message: "인증 실패" },
        }),
        { status: 401 },
      ),
    ),
  );
  await expect(getJson("/auth/session")).rejects.toMatchObject({
    status: 401,
    code: "unauthorized",
    message: "인증 실패",
  });
});

test("handles non-JSON gateway errors without exposing their body", async () => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValue(
        new Response("<html>private gateway body</html>", { status: 502 }),
      ),
  );
  await expect(getJson("/metadata/status")).rejects.toMatchObject({
    status: 502,
    code: null,
    message: "Admin API 요청 실패 (502)",
  });
});

test("preserves string validation errors and passes session credentials", async () => {
  window.sessionStorage.setItem("teoria-admin-token", "synthetic-test-token");
  const fetch = vi
    .fn()
    .mockResolvedValue(
      new Response(JSON.stringify({ detail: "잘못된 요청" }), { status: 422 }),
    );
  vi.stubGlobal("fetch", fetch);
  await expect(getJson("/bindings")).rejects.toMatchObject({
    status: 422,
    code: null,
    message: "잘못된 요청",
  });
  expect(fetch.mock.calls[0][1].headers.Authorization).toBe(
    "Bearer synthetic-test-token",
  );
});

test("invalidates only the session whose credential was rejected", async () => {
  window.sessionStorage.setItem("teoria-admin-token", "old-token");
  let resolve!: (response: Response) => void;
  vi.stubGlobal(
    "fetch",
    vi.fn(
      () =>
        new Promise<Response>((done) => {
          resolve = done;
        }),
    ),
  );
  const pending = getJson("/metadata/status");
  window.sessionStorage.setItem("teoria-admin-token", "new-token");
  resolve(new Response("{}", { status: 401 }));
  await expect(pending).rejects.toMatchObject({ status: 401 });
  expect(window.sessionStorage.getItem("teoria-admin-token")).toBe("new-token");
});
