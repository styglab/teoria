import { afterEach, expect, it, vi } from "vitest";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { clearCatalogCache, useCatalogQuery } from "./catalog_queries";
import { AdminApiError, SESSION_EXPIRED_EVENT } from "../../api/http_client";
afterEach(() => {
  cleanup();
  clearCatalogCache();
  sessionStorage.clear();
});
it("aborts superseded requests and keeps the last page through a failed refresh", async () => {
  let fail = false;
  const requests: AbortSignal[] = [];
  const loader = vi.fn(async (signal: AbortSignal) => {
    requests.push(signal);
    if (fail) throw new Error("offline");
    return ["previous page"];
  });
  const { result, rerender } = renderHook(
    ({ key }) => useCatalogQuery(key, loader, { keepPrevious: true }),
    { initialProps: { key: "first" } },
  );
  await waitFor(() => expect(result.current.data).toEqual(["previous page"]));
  fail = true;
  rerender({ key: "next" });
  await waitFor(() => expect(result.current.error).toContain("다시 시도"));
  expect(requests.length).toBeGreaterThan(1);
  expect(result.current.data).toEqual(["previous page"]);
  expect(result.current.previous).toBe(true);
  fail = false;
  act(() => result.current.retry());
  await waitFor(() => expect(result.current.error).toBe(""));
  await waitFor(() => expect(result.current.previous).toBe(false));
});
it("reuses recent results on return and never shares cached observations with another token", async () => {
  sessionStorage.setItem("teoria-admin-token", "synthetic-a");
  const load = vi.fn(async () => ({ page: 1 }));
  const first = renderHook(() => useCatalogQuery("same", load));
  await waitFor(() => expect(first.result.current.data).toEqual({ page: 1 }));
  first.unmount();
  const second = renderHook(() => useCatalogQuery("same", load));
  await waitFor(() => expect(second.result.current.data).toEqual({ page: 1 }));
  expect(load).toHaveBeenCalledTimes(1);
  second.unmount();
  sessionStorage.setItem("teoria-admin-token", "synthetic-b");
  const third = renderHook(() => useCatalogQuery("same", load));
  await waitFor(() => expect(third.result.current.data).toEqual({ page: 1 }));
  expect(load).toHaveBeenCalledTimes(2);
});
it("does not render a late response from an aborted document request", async () => {
  let finish: (value: string) => void = () => {};
  const first = new Promise<string>((resolve) => {
    finish = resolve;
  });
  const { result, rerender } = renderHook(
    ({ key }) =>
      useCatalogQuery(key, async () => (key === "first" ? first : "second")),
    { initialProps: { key: "first" } },
  );
  rerender({ key: "second" });
  await waitFor(() => expect(result.current.data).toBe("second"));
  act(() => finish("wrong source"));
  await Promise.resolve();
  expect(result.current.data).toBe("second");
});
it.each([
  [413, "한도"],
  [404, "저장소"],
  [401, "로그인"],
  [409, "무결성"],
])(
  "explains error status %s without losing its recovery action",
  async (status, text) => {
    const { result } = renderHook(() =>
      useCatalogQuery("error", async () => {
        throw new AdminApiError("opaque", status);
      }),
    );
    await waitFor(() => expect(result.current.error).toContain(text));
  },
);

it("clears cached observations immediately when a session ends", async () => {
  const load = vi.fn(async () => ({ value: "private fixture" }));
  const first = renderHook(() => useCatalogQuery("doc", load));
  await waitFor(() => expect(first.result.current.data).toBeTruthy());
  first.unmount();
  window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT));
  const second = renderHook(() => useCatalogQuery("doc", load));
  await waitFor(() => expect(second.result.current.data).toBeTruthy());
  expect(load).toHaveBeenCalledTimes(2);
});
