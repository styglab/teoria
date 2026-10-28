import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { ReviewInbox } from "./ReviewInbox";
import { suggestionApi } from "../../api/suggestions";
import { bindingApi, type SemanticBinding } from "../../api/binding";
import { ontologyApi } from "../../api/ontology";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});
it("unifies review discovery while keeping approval in its owning workflow", async () => {
  vi.spyOn(suggestionApi, "suggestionPage").mockResolvedValue({
    items: [],
    next_cursor: null,
  });
  vi.spyOn(bindingApi, "bindings").mockResolvedValue({
    items: [
      {
        binding_id: "binding-id",
        ontology_stable_key: "goods.Item",
        fully_qualified_name: "terms.Item",
        created_at: "2026-10-28",
      } as SemanticBinding,
    ],
  });
  vi.spyOn(ontologyApi, "authoredOntologies").mockResolvedValue({
    items: [
      {
        namespace: "goods",
        name: "물품",
        description: "",
        version_count: 1,
        latest_version: "1",
        latest_status: "in_review",
      },
    ],
  });
  vi.spyOn(ontologyApi, "ontologyVersions").mockResolvedValue({
    items: [
      {
        ontology_version_id: "version-id",
        version: "1",
        status: "in_review",
        created_at: "2026-10-28",
      },
    ],
  });
  const approve = vi.spyOn(bindingApi, "reviewBinding");
  const publish = vi.spyOn(ontologyApi, "publishOntology");
  render(
    <MemoryRouter>
      <ReviewInbox />
    </MemoryRouter>,
  );
  expect(await screen.findByText("goods.Item")).toBeTruthy();
  expect(await screen.findByText("물품 v1")).toBeTruthy();
  const links = screen
    .getAllByRole("link", { name: /검토 열기/ })
    .map((link) => link.getAttribute("href"));
  expect(links).toContain("/admin/semantic-model/bindings?binding=binding-id");
  expect(links).toContain(
    "/admin/semantic-model/ontology?version=version-id&view=review",
  );
  expect(approve).not.toHaveBeenCalled();
  expect(publish).not.toHaveBeenCalled();
});
