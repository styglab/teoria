import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { MappingEditor } from "./MappingEditor";
import { goodsDictionaryApi, type DictionaryRecord } from "../../api/goods_dictionary";
import * as http from "../../api/http_client";

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

test("proposes a stable Ontology concept and pinned publication without a local definition revision", async () => {
  const reference = { version_id: "publication", namespace: "goods", version: "1", checksum: "a".repeat(64) };
  const target: DictionaryRecord = { concept_id: "inverter", concept_key: "goods.inverter", kind: "item_type", status: "approved", ontology: reference,
    content: { key: "goods.inverter", kind: "item_type", preferred_name: "인버터", definition: "전력 변환 장치입니다.", value_kind: null, applicable_item_type_ids: [], quantity_dimension: null, canonical_unit: null, allowed_units: [], references: [] } };
  vi.spyOn(goodsDictionaryApi, "catalog").mockResolvedValue({ items: [target], total: 1 });
  const post = vi.spyOn(http, "postJson").mockResolvedValue({});
  const saved = vi.fn();
  render(<MappingEditor source={{ ...target, entry_id: "expression", preferred_name: "인버터" }} classification="1234567890" onSaved={saved} onCancel={() => {}} />);
  await screen.findByRole("option", { name: "인버터 · goods 1" });
  fireEvent.change(screen.getByLabelText("연결할 온톨로지 개념"), { target: { value: "publication:inverter" } });
  fireEvent.change(screen.getByLabelText("판정 근거"), { target: { value: "원문 문맥과 게시된 개념의 정의를 함께 검토했습니다." } });
  fireEvent.click(screen.getByRole("button", { name: "연결 제안 저장" }));
  await waitFor(() => expect(saved).toHaveBeenCalledOnce());
  expect(post).toHaveBeenCalledWith("/goods/dictionary/mappings", expect.objectContaining({ ontology: reference, target_concept_id: "inverter", source_entry_id: "expression", scope_mode: "classified" }));
  expect(post.mock.calls[0][1]).not.toHaveProperty("target_revision_id");
  expect(post.mock.calls[0][1]).not.toHaveProperty("actor");
});
