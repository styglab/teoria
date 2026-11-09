import "@testing-library/jest-dom/vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";
import {
  goodsDictionaryApi,
  type DictionaryRecord,
} from "../../api/goods_dictionary";
import { GoodsDictionary } from "./GoodsDictionary";
import { ApplicationStandards } from "../specification_processing/ApplicationStandards";

vi.spyOn(goodsDictionaryApi, "classifications").mockResolvedValue({
  items: [],
  total: 0,
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.spyOn(goodsDictionaryApi, "classifications").mockResolvedValue({
    items: [],
    total: 0,
  });
});
const definition = {
  key: "memory_capacity",
  kind: "characteristic" as const,
  preferred_name: "메모리 용량",
  definition: "서버 주기억장치의 저장 용량을 의미한다.",
  value_kind: "number",
  applicable_item_type_ids: ["server"],
  quantity_dimension: "information",
  canonical_unit: "GB",
  allowed_units: ["GB"],
  references: ["source:document#row1"],
};
const row: DictionaryRecord = {
  revision_id: "revision_1",
  concept_id: "concept_1",
  concept_key: "memory_capacity",
  revision: 2,
  kind: "characteristic",
  status: "draft",
  content: definition,
};

test("canonical definitions are read-only here and lead to Ontology authoring", async () => {
  vi.spyOn(goodsDictionaryApi, "catalog").mockResolvedValue({ items: [{ ...row, status: "approved", revision_id: undefined, ontology: { version_id: "v1", namespace: "goods", version: "1", checksum: "a".repeat(64) } }], total: 1 });
  vi.spyOn(goodsDictionaryApi, "audit").mockResolvedValue({ items: [] });
  vi.spyOn(goodsDictionaryApi, "impact").mockResolvedValue({ documents: [] });
  render(<MemoryRouter initialEntries={["/admin/domains/goods/dictionary?classification=all&tab=attributes"]}><GoodsDictionary /></MemoryRouter>);
  expect(await screen.findByRole("heading", { name: "메모리 용량" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "온톨로지에서 정의 작성·검토" })).toHaveAttribute("href", "/admin/semantic-model/ontology");
  expect(screen.queryByRole("button", { name: "새 정의 제안" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "승인" })).not.toBeInTheDocument();
});

test("reviews expression mappings and records an explicit reason through the API", async () => {
  let approved = false;
  vi.spyOn(goodsDictionaryApi, "catalog").mockImplementation(async () => ({
    items: [{ ...row, mapping_id: "mapping_1", source_name: "메모리 용량", status: approved ? "approved" : "draft" }],
    total: 1,
  }));
  vi.spyOn(goodsDictionaryApi, "audit").mockResolvedValue({
    items: [
      {
        event_id: "event",
        action: "proposed",
        actor: "worker:semantic",
        rationale: "원문 근거 기반 제안",
        created_at: "2026-11-04T00:00:00Z",
      },
    ],
  });
  vi.spyOn(goodsDictionaryApi, "impact").mockResolvedValue({
    documents: [
      {
        document_id: "server_doc",
        operation_id: "original_run",
        source_sha256: "a".repeat(64),
      },
    ],
  });
  const decide = vi
    .spyOn(goodsDictionaryApi, "decide")
    .mockImplementation(async () => {
      approved = true;
      return { ...row, status: "approved" };
    });
  render(
    <MemoryRouter
      initialEntries={[
        "/admin/domains/goods/dictionary?classification=4321150102&tab=mapping",
      ]}
    >
      <GoodsDictionary />
    </MemoryRouter>,
  );
  expect(
    await screen.findByRole("heading", { name: "메모리 용량" }),
  ).toBeInTheDocument();
  expect(await screen.findByText(/worker:semantic/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /^승인$/ })).toBeDisabled();
  fireEvent.change(screen.getByLabelText("검토 사유"), {
    target: { value: "원문과 적용 범위 및 단위 정책을 검토했습니다." },
  });
  fireEvent.click(screen.getByRole("button", { name: /^승인$/ }));
  await waitFor(() =>
    expect(decide).toHaveBeenCalledWith(
      "mapping",
      "mapping_1",
      "approve",
      "원문과 적용 범위 및 단위 정책을 검토했습니다.",
    ),
  );
  expect(
    await screen.findByRole("button", { name: "사용 중단" }),
  ).toBeInTheDocument();
});

test("searches and pages on the server rather than downloading the whole dictionary", async () => {
  const catalog = vi
    .spyOn(goodsDictionaryApi, "catalog")
    .mockResolvedValue({ items: [], total: 80 });
  render(
    <MemoryRouter
      initialEntries={[
        "/admin/domains/goods/dictionary?classification=4321150102&tab=attributes",
      ]}
    >
      <GoodsDictionary />
    </MemoryRouter>,
  );
  await waitFor(() => expect(catalog).toHaveBeenCalled());
  fireEvent.change(screen.getByLabelText("품목 4321150102 검색"), {
    target: { value: "정격출력" },
  });
  await waitFor(() =>
    expect(catalog.mock.calls.at(-1)?.[0].get("query")).toBe("정격출력"),
  );
  expect(catalog.mock.calls.at(-1)?.[0].get("limit")).toBe("25");
});

test("application version creation pins the reviewed snapshot and never submits an actor", async () => {
  vi.spyOn(goodsDictionaryApi, "standardReadiness").mockResolvedValue({
    source_run_id: "source_run", ready: true, reason: null,
    definition_count: 1, rule_count: 1, standard_kind: "extraction_draft",
  });
  vi.spyOn(goodsDictionaryApi, "standards").mockResolvedValue({
    items: [],
    total: 0,
  });
  vi.spyOn(goodsDictionaryApi, "standardSources").mockResolvedValue({
    items: [
      {
        run_id: "source_run",
        classification_code: "4321150102",
        status: "completed",
      },
    ],
    total: 1,
  });
  vi.spyOn(goodsDictionaryApi, "snapshot").mockResolvedValue({
    schema_version: 2,
    checksum: "a".repeat(64),
    ontologies: [],
    mappings: [{}],
  });
  const approve = vi
    .spyOn(goodsDictionaryApi, "approveStandard")
    .mockRejectedValue(new Error("사전이 변경되었습니다. 다시 조회하세요."));
  render(
    <MemoryRouter>
      <ApplicationStandards />
    </MemoryRouter>,
  );
  await screen.findByRole("option", { name: /source_run/ });
  fireEvent.change(screen.getByLabelText("버전 이름"), {
    target: { value: "서버 v1" },
  });
  fireEvent.change(screen.getByLabelText("표준관리 실행"), {
    target: { value: "source_run" },
  });
  fireEvent.change(screen.getByLabelText("승인 근거"), {
    target: { value: "표준과 사전의 적용 범위를 검토했습니다." },
  });
  await screen.findByText("정의 1개 · 적용 규칙 1개를 확인했습니다.");
  fireEvent.click(
    screen.getByRole("button", {
      name: "검토한 기준을 규격서 처리 기준으로 승인",
    }),
  );
  await waitFor(() =>
    expect(approve).toHaveBeenCalledWith({
      name: "서버 v1",
      source_run_id: "source_run",
      expected_dictionary_checksum: "a".repeat(64),
      rationale: "표준과 사전의 적용 범위를 검토했습니다.",
    }),
  );
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "사전이 변경되었습니다",
  );
});

test("starts with a product choice and sends product scope separately from shared definitions", async () => {
  const catalog = vi
    .spyOn(goodsDictionaryApi, "catalog")
    .mockResolvedValue({ items: [], total: 0 });
  render(
    <MemoryRouter>
      <GoodsDictionary />
    </MemoryRouter>,
  );
  expect(
    screen.getByText(
      "정의는 온톨로지에서 관리합니다. 품목별 적용 범위는 근거가 있는 원문 표현 연결을 검토해 승인합니다.",
    ),
  ).toBeInTheDocument();
  expect(catalog).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText("품목코드 검색·직접 입력"), {
    target: { value: "4321150102" },
  });
  fireEvent.click(screen.getByRole("button", { name: "이 품목 보기" }));
  await waitFor(() =>
    expect(catalog.mock.calls.at(-1)?.[0].get("classification")).toBe(
      "4321150102",
    ),
  );
  expect(catalog.mock.calls.at(-1)?.[0].get("concept_kind")).toBe("item_type");
  fireEvent.click(screen.getByRole("button", { name: "검토 대기" }));
  await waitFor(() =>
    expect(catalog.mock.calls.at(-1)?.[0].get("unresolved")).toBe("true"),
  );
  expect(catalog.mock.calls.at(-1)?.[0].get("kind")).toBe("source");
  fireEvent.click(screen.getAllByRole("button", { name: "온톨로지 정의 조회" })[0]);
  await waitFor(() =>
    expect(catalog.mock.calls.at(-1)?.[0].has("classification")).toBe(false),
  );
});

 test("prevents approving a processing standard that has no application rules", async () => {
  vi.spyOn(goodsDictionaryApi, "standards").mockResolvedValue({items:[],total:0});
  vi.spyOn(goodsDictionaryApi, "standardSources").mockResolvedValue({items:[{run_id:"empty_run",classification_code:null,status:"partial"}],total:1});
  vi.spyOn(goodsDictionaryApi, "snapshot").mockResolvedValue({checksum:"a".repeat(64),mappings:[],schema_version:2,ontologies:[]});
  vi.spyOn(goodsDictionaryApi, "standardReadiness").mockResolvedValue({source_run_id:"empty_run",ready:false,reason:"standard_has_no_application_rules",definition_count:0,rule_count:0,standard_kind:"extraction_draft"});
  const approve=vi.spyOn(goodsDictionaryApi,"approveStandard");
  render(<MemoryRouter><ApplicationStandards /></MemoryRouter>);
  await screen.findByRole("option",{name:/empty_run/});
  fireEvent.change(screen.getByLabelText("표준관리 실행"),{target:{value:"empty_run"}});
  await screen.findByText(/적용할 규칙이 없는 표준은 승인할 수 없습니다/);
  const button=screen.getByRole("button",{name:"검토한 기준을 규격서 처리 기준으로 승인"}) as HTMLButtonElement;
  expect(button.disabled).toBe(true);
  fireEvent.submit(button.closest("form")!);
  expect(approve).not.toHaveBeenCalled();
});
