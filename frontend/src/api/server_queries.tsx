import {
  hashKey,
  QueryClient,
  QueryClientProvider,
  useInfiniteQuery,
  useQuery,
} from "@tanstack/react-query";
import { useEffect, useRef, useSyncExternalStore, type ReactNode } from "react";
import { DATA_CHANGED_EVENT, SESSION_EXPIRED_EVENT } from "./http_client";

// Tokens stay outside query keys, diagnostics and browser persistence.
let token: string | null = sessionStorage.getItem("teoria-admin-token");
let generation = 0;
const listeners = new Set<() => void>();
export const serverQueryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 0,
      gcTime: 300_000,
      retry: false,
      refetchOnWindowFocus: false,
    },
    mutations: { retry: false },
  },
});
export function resetServerQueries() {
  token = sessionStorage.getItem("teoria-admin-token");
  generation += 1;
  void serverQueryClient.cancelQueries();
  serverQueryClient.clear();
  listeners.forEach((notify) => notify());
}
function currentScope() {
  if (token !== sessionStorage.getItem("teoria-admin-token"))
    resetServerQueries();
  return generation;
}
window.addEventListener(SESSION_EXPIRED_EVENT, resetServerQueries);
window.addEventListener(DATA_CHANGED_EVENT, () => {
  void serverQueryClient.invalidateQueries();
});
export function invalidateServerQueries() {
  return serverQueryClient.invalidateQueries();
}
export function ServerQueryProvider({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider client={serverQueryClient}>
      {children}
    </QueryClientProvider>
  );
}

type QueryOptions<T> = {
  enabled?: boolean;
  keepPrevious?: boolean;
  refresh?: number;
  staleTime?: number;
  interval?: number | ((data: T | null) => number | false);
};

export function useServerQuery<T>(
  key: string | readonly unknown[] | null,
  load: (signal: AbortSignal) => Promise<T>,
  options: QueryOptions<T> = {},
) {
  const scope = useSyncExternalStore(
    (notify) => {
      listeners.add(notify);
      return () => {
        listeners.delete(notify);
      };
    },
    currentScope,
    currentScope,
  );
  const identity = hashKey(Array.isArray(key) ? key : [key]);
  const loader = useRef(load);
  loader.current = load;
  const query = useQuery(
    {
      queryKey: [scope, ...(Array.isArray(key) ? key : [key])],
      queryFn: ({ signal }) => loader.current(signal),
      enabled: key !== null && options.enabled !== false,
      staleTime: options.staleTime ?? 0,
      refetchInterval:
        typeof options.interval === "function"
          ? (query) =>
              (options.interval as (data: T | null) => number | false)(
                query.state.data ?? null,
              )
          : options.interval,
      placeholderData: options.keepPrevious
        ? (previous, previousQuery) =>
            previousQuery?.queryKey[0] === scope ? previous : undefined
        : undefined,
    },
    serverQueryClient,
  );
  // Retaining the last visible page after a failed refresh is UI state, not a second cache.
  const visible = useRef<{ scope: number; key: string; data: T } | null>(null);
  if (query.data !== undefined && !query.isPlaceholderData)
    visible.current = { scope, key: identity, data: query.data };
  if (visible.current && visible.current.scope !== scope)
    visible.current = null;
  const fallback =
    options.keepPrevious && visible.current?.scope === scope
      ? visible.current
      : null;
  const refresh = useRef(options.refresh);
  useEffect(() => {
    if (
      refresh.current !== options.refresh &&
      key !== null &&
      options.enabled !== false
    )
      void query.refetch();
    refresh.current = options.refresh;
  }, [options.refresh, key, options.enabled, query.refetch]);
  const enabled = key !== null && options.enabled !== false;
  const data = enabled ? (query.data ?? fallback?.data ?? null) : null;
  return {
    data,
    setData: (update: T | null | ((previous: T | null) => T | null)) => {
      if (scope !== currentScope()) return;
      serverQueryClient.setQueryData<T | null>(
        [scope, ...(Array.isArray(key) ? key : [key])],
        (previous) =>
          typeof update === "function"
            ? (update as (previous: T | null) => T | null)(previous ?? null)
            : update,
      );
    },
    error: query.error ? (query.error as Error).message : "",
    failure: query.error,
    loading:
      query.isFetching ||
      (query.isPending && key !== null && options.enabled !== false),
    previous:
      query.isPlaceholderData ||
      (query.data === undefined && !!fallback && fallback.key !== identity),
    cancel: () =>
      serverQueryClient.cancelQueries({
        queryKey: [scope, ...(Array.isArray(key) ? key : [key])],
        exact: true,
      }),
    refetch: query.refetch,
    retry: () => {
      void query.refetch();
    },
  };
}

export function useServerPages<T extends { next_cursor: string | null }>(
  key: readonly unknown[],
  load: (cursor: string | undefined, signal: AbortSignal) => Promise<T>,
  options: { enabled?: boolean } = {},
) {
  const scope = useSyncExternalStore(
    (notify) => {
      listeners.add(notify);
      return () => {
        listeners.delete(notify);
      };
    },
    currentScope,
    currentScope,
  );
  return useInfiniteQuery(
    {
      queryKey: [scope, ...key],
      initialPageParam: undefined as string | undefined,
      queryFn: ({ pageParam, signal }) => load(pageParam, signal),
      getNextPageParam: (page) => page.next_cursor || undefined,
      enabled: options.enabled !== false,
    },
    serverQueryClient,
  );
}
