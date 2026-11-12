import { afterEach, expect, it, vi } from "vitest";
import { ontologyApi } from "../../../ontology/authoring/api";
import { bindingApi } from "../../../ontology/bindings/api";
import { suggestionApi } from "./api";
import { loadReviewWork } from "./review_work";

afterEach(() => vi.restoreAllMocks());

it("does not query disabled Ontology APIs in a metadata-only review queue", async () => {
  vi.spyOn(suggestionApi, "suggestionPage").mockResolvedValue({ items: [], next_cursor: null });
  const bindings = vi.spyOn(bindingApi, "bindings").mockRejectedValue(new Error("disabled"));
  const ontology = vi.spyOn(ontologyApi, "authoredOntologies").mockRejectedValue(new Error("disabled"));
  const result = await loadReviewWork({ metadata: true, ontology: false });
  expect(bindings).not.toHaveBeenCalled();
  expect(ontology).not.toHaveBeenCalled();
  expect(result.errors).toEqual([]);
});

it("does not query disabled Metadata APIs in an ontology-only review queue", async () => {
  const suggestions = vi.spyOn(suggestionApi, "suggestionPage").mockRejectedValue(new Error("disabled"));
  vi.spyOn(bindingApi, "bindings").mockResolvedValue({ items: [] });
  vi.spyOn(ontologyApi, "authoredOntologies").mockResolvedValue({ items: [] });
  const result = await loadReviewWork({ metadata: false, ontology: true });
  expect(suggestions).not.toHaveBeenCalled();
  expect(result.errors).toEqual([]);
});

it("forwards cancellation to all review requests and stops before scheduling version requests", async () => {
  const controller = new AbortController();
  const suggestions = vi.spyOn(suggestionApi, "suggestionPage").mockResolvedValue({ items: [], next_cursor: null });
  const bindings = vi.spyOn(bindingApi, "bindings").mockResolvedValue({ items: [] });
  const ontologies = vi.spyOn(ontologyApi, "authoredOntologies").mockImplementation(async () => {
    controller.abort();
    return { items: [] };
  });
  const versions = vi.spyOn(ontologyApi, "ontologyVersions");
  await expect(loadReviewWork({ metadata: true, ontology: true }, controller.signal)).rejects.toHaveProperty("name", "AbortError");
  expect(suggestions).toHaveBeenCalledWith("pending", undefined, undefined, controller.signal);
  expect(bindings).toHaveBeenCalledWith("draft", undefined, undefined, controller.signal);
  expect(ontologies).toHaveBeenCalledWith(controller.signal);
  expect(versions).not.toHaveBeenCalled();
});
