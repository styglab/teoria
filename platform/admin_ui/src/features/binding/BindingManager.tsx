import {
  type FormEvent,
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Check, Link2, Plus, ShieldCheck, X } from "lucide-react";
import { Button } from "../../components/ui/button";
import {
  FilterTabs,
  PageHeader,
  PageState,
  SearchField,
} from "../../components/workspace/WorkspaceLayout";
import {
  bindingApi,
  type BindingValidation,
  type SemanticBinding,
} from "../../api/binding";
import { ontologyApi, type OntologyConcept } from "../../api/ontology";
import { metadataApi } from "../../api/metadata";

const statuses = [
  "all",
  "draft",
  "approved",
  "rejected",
  "deprecated",
] as const;
const statusLabels: Record<string, string> = {
  all: "전체",
  draft: "초안",
  approved: "승인됨",
  rejected: "거절됨",
  deprecated: "사용 종료",
  valid: "정상",
  checking: "확인 중",
};
const conceptLabels: Record<string, string> = {
  object: "업무 개념",
  property: "속성",
  relationship: "관계",
  rule: "규칙",
};
const authorityLabels: Record<string, string> = {
  preferred: "우선",
  authoritative: "권위",
  supplemental: "보조",
};
const targetLabels: Record<string, string> = {
  glossary_term: "업무 용어",
  data_asset: "데이터 자산",
};

export function BindingManager() {
  const [params] = useSearchParams();
  const asset = params.get("asset");
  const assetId = params.get("assetId");
  const selectedId = params.get("binding");
  const [contextTruncated, setContextTruncated] = useState(false);
  const [items, setItems] = useState<SemanticBinding[]>([]);
  const [concepts, setConcepts] = useState<OntologyConcept[]>([]);
  const [validation, setValidation] = useState<BindingValidation | null>(null);
  const [status, setStatus] = useState<(typeof statuses)[number]>("all");
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [formOpen, setFormOpen] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState({
    conceptId: "",
    targetType: "glossary_term",
    entityId: "",
    entityType: "glossaryTerm",
    fqn: "",
    bindingType: "equivalent_to",
    authority: "preferred",
    purpose: "semantic_resolution",
  });

  const load = useCallback(async () => {
    setLoading(true);
    try {
      let ids: string[] | undefined;
      if (selectedId) ids = [selectedId];
      else if (assetId) {
        const context = await metadataApi.assetContext(assetId);
        if (context.business.status !== "available")
          throw new Error("자산의 의미 연결 원천을 조회할 수 없습니다.");
        ids =
          context.business.data?.bindings.map((item) => item.binding_id) || [];
        setContextTruncated(Boolean(context.business.data?.bindings_truncated));
      }
      const [bindingResponse, conceptResponse, validationResponse] =
        await Promise.all([
          ids?.length === 0
            ? Promise.resolve({ items: [] })
            : bindingApi.bindings(status === "all" ? undefined : status, ids),
          ontologyApi.ontologyConcepts(),
          bindingApi.bindingValidation(),
        ]);
      setItems(bindingResponse.items);
      setConcepts(conceptResponse.items);
      setValidation(validationResponse);
      setError(null);
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setLoading(false);
    }
  }, [status, assetId, selectedId]);
  useEffect(() => {
    load();
  }, [load]);
  const selected = useMemo(
    () => concepts.find((item) => item.concept_id === form.conceptId),
    [concepts, form.conceptId],
  );

  const review = async (
    item: SemanticBinding,
    decision: "approve" | "reject" | "deprecate",
  ) => {
    setBusy(item.binding_id);
    try {
      await bindingApi.reviewBinding(item.binding_id, decision);
      await load();
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setBusy(null);
    }
  };
  const create = async (event: FormEvent) => {
    event.preventDefault();
    if (!selected) return;
    setBusy("create");
    try {
      await bindingApi.createBinding({
        ontology_ref_type: selected.concept_kind,
        ontology_concept_id: selected.concept_id,
        target_type: form.targetType,
        external_entity_id: form.entityId,
        entity_type: form.entityType,
        fully_qualified_name: form.fqn,
        binding_type: form.bindingType,
        purpose: form.purpose,
        authority: form.authority,
        priority: 100,
        provenance: { source: "admin_ui", resolution: "review_required" },
      });
      setFormOpen(false);
      setForm((value) => ({ ...value, entityId: "", fqn: "" }));
      await load();
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const filtered = items.filter((item) =>
    [item.ontology_stable_key, item.fully_qualified_name, item.purpose].some(
      (value) =>
        value?.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()),
    ),
  );

  return (
    <div className="binding-manager">
      <PageHeader
        title="의미 연결"
        description="업무 개념과 데이터 자산·용어의 연결을 검토하고 관리합니다."
        actions={
          <Button
            disabled={!!busy}
            onClick={() => setFormOpen((value) => !value)}
          >
            {formOpen ? <X size={14} /> : <Plus size={14} />}{" "}
            {formOpen ? "닫기" : "의미 연결 추가"}
          </Button>
        }
      />
      <SearchField
        label="의미 연결 검색"
        placeholder="업무 개념, 자산 이름, 사용 목적 검색"
        value={query}
        onChange={setQuery}
      />
      {selectedId && (
        <div className="context-banner">
          <span>제안에서 생성된 의미 연결을 검토합니다.</span>
          <Link to="/admin/semantic-model/bindings">모든 연결 보기</Link>
        </div>
      )}
      {asset && (
        <div className="context-banner">
          <span>
            선택한 자산: <strong>{asset}</strong>
          </span>
          <Link
            to={`/admin/data-catalog/assets/${encodeURIComponent(asset)}?tab=business`}
          >
            자산으로 돌아가기
          </Link>
          <Link to="/admin/semantic-model/bindings">범위 해제</Link>
          {contextTruncated && <small>최근 50개 연결 범위입니다.</small>}
        </div>
      )}
      <div className="page-controls">
        <FilterTabs
          label="의미 연결 상태"
          items={statuses.map((id) => ({ id, label: statusLabels[id] }))}
          value={status}
          onChange={setStatus}
          disabled={!!busy}
        />
        <div className={`binding-health ${validation?.status ?? "unknown"}`}>
          <ShieldCheck size={15} />
          <strong>
            {statusLabels[validation?.status ?? "checking"] ??
              validation?.status}
          </strong>
          <span>
            연결 {validation?.binding_count ?? 0}개 · 진단{" "}
            {validation?.diagnostic_count ?? 0}개
          </span>
        </div>
      </div>
      {formOpen && (
        <form className="binding-form" onSubmit={create}>
          <label>
            온톨로지 개념
            <select
              required
              value={form.conceptId}
              onChange={(e) => setForm({ ...form, conceptId: e.target.value })}
            >
              <option value="">선택</option>
              {concepts.map((item) => (
                <option key={item.concept_id} value={item.concept_id}>
                  {item.stable_key} ·{" "}
                  {conceptLabels[item.concept_kind] ?? item.concept_kind}
                </option>
              ))}
            </select>
          </label>
          <label>
            연결 대상
            <select
              value={form.targetType}
              onChange={(e) =>
                setForm({
                  ...form,
                  targetType: e.target.value,
                  entityType:
                    e.target.value === "glossary_term"
                      ? "glossaryTerm"
                      : "column",
                })
              }
            >
              <option value="glossary_term">업무 용어</option>
              <option value="data_asset">데이터 자산</option>
            </select>
          </label>
          <label>
            OpenMetadata 엔터티 ID
            <input
              required
              value={form.entityId}
              onChange={(e) => setForm({ ...form, entityId: e.target.value })}
            />
          </label>
          <label>
            정규 이름(FQN)
            <input
              required
              value={form.fqn}
              onChange={(e) => setForm({ ...form, fqn: e.target.value })}
              placeholder="Procurement.ContractAmount"
            />
          </label>
          <label>
            엔터티 유형
            <input
              required
              value={form.entityType}
              onChange={(e) => setForm({ ...form, entityType: e.target.value })}
            />
          </label>
          <label>
            권위 수준
            <select
              value={form.authority}
              onChange={(e) => setForm({ ...form, authority: e.target.value })}
            >
              <option value="preferred">우선</option>
              <option value="authoritative">권위</option>
              <option value="supplemental">보조</option>
            </select>
          </label>
          <button disabled={busy === "create"} type="submit">
            연결 초안 생성
          </button>
        </form>
      )}
      {error && <div className="binding-error">{error}</div>}
      <div className="binding-list">
        {!loading &&
          filtered.map((item) => (
            <article key={item.binding_id}>
              <header>
                <div className="binding-icon">
                  <Link2 size={15} />
                </div>
                <div>
                  <small>
                    {conceptLabels[item.ontology_concept_kind] ??
                      item.ontology_concept_kind}
                  </small>
                  <h3>{item.ontology_stable_key}</h3>
                </div>
                <b className={`binding-status ${item.status}`}>
                  {statusLabels[item.status] ?? item.status}
                </b>
              </header>
              <div className="binding-direction">
                <span>↕</span>
                <div>
                  <strong>{item.fully_qualified_name}</strong>
                  <small>
                    OpenMetadata · {item.entity_type} ·{" "}
                    {targetLabels[item.target_type] ?? item.target_type}
                  </small>
                </div>
              </div>
              <dl>
                <div>
                  <dt>연결 유형</dt>
                  <dd>{item.binding_type}</dd>
                </div>
                <div>
                  <dt>권위 수준</dt>
                  <dd>{authorityLabels[item.authority] ?? item.authority}</dd>
                </div>
                <div>
                  <dt>사용 목적</dt>
                  <dd>{item.purpose ?? "—"}</dd>
                </div>
                <div>
                  <dt>최근 검증</dt>
                  <dd>
                    {item.last_verified_at
                      ? item.last_verified_at.slice(0, 10)
                      : "검증 기록 없음"}
                  </dd>
                </div>
              </dl>
              <footer>
                <small>
                  생성 {item.created_by}
                  {item.approved_by ? ` · 승인 ${item.approved_by}` : ""}
                </small>
                <div>
                  {item.status === "draft" && (
                    <>
                      <button
                        disabled={busy === item.binding_id}
                        onClick={() => review(item, "reject")}
                      >
                        거절
                      </button>
                      <button
                        className="primary"
                        disabled={busy === item.binding_id}
                        onClick={() => review(item, "approve")}
                      >
                        <Check size={13} />
                        승인
                      </button>
                    </>
                  )}
                  {item.status === "approved" && (
                    <button
                      disabled={busy === item.binding_id}
                      onClick={() => review(item, "deprecate")}
                    >
                      사용 종료
                    </button>
                  )}
                </div>
              </footer>
            </article>
          ))}
      </div>
      {loading && <PageState loading title="의미 연결을 불러오고 있습니다…" />}
      {!loading && !error && !filtered.length && (
        <PageState
          title={
            query
              ? "조건에 맞는 의미 연결이 없습니다"
              : "해당 상태의 의미 연결이 없습니다."
          }
        />
      )}
    </div>
  );
}
