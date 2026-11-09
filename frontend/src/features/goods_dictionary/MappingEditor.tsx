import { useEffect, useState, type FormEvent } from "react";
import {
  goodsDictionaryApi,
  type DictionaryRecord,
} from "../../api/goods_dictionary";
import { postJson } from "../../api/http_client";

export function MappingEditor({
  source,
  classification: selectedClassification,
  onSaved,
  onCancel,
}: {
  source: DictionaryRecord;
  classification?: string;
  onSaved: () => void;
  onCancel: () => void;
}) {
  const [owners, setOwners] = useState<Record<string, string>>({});
  useEffect(() => {
    const controller = new AbortController();
    goodsDictionaryApi
      .catalog(
        new URLSearchParams({
          kind: "concept",
          status: "approved",
          concept_kind: "item_type",
          limit: "500",
        }),
        controller.signal,
      )
      .then((page) =>
        setOwners(
          Object.fromEntries(
            page.items.map((row) => [
              row.concept_id!,
              row.content.preferred_name,
            ]),
          ),
        ),
      )
      .catch((e) => {
        if (!controller.signal.aborted) setError(e.message);
      });
    return () => controller.abort();
  }, []);
  const [query, setQuery] = useState("");
  const [targets, setTargets] = useState<DictionaryRecord[]>([]);
  const [target, setTarget] = useState("");
  const [owner, setOwner] = useState("");
  const [classification, setClassification] = useState(
    selectedClassification || "",
  );
  const [relation, setRelation] = useState("equivalent");
  const [rationale, setRationale] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    setTarget("");
    setOwner("");
    goodsDictionaryApi
      .catalog(
        new URLSearchParams({
          kind: "concept",
          status: "approved",
          concept_kind: source.kind,
          query,
          limit: "100",
        }),
        controller.signal,
      )
      .then((p) => setTargets(p.items))
      .catch((e) => {
        if (!controller.signal.aborted) setError(e.message);
      });
    return () => controller.abort();
  }, [query, source.kind]);
  const targetKey = (t: DictionaryRecord) => `${t.ontology?.version_id}:${t.concept_id}`;
  const selected = targets.find((t) => targetKey(t) === target);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await postJson("/goods/dictionary/mappings", {
        source_entry_id: source.entry_id,
        ontology: selected?.ontology,
        target_concept_id: selected?.concept_id,
        owner_concept_id: owner || null,
        classification_code: classification || null,
        scope_mode: classification ? "classified" : "unclassified",
        relation,
        rationale,
      });
      onSaved();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <form className="dictionary-form" onSubmit={submit}>
      <h3>원문 표현 연결 제안</h3>
      <p>원문 표현: {source.preferred_name}</p>
      <label>
        게시된 온톨로지 개념 검색
        <input value={query} onChange={(e) => setQuery(e.target.value)} />
      </label>
      <label>
        연결할 온톨로지 개념
        <select
          required
          value={target}
          onChange={(e) => {
            setTarget(e.target.value);
            setOwner("");
          }}
        >
          <option value="">선택 (검색 결과 최대 100개)</option>
          {targets.map((t) => (
            <option key={targetKey(t)} value={targetKey(t)}>
              {t.content.preferred_name} · {t.ontology?.namespace} {t.ontology?.version}
            </option>
          ))}
        </select>
      </label>
      {!targets.length && <p>게시된 개념이 필요합니다. 온톨로지에서 정의를 작성·검토·게시한 뒤 연결하세요.</p>}
      {selected && <p>{selected.content.definition}</p>}
      {source.kind === "characteristic" && (
        <label>
          적용 물품 유형
          <select
            required
            value={owner}
            onChange={(e) => setOwner(e.target.value)}
          >
            <option value="">선택</option>
            {selected?.content.applicable_item_type_ids.map((id) => (
              <option key={id} value={id}>
                {owners[id] || id}
              </option>
            ))}
          </select>
        </label>
      )}
      <label>
        분류 코드
        <input
          pattern="[0-9]{10}"
          readOnly={selectedClassification !== undefined}
          value={classification}
          onChange={(e) => setClassification(e.target.value)}
        />
      </label>
      <p>
        분류를 비우면 미분류 문맥에만 적용됩니다. 전체 분류에 적용하지 않습니다.
      </p>
      <label>
        연결 관계
        <select value={relation} onChange={(e) => setRelation(e.target.value)}>
          <option value="equivalent">같은 의미</option>
          <option value="related">관련 의미 (자동 대체하지 않음)</option>
        </select>
      </label>
      <label>
        판정 근거
        <textarea
          required
          minLength={10}
          maxLength={4000}
          value={rationale}
          onChange={(e) => setRationale(e.target.value)}
        />
      </label>
      {error && <p role="alert">{error}</p>}
      <div className="dictionary-actions">
        <button disabled={busy || !target}>연결 제안 저장</button>
        <button type="button" disabled={busy} onClick={onCancel}>
          취소
        </button>
      </div>
    </form>
  );
}
