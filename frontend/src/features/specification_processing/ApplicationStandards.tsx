import { useEffect, useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { PageHeader } from "../../components/workspace/WorkspaceLayout";
import "./application_standards.css";
import { processingApi } from "../../api/specification_processing";
import {
  goodsDictionaryApi,
  type ApplicationStandard,
} from "../../api/goods_dictionary";

export function ApplicationStandards() {
  const [params] = useSearchParams();
  const [page, setPage] = useState(0);
  const [sourcePage, setSourcePage] = useState(0);
  const [revision, setRevision] = useState(0);
  const [releases, setReleases] = useState<{
    items: ApplicationStandard[];
    total: number;
  }>({ items: [], total: 0 });
  const [sources, setSources] = useState<{
    items: Array<{
      run_id: string;
      classification_code: string | null;
      status: string;
    }>;
    total: number;
  }>({ items: [], total: 0 });
  const [snapshot, setSnapshot] = useState<Awaited<ReturnType<typeof goodsDictionaryApi.snapshot>> | null>(null);
  const [name, setName] = useState("");
  const [source, setSource] = useState(params.get("source_run") || "");
  const [rationale, setRationale] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [readiness, setReadiness] = useState<Awaited<ReturnType<typeof goodsDictionaryApi.standardReadiness>> | null>(null);
  const [readinessError, setReadinessError] = useState("");
  useEffect(() => {
    let active = true;
    setReadiness(null); setReadinessError("");
    if (source) goodsDictionaryApi.standardReadiness(source).then(value => {
      if (active) setReadiness(value);
    }).catch(reason => { if (active) setReadinessError(reason.message); });
    return () => { active = false; };
  }, [source, revision]);
  const ready = readiness?.source_run_id === source && readiness.ready;
  useEffect(() => {
    let active = true;
    setError("");
    Promise.all([
      goodsDictionaryApi.standards(page),
      goodsDictionaryApi.standardSources(sourcePage),
      goodsDictionaryApi.snapshot(),
    ])
      .then(async ([r, s, d]) => {
        const requested = params.get("source_run");
        if (requested && !s.items.some(item => item.run_id === requested)) {
          const detail = await processingApi.detail(requested);
          if (detail.run.mode === "standard_management" && ["completed", "partial"].includes(detail.run.status)) {
            s.items = [detail.run, ...s.items];
          }
        }
        if (active) {
          setReleases(r);
          setSources(s);
          setSnapshot(d);
        }
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, [page, sourcePage, revision, params]);
  const selected = sources.items.find((s) => s.run_id === source);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!snapshot || !ready) return;
    setBusy(true);
    setError("");
    try {
      await goodsDictionaryApi.approveStandard({
        name,
        source_run_id: source,
        expected_dictionary_checksum: snapshot.checksum,
        rationale,
      });
      setName("");
      setSource("");
      setRationale("");
      setRevision((v) => v + 1);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="processing-standard-detail">
      <Link to="/admin/specifications">← FormatID로 돌아가기</Link>
      <PageHeader
        title="규격서 처리 기준"
        description="문서 처리에 사용할 표준·프로파일과 사전 버전을 검토해 함께 고정합니다."
      />
      <p>
        규격서 처리 기준은 선택한 실행의 표준과 게시된 온톨로지·승인된 표현 연결을
        불변 스냅샷으로 묶습니다. 이후 사전 개정은 이 버전을 바꾸지 않습니다.
      </p>
      <p>
        추출용 표준 초안을 고정한 버전은 Published Ontology나 국가 표준 인증을
        뜻하지 않습니다.
      </p>
      {error && (
        <p role="alert">
          {error}{" "}
          <button onClick={() => setRevision((v) => v + 1)}>다시 조회</button>
        </p>
      )}
      <form className="processing-standard-form" onSubmit={submit}>
        <h3>새 규격서 처리 기준 승인</h3>
        <label>
          버전 이름
          <input
            required
            maxLength={120}
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="서버 규격서 적용 기준 v1"
          />
        </label>
        <label>
          표준관리 실행
          <select
            required
            value={source}
            onChange={(e) => setSource(e.target.value)}
          >
            <option value="">처리 결과 선택</option>
            {sources.items.map((s) => (
              <option key={s.run_id} value={s.run_id}>
                {s.run_id} · {s.classification_code || "미분류"} ·{" "}
                {s.status === "partial" ? "부분 완료" : "완료"}
              </option>
            ))}
          </select>
        </label>
        {selected && (
          <Link
            to={`/admin/specifications?run=${encodeURIComponent(selected.run_id)}`}
          >
            선택한 실행의 표준과 미해결 항목 검토
          </Link>
        )}
        {selected && !readiness && !readinessError && <p role="status">적용할 규칙을 확인하고 있습니다…</p>}
        {readinessError && <p role="alert">{readinessError}</p>}
        {readiness && readiness.source_run_id === source && <p role={readiness.ready ? "status" : "alert"}>
          {readiness.ready
            ? `정의 ${readiness.definition_count}개 · 적용 규칙 ${readiness.rule_count}개를 확인했습니다.`
            : "적용할 규칙이 없는 표준은 승인할 수 없습니다. 표준·프로파일을 먼저 작성하고 검토하세요."}
        </p>}
        <div className="processing-standard-actions">
          <button
            type="button"
            disabled={!sourcePage}
            onClick={() => {
              setSource("");
              setSourcePage((p) => p - 1);
            }}
          >
            이전 실행
          </button>
          <span>
            조회 {sources.items.length} / 전체 {sources.total}
          </span>
          <button
            type="button"
            disabled={(sourcePage + 1) * 25 >= sources.total}
            onClick={() => {
              setSource("");
              setSourcePage((p) => p + 1);
            }}
          >
            다음 실행
          </button>
        </div>
        {snapshot && (
          <p>
            현재 사전: {snapshot.schema_version === 2 ? `게시 Ontology ${snapshot.ontologies?.length || 0}개` : `과거 정의 ${snapshot.concepts?.length || 0}개`} · 연결{" "}
            {snapshot.mappings.length}개 중 승인된 항목만 고정합니다.
          </p>
        )}
        {selected?.status === "partial" && (
          <label>
            <input key={source} type="checkbox" required />
            부분 완료 실행의 보류·미해결 항목을 확인했습니다.
          </label>
        )}
        <label>
          승인 근거
          <textarea
            required
            minLength={10}
            maxLength={4000}
            value={rationale}
            onChange={(e) => setRationale(e.target.value)}
          />
        </label>
        <button disabled={busy || !snapshot || !selected || !ready}>
          검토한 기준을 규격서 처리 기준으로 승인
        </button>
      </form>
      <h3>고정된 규격서 처리 기준</h3>
      {releases.items.length ? (
        <ul>
          {releases.items.map((r) => (
            <li key={r.release_id}>
              <strong>{r.name}</strong>
              <p>
                {r.classification_code || "미분류"} ·{" "}
                {r.standard_kind === "ontology_profile"
                  ? "Ontology 프로파일"
                  : "추출용 표준 초안"}{" "}
                · 승인자 {r.approved_by}
              </p>
              <p>{r.rationale}</p>
              {r.status === "approved" && <Link to={`/admin/specifications?new=1&reprocess=${encodeURIComponent(r.source_run_id)}&release=${encodeURIComponent(r.release_id)}`}>이 기준으로 원본 문서 재처리</Link>}
              <details>
                <summary>고정 정보</summary>
                <p>표준: {r.standard_ref.sha256}</p>
                <p>사전: {r.dictionary_checksum}</p>
                <p>원본 실행: {r.source_run_id}</p>
              </details>
            </li>
          ))}
        </ul>
      ) : (
        <p>
          승인된 규격서 처리 기준이 없습니다. 검토한 표준관리 결과를 선택해
          고정하세요.
        </p>
      )}
      <div className="processing-standard-actions">
        <button disabled={!page} onClick={() => setPage((p) => p - 1)}>
          이전 버전
        </button>
        <span>{releases.total}개</span>
        <button
          disabled={(page + 1) * 25 >= releases.total}
          onClick={() => setPage((p) => p + 1)}
        >
          다음 버전
        </button>
      </div>
    </div>
  );
}
