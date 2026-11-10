import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { serverQueryClient } from "../../api/server_queries";
import { imageRegistryApi } from "./api";
import { ImageRegistry } from "./ImageRegistry";

afterEach(() => {
  cleanup();
  serverQueryClient.clear();
  vi.restoreAllMocks();
});

it("shows verified image references and resolves a different tag", async () => {
  vi.spyOn(imageRegistryApi, "status").mockResolvedValue({
    configured: true,
    host: "registry.example.com",
  });
  vi.spyOn(imageRegistryApi, "repositories").mockResolvedValue({
    items: ["teoria/admin", "models/churn"],
    next: null,
  });
  vi.spyOn(imageRegistryApi, "tags").mockResolvedValue({
    items: ["v1", "v2"],
    next: null,
  });
  const manifest = vi
    .spyOn(imageRegistryApi, "manifest")
    .mockImplementation(async (repository, reference) => ({
      repository,
      reference,
      digest: "sha256:" + reference,
      image: `registry.example.com/${repository}@sha256:${reference}`,
      media_type: "index",
      platforms: [{ os: "linux", architecture: "amd64" }],
    }));
  render(
    <MemoryRouter
      initialEntries={["/admin/images?repository=models/churn&tag=v2"]}
    >
      <ImageRegistry />
    </MemoryRouter>,
  );
  expect(
    await screen.findByText("registry.example.com/models/churn@sha256:v2"),
  ).toBeTruthy();
  expect(screen.getByText("linux/amd64")).toBeTruthy();
  fireEvent.change(screen.getByRole("combobox", { name: "이미지 태그" }), {
    target: { value: "v1" },
  });
  expect(
    await screen.findByText("registry.example.com/models/churn@sha256:v1"),
  ).toBeTruthy();
  await waitFor(() =>
    expect(manifest).toHaveBeenCalledWith(
      "models/churn",
      "v1",
      expect.any(AbortSignal),
    ),
  );
});

it("does not query images when no registry is configured", async () => {
  vi.spyOn(imageRegistryApi, "status").mockResolvedValue({
    configured: false,
    host: null,
  });
  const repositories = vi.spyOn(imageRegistryApi, "repositories");
  render(
    <MemoryRouter>
      <ImageRegistry />
    </MemoryRouter>,
  );
  expect(
    await screen.findByText("이미지 저장소가 연결되지 않았습니다"),
  ).toBeTruthy();
  expect(repositories).not.toHaveBeenCalled();
});
