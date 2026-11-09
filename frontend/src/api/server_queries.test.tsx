import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { AdminApiError, postJson } from "./http_client";
import {
  resetServerQueries,
  serverQueryClient,
  useServerQuery,
} from "./server_queries";

afterEach(() => {
  sessionStorage.clear();
  vi.unstubAllGlobals();
});

it("shares concurrent reads and cancels an abandoned in-flight request", async () => {
  let finish!: (value: string) => void;
  let signal!: AbortSignal;
  const load = vi.fn((current: AbortSignal) => {
    signal = current;
    return new Promise<string>((resolve) => {
      finish = resolve;
    });
  });
  const first = renderHook(() => useServerQuery(["shared"], load));
  const second = renderHook(() => useServerQuery(["shared"], load));
  await waitFor(() => expect(load).toHaveBeenCalledTimes(1));
  first.unmount();
  expect(signal.aborted).toBe(false);
  second.unmount();
  expect(signal.aborted).toBe(true);
  await act(async () => {
    finish("late private response");
  });
  expect(
    serverQueryClient
      .getQueryCache()
      .getAll()
      .every((query) => query.state.data === undefined),
  ).toBe(true);
});

it("keeps a late old page from replacing the current page", async () => {
  let finish!: (value: string) => void;
  let oldSignal!: AbortSignal;
  const { result, rerender } = renderHook(
    ({ page }) =>
      useServerQuery(["pages", page], (signal) => {
        if (page === 1) {
          oldSignal = signal;
          return new Promise<string>((resolve) => {
            finish = resolve;
          });
        }
        return Promise.resolve("page two");
      }),
    { initialProps: { page: 1 } },
  );
  rerender({ page: 2 });
  await waitFor(() => expect(result.current.data).toBe("page two"));
  expect(oldSignal.aborted).toBe(true);
  await act(async () => {
    finish("page one");
  });
  expect(result.current.data).toBe("page two");
});

it("clears private data and cancels requests when the authenticated session changes", async () => {
  sessionStorage.setItem("teoria-admin-token", "secret-one");
  resetServerQueries();
  const { result } = renderHook(() =>
    useServerQuery(["principal"], async () =>
      sessionStorage.getItem("teoria-admin-token"),
    ),
  );
  await waitFor(() => expect(result.current.data).toBe("secret-one"));
  expect(
    JSON.stringify(
      serverQueryClient
        .getQueryCache()
        .getAll()
        .map((query) => query.queryKey),
    ),
  ).not.toContain("secret-one");
  act(() => {
    sessionStorage.setItem("teoria-admin-token", "secret-two");
    resetServerQueries();
  });
  expect(result.current.data).not.toBe("secret-one");
  await waitFor(() => expect(result.current.data).toBe("secret-two"));
  expect(
    serverQueryClient
      .getQueryCache()
      .getAll()
      .some((query) => query.state.data === "secret-one"),
  ).toBe(false);
});

it.each([401, 403])(
  "does not automatically retry an authorization failure (%s)",
  async (status) => {
    const load = vi.fn().mockRejectedValue(new AdminApiError("denied", status));
    const { result } = renderHook(() =>
      useServerQuery(["denied", status], load),
    );
    await waitFor(() => expect(result.current.error).toBe("denied"));
    expect(load).toHaveBeenCalledTimes(1);
  },
);

it("invalidates reads after a confirmed write, but not after a read-only POST or failed write", async () => {
  const load = vi.fn().mockResolvedValue("value");
  renderHook(() => useServerQuery(["mutation-target"], load));
  await waitFor(() => expect(load).toHaveBeenCalledTimes(1));
  const fetchMock = vi
    .fn()
    .mockImplementation(async () => new Response("{}", { status: 200 }));
  vi.stubGlobal("fetch", fetchMock);
  await act(async () => {
    await postJson("/related-context", {}, { changesData: false });
  });
  expect(load).toHaveBeenCalledTimes(1);
  fetchMock.mockResolvedValueOnce(new Response("{}", { status: 403 }));
  await act(async () => {
    await expect(postJson("/approve", {})).rejects.toThrow();
  });
  expect(load).toHaveBeenCalledTimes(1);
  await act(async () => {
    await postJson("/approve", {});
  });
  await waitFor(() => expect(load).toHaveBeenCalledTimes(2));
});
