import { PageHeader } from "../../components/workspace/WorkspaceLayout";
import { useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import {
  suggestionApi,
  type IntelligenceSuggestion,
} from "../../api/suggestions";
import { metadataApi, type MetadataTableDetail } from "../../api/metadata";
import { bindingApi } from "../../api/binding";
import { AssetContext } from "./AssetContext";
import { TableDataEvidence } from "./TableDataEvidence";
import { AssetAssessmentPanel } from "../intelligence/asset_assessment/AssetAssessmentPanel";
import { useAdminAccess } from "../access/AdminAccess";
const tabs = [
  { id: "technical", label: "개요" },
  { id: "columns", label: "스키마" },
  { id: "business", label: "의미" },
  { id: "governance", label: "거버넌스" },
  { id: "evidence", label: "품질·프로파일" },
  { id: "lineage", label: "계보" },
  { id: "operations", label: "운영" },
  { id: "diagnosis", label: "진단" },
];
type DescriptionEditTarget = {
  label: string;
  current: string;
  columnName?: string;
};
const diagnosisRequests = {
  enrichment: {
    label: "메타데이터 정비",
    skill: "enrich-metadata-asset",
    scope:
      "테이블·컬럼 설명과 Glossary 용어를 검토하고, 근거와 confidence를 포함한 제안을 Review Queue에 올려줘.",
  },
  semantics: {
    label: "업무 의미 연결",
    skill: "align-metadata-semantics",
    scope:
      "기존 Published Ontology와 Glossary를 확인해 Semantic Binding을 제안하고, 근거와 confidence를 포함한 제안을 Review Queue에 올려줘. 대응 개념이 없으면 연결 공백으로 보고하고 신규 Ontology는 만들지 마.",
  },
  disclosure: {
    label: "개방 적합성 진단",
    skill: "assess-data-disclosure",
    scope:
      "일반 공개 시나리오를 기준으로 정보 유형과 법령 근거를 검토해 내부 처리와 외부 개방을 구분한 진단 초안을 보여줘. 평가 기준일을 명시하고 태그 후보와 보호조치를 제안해줘. 개인정보 원본 샘플은 사용하지 마. 태그는 적용하지 말고, 지원하지 않는 제안 유형은 Review Queue에 제출하지 마.",
  },
};
export function MetadataAssetPage() {
  const { fqn } = useParams();
  const [params, setParams] = useSearchParams();
  const tab = tabs.some((item) => item.id === params.get("tab"))
    ? params.get("tab")!
    : "technical";
  const [columnQuery, setColumnQuery] = useState("");
  const [columnFilter, setColumnFilter] = useState("all");
  const [detail, setDetail] = useState<MetadataTableDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [suggestion, setSuggestion] = useState<IntelligenceSuggestion | null>(
    null,
  );
  const [descriptionSuggestion, setDescriptionSuggestion] =
    useState<IntelligenceSuggestion | null>(null);
  const [descriptionTarget, setDescriptionTarget] =
    useState<DescriptionEditTarget | null>(null);
  const [bindingApproved, setBindingApproved] = useState(false);
  const [copied, setCopied] = useState<string | null>(null);
  const { principal, requestLogin } = useAdminAccess();
  useEffect(() => {
    let active = true;
    setDetail(null);
    setError(null);
    setSuggestion(null);
    setDescriptionSuggestion(null);
    setDescriptionTarget(null);
    setBindingApproved(false);
    setColumnQuery("");
    setColumnFilter("all");
    if (fqn)
      metadataApi
        .metadataTable(fqn)
        .then((value) => {
          if (active) setDetail(value);
        })
        .catch((reason) => {
          if (active) setError((reason as Error).message);
        });
    return () => {
      active = false;
    };
  }, [fqn]);
  const copyAnalysisRequest = async (kind: keyof typeof diagnosisRequests) => {
    const fqn = detail?.reference.fully_qualified_name;
    if (!fqn) return;
    const request = diagnosisRequests[kind];
    const prompt = `$${request.skill}\nOpenMetadata 테이블 ${fqn}를 분석해줘.\n${request.scope}\n승인하거나 적용하지는 마.`;
    try {
      if (navigator.clipboard) await navigator.clipboard.writeText(prompt);
      else {
        const input = document.createElement("textarea");
        input.value = prompt;
        input.style.position = "fixed";
        input.style.opacity = "0";
        document.body.appendChild(input);
        try {
          input.select();
          if (!document.execCommand("copy")) throw new Error("copy_failed");
        } finally {
          input.remove();
        }
      }
    } catch {
      setError(
        "클립보드에 복사하지 못했습니다. 브라우저의 복사 권한을 확인하세요.",
      );
      return;
    }
    setCopied(kind);
    window.setTimeout(() => setCopied(null), 2500);
  };

  const reviewSuggestion = async (decision: "approve" | "reject") => {
    if (!suggestion) return;
    setBusy(suggestion.suggestion_id);
    setError(null);
    try {
      setSuggestion(
        await suggestionApi.reviewSuggestion(
          suggestion.suggestion_id,
          decision,
        ),
      );
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const approveBinding = async () => {
    if (!suggestion?.resulting_binding) return;
    setBusy(suggestion.resulting_binding.binding_id);
    setError(null);
    try {
      await bindingApi.reviewBinding(
        suggestion.resulting_binding.binding_id,
        "approve",
        `Suggestion ${suggestion.suggestion_id} 검토 완료`,
      );
      setBindingApproved(true);
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const editDescription = (target: DescriptionEditTarget) => {
    if (!principal) {
      requestLogin();
      return;
    }
    setDescriptionTarget(target);
  };

  if (!detail)
    return (
      <div className="workspace-page">
        <Link to="/admin/data-catalog">← 데이터 자산</Link>
        {error ? (
          <p role="alert">{error}</p>
        ) : (
          <p role="status">자산을 조회하고 있습니다…</p>
        )}
      </div>
    );
  const visibleColumns = detail.columns.filter(
    (column) =>
      (columnFilter !== "missing" || !column.description?.trim()) &&
      [column.name, column.displayName, column.description].some((value) =>
        value
          ?.toLocaleLowerCase()
          .includes(columnQuery.trim().toLocaleLowerCase()),
      ),
  );
  const contextQuery = new URLSearchParams({
    asset: detail.reference.fully_qualified_name || fqn || "",
    assetId: detail.reference.entity_id,
  }).toString();
  return (
    <div className="workspace-page asset-page">
      <Link
        className="breadcrumb-link"
        to={
          params.get("returnTo")?.startsWith("/admin/data-catalog?")
            ? params.get("returnTo")!
            : "/admin/data-catalog"
        }
      >
        ← 목록으로
      </Link>
      <PageHeader
        title={detail.display_name || detail.name}
        description={detail.reference.fully_qualified_name}
        actions={
          <div className="page-actions">
            <button
              className="page-primary-link"
              onClick={() =>
                setParams((previous) => {
                  const next = new URLSearchParams(previous);
                  next.set("tab", "diagnosis");
                  return next;
                })
              }
            >
              진단 요청
            </button>
            <button
              onClick={() =>
                editDescription({
                  label: "테이블 설명",
                  current: detail.description || "",
                })
              }
            >
              설명 변경안
            </button>
            <Link to={`/admin/changes/review?${contextQuery}`}>
              이 자산의 제안
            </Link>
          </div>
        }
      />

      <div className="asset-summary">
        <span>
          컬럼 <strong>{detail.columns.length}</strong>
        </span>
        <span>
          소유자{" "}
          <strong>
            {detail.owners
              .map((owner) => String(owner.displayName || owner.name))
              .join(", ") || "미지정"}
          </strong>
        </span>
        <span>
          용어 <strong>{detail.glossary_terms.length}</strong>
        </span>
        <span>
          설명 <strong>{detail.description ? "등록" : "없음"}</strong>
        </span>
      </div>
      <nav className="workspace-tabs" aria-label="자산 상세 관점">
        {tabs.map((item) => (
          <button
            key={item.id}
            aria-current={tab === item.id ? "page" : undefined}
            onClick={() =>
              setParams((previous) => {
                const next = new URLSearchParams(previous);
                next.set("tab", item.id);
                return next;
              })
            }
          >
            {item.label}
          </button>
        ))}
      </nav>
      {tab === "diagnosis" && (
        <>
          {" "}
          <section className="asset-diagnosis" aria-label="자산 진단">
            <h3>자산 진단</h3>
            <AssetAssessmentPanel
              key={detail.reference.entity_id}
              detail={detail}
            />
            <details className="assessment-developer">
              <summary>개발용 Skill 요청</summary>
              <div className="page-actions">
                {(
                  Object.keys(diagnosisRequests) as Array<
                    keyof typeof diagnosisRequests
                  >
                ).map((kind) => (
                  <button key={kind} onClick={() => copyAnalysisRequest(kind)}>
                    {copied === kind
                      ? `${diagnosisRequests[kind].label} 요청 복사됨`
                      : `${diagnosisRequests[kind].label} 요청 복사`}
                  </button>
                ))}
              </div>
            </details>
          </section>
        </>
      )}
      {error && (
        <p role="alert" className="workspace-error">
          {error}
        </p>
      )}
      {descriptionSuggestion && (
        <div className="metadata-change-created" role="status">
          <div>
            <strong>설명 변경안을 검토 대기열에 등록했습니다.</strong>
            <span>OpenMetadata에는 아직 반영되지 않았습니다.</span>
          </div>
          <Link
            to={`/admin/changes/review?${contextQuery}&suggestion=${encodeURIComponent(descriptionSuggestion.suggestion_id)}`}
          >
            변경안 검토
          </Link>
        </div>
      )}
      {[
        "technical",
        "operations",
        "business",
        "governance",
        "lineage",
      ].includes(tab) && (
        <AssetContext tableId={detail.reference.entity_id} section={tab} />
      )}
      {tab === "columns" && (
        <>
          <div className="column-browser-controls">
            <label>
              컬럼 검색
              <input
                aria-label="컬럼 검색"
                placeholder="이름 또는 설명 검색"
                value={columnQuery}
                onChange={(event) => setColumnQuery(event.target.value)}
              />
            </label>
            <label>
              표시
              <select
                value={columnFilter}
                onChange={(event) => setColumnFilter(event.target.value)}
              >
                <option value="all">전체 컬럼</option>
                <option value="missing">설명 없는 컬럼</option>
              </select>
            </label>
          </div>
          <div className="asset-columns-wrap">
            <table className="asset-columns-table">
              <thead>
                <tr>
                  <th>컬럼</th>
                  <th>타입</th>
                  <th>설명</th>
                  <th>태그·용어</th>
                  <th>작업</th>
                </tr>
              </thead>
              <tbody>
                {visibleColumns.map((column) => (
                  <tr key={column.name}>
                    <td>
                      <strong>{column.displayName || column.name}</strong>
                      {column.displayName && <code>{column.name}</code>}
                    </td>
                    <td>
                      <code>{column.dataType || "—"}</code>
                    </td>
                    <td>
                      <p
                        className={
                          column.description ? "" : "asset-value-missing"
                        }
                      >
                        {column.description || "설명 없음"}
                      </p>
                    </td>
                    <td>
                      <div className="asset-labels">
                        {column.tags?.length ? (
                          column.tags.map((tag, index) => (
                            <span key={index}>
                              {String(tag.tagFQN || tag.name || "태그")}
                            </span>
                          ))
                        ) : (
                          <span className="asset-value-missing">없음</span>
                        )}
                      </div>
                    </td>
                    <td>
                      <div className="asset-column-actions">
                        <button
                          onClick={() =>
                            editDescription({
                              label: `${column.displayName || column.name} 컬럼 설명`,
                              current: column.description || "",
                              columnName: column.name,
                            })
                          }
                        >
                          설명 변경
                        </button>
                        <button
                          disabled={busy === column.name}
                          onClick={async () => {
                            if (!principal) {
                              requestLogin();
                              return;
                            }
                            setBusy(column.name);
                            setError(null);
                            setBindingApproved(false);
                            try {
                              setSuggestion(
                                await suggestionApi.suggestColumnBinding(
                                  detail.reference.entity_id,
                                  column.name,
                                ),
                              );
                            } catch (reason) {
                              setError((reason as Error).message);
                            } finally {
                              setBusy(null);
                            }
                          }}
                        >
                          {busy === column.name ? "생성 중…" : "연결 제안"}
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!visibleColumns.length && (
              <div className="asset-catalog-empty">
                조건에 맞는 컬럼이 없습니다.
              </div>
            )}
          </div>
          {suggestion && (
            <aside className="binding-candidate-review">
              <header>
                <div>
                  <span>BINDING SUGGESTION</span>
                  <h3>{suggestion.proposed_value.ontology_stable_key}</h3>
                </div>
                <b>{(suggestion.confidence * 100).toFixed(0)}%</b>
              </header>
              <div className="binding-candidate-path">
                <code>{suggestion.target_ref}</code>
                <span>↕</span>
                <code>{suggestion.proposed_value.ontology_stable_key}</code>
              </div>
              <h4>판정 근거</h4>
              <ul>
                {suggestion.evidence?.map((item) => (
                  <li key={item.evidence_id}>
                    <strong>{item.evidence_type}</strong>
                    <span>
                      {item.provenance?.score == null
                        ? "근거 확인"
                        : `${(item.provenance.score * 100).toFixed(0)}%`}
                    </span>
                  </li>
                ))}
              </ul>
              {!!suggestion.proposed_value.alternatives?.length && (
                <p>
                  다른 후보:{" "}
                  {suggestion.proposed_value.alternatives
                    .map(
                      (item) =>
                        `${item.stable_key} ${(item.score * 100).toFixed(0)}%`,
                    )
                    .join(" · ")}
                </p>
              )}
              {suggestion.status === "pending" && (
                <footer className="suggestion-actions">
                  <button
                    disabled={!principal || busy === suggestion.suggestion_id}
                    onClick={() => reviewSuggestion("reject")}
                  >
                    거절
                  </button>
                  <button
                    disabled={!principal || busy === suggestion.suggestion_id}
                    onClick={() => reviewSuggestion("approve")}
                  >
                    승인하고 Binding Draft 생성
                  </button>
                </footer>
              )}
              {suggestion.resulting_binding && !bindingApproved && (
                <>
                  <p className="candidate-notice">
                    Suggestion이 승인되어 Binding Draft가 생성되었습니다. 의미
                    연결은 별도 승인 전까지 활성화되지 않습니다.
                  </p>
                  <footer className="suggestion-actions">
                    <button
                      disabled={
                        !principal ||
                        busy === suggestion.resulting_binding.binding_id
                      }
                      onClick={approveBinding}
                    >
                      Binding Draft 검토·승인
                    </button>
                  </footer>
                </>
              )}
              {bindingApproved && (
                <p className="candidate-success">
                  Approved Binding으로 활성화되었습니다.
                </p>
              )}
            </aside>
          )}
        </>
      )}
      {tab === "evidence" && (
        <TableDataEvidence
          key={detail.reference.entity_id}
          tableId={detail.reference.entity_id}
        />
      )}
      {descriptionTarget && (
        <DescriptionChangeDialog
          target={descriptionTarget}
          busy={busy === "description-change"}
          onClose={() => setDescriptionTarget(null)}
          onSubmit={async (description) => {
            setBusy("description-change");
            setError(null);
            try {
              const created = await suggestionApi.suggestDescriptionChange(
                detail.reference.entity_id,
                description,
                descriptionTarget.columnName,
              );
              setDescriptionSuggestion(created);
              setDescriptionTarget(null);
            } catch (reason) {
              setError((reason as Error).message);
            } finally {
              setBusy(null);
            }
          }}
        />
      )}
    </div>
  );
}

function DescriptionChangeDialog({
  target,
  busy,
  onClose,
  onSubmit,
}: {
  target: DescriptionEditTarget;
  busy: boolean;
  onClose: () => void;
  onSubmit: (description: string) => Promise<void>;
}) {
  const [value, setValue] = useState(target.current);
  const unchanged = value.trim() === target.current.trim();
  return (
    <div className="validation-backdrop">
      <section
        className="metadata-change-dialog"
        role="dialog"
        aria-modal="true"
        aria-label="설명 변경안 작성"
      >
        <header>
          <div>
            <span className="page-eyebrow">METADATA CHANGE</span>
            <h2>{target.label}</h2>
          </div>
          <button type="button" onClick={onClose} disabled={busy}>
            닫기
          </button>
        </header>
        <p>
          변경안은 검토 대기열에 등록됩니다. 승인 시점에 현재 버전을 다시 확인한
          뒤 OpenMetadata에 반영합니다.
        </p>
        <div className="metadata-change-current">
          <span>현재 설명</span>
          <p>{target.current || "설명 없음"}</p>
        </div>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            void onSubmit(value);
          }}
        >
          <label>
            제안 설명
            <textarea
              autoFocus
              rows={8}
              maxLength={10000}
              value={value}
              onChange={(event) => setValue(event.target.value)}
            />
          </label>
          <footer>
            <span>{value.length.toLocaleString()} / 10,000</span>
            <div>
              <button type="button" onClick={onClose} disabled={busy}>
                취소
              </button>
              <button
                type="submit"
                disabled={busy || !value.trim() || unchanged}
              >
                {busy ? "등록 중…" : "검토 요청"}
              </button>
            </div>
          </footer>
        </form>
      </section>
    </div>
  );
}
