import { AssessmentHistory } from "./AssessmentHistory";
import { assessmentErrors as errors } from "./assessment_messages";
import { AdminApiError } from "../../../api/http_client";
import { useEffect, useRef, useState } from "react";
import { ChevronDown, Play, Search } from "lucide-react";
import {
  assetAssessmentApi,
  type AssessmentScope,
  type DisclosureContext,
  type AssetAssessment,
} from "../../../api/asset_assessment";
import { type MetadataTableDetail } from "../../../api/metadata";
import { useAdminAccess } from "../../access/AdminAccess";
import "./asset_assessment.css";

const scopes: Array<[AssessmentScope, string]> = [
  ["metadata_enrichment", "메타데이터 정비"],
  ["semantic_alignment", "업무 의미 연결"],
  ["disclosure_assessment", "개방 적합성 진단"],
];
const scopeDescriptions: Record<AssessmentScope, string> = {
  metadata_enrichment: "테이블·컬럼 설명 보완",
  semantic_alignment: "기존 업무 개념과 연결",
  disclosure_assessment: "법령 근거와 개방 조건 검토",
};

export function AssetAssessmentPanel({
  detail,
}: {
  detail: MetadataTableDetail;
}) {
  const { principal, requestLogin } = useAdminAccess();
  const [selected, setSelected] = useState<AssessmentScope[]>([
    "metadata_enrichment",
    "semantic_alignment",
  ]);
  const [columns, setColumns] = useState<string[]>([]);
  const [columnQuery, setColumnQuery] = useState("");
  const [disclosureContext, setDisclosureContext] =
    useState<DisclosureContext>("public_release");
  const [items, setItems] = useState<AssetAssessment[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const requestVersion = useRef(0);
  const hasActive = items.some(
    (item) => item.status === "queued" || item.status === "running",
  );
  useEffect(() => {
    if (!principal) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    const load = async () => {
      const version = requestVersion.current;
      try {
        const result = await assetAssessmentApi.assetAssessments(
          detail.reference.entity_id,
        );
        if (!active || version !== requestVersion.current) return;
        setItems(result.items);
        if (
          result.items.some(
            (item) => item.status === "queued" || item.status === "running",
          )
        )
          timer = setTimeout(load, 3000);
      } catch (reason) {
        if (active) setError((reason as Error).message);
      }
    };
    void load();
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [principal?.actor, detail.reference.entity_id, hasActive]);

  const start = async () => {
    if (!principal) {
      requestLogin();
      return;
    }
    setBusy(true);
    setError(null);
    requestVersion.current += 1;
    try {
      const item = await assetAssessmentApi.createAssetAssessment({
        table_fqn: detail.reference.fully_qualified_name!,
        scopes: selected,
        column_names: columns,
        disclosure_context: disclosureContext,
      });
      setItems((previous) =>
        [
          item,
          ...previous.filter((old) => old.assessment_id !== item.assessment_id),
        ].slice(0, 10),
      );
    } catch (reason) {
      const message = (reason as Error).message;
      setError(
        reason instanceof AdminApiError && reason.code
          ? errors[reason.code] || message
          : message,
      );
    } finally {
      setBusy(false);
    }
  };
  const visibleColumns = detail.columns.filter((column) =>
    column.name
      .toLocaleLowerCase()
      .includes(columnQuery.trim().toLocaleLowerCase()),
  );
  return (
    <section className="assessment-panel" aria-label="자동 자산 진단">
      <p className="assessment-intro">
        선택한 항목을 진단해 변경안을 제안합니다. 검토·승인 후 반영됩니다.
      </p>
      <fieldset className="assessment-scopes" disabled={busy}>
        <legend>진단 항목</legend>
        <div className="assessment-scope-grid">
          {scopes.map(([id, label]) => (
            <label
              className={`assessment-scope${selected.includes(id) ? " is-selected" : ""}`}
              key={id}
            >
              <input
                type="checkbox"
                aria-label={label}
                checked={selected.includes(id)}
                onChange={(event) =>
                  setSelected((previous) =>
                    event.target.checked
                      ? [...previous, id]
                      : previous.filter((value) => value !== id),
                  )
                }
              />
              <span>
                <strong>{label}</strong>
                <small>{scopeDescriptions[id]}</small>
              </span>
            </label>
          ))}
        </div>
      </fieldset>
      <details className="assessment-column-picker">
        <summary>
          <span>
            대상 컬럼 선택 <small>최대 30개</small>
          </span>
          <span className="assessment-picker-count">
            {columns.length
              ? `${columns.length}개 선택`
              : detail.columns.length > 30
                ? "선택 필요"
                : "전체 컬럼"}
          </span>
          <ChevronDown size={15} aria-hidden="true" />
        </summary>
        <div className="assessment-picker-body">
          <div className="assessment-picker-toolbar">
            <label className="assessment-column-search">
              <Search size={15} aria-hidden="true" />
              <input
                aria-label="진단 대상 컬럼 검색"
                placeholder="컬럼 이름 검색"
                value={columnQuery}
                onChange={(event) => setColumnQuery(event.target.value)}
              />
            </label>
            <button
              type="button"
              disabled={!columns.length || busy}
              onClick={() => setColumns([])}
            >
              선택 초기화
            </button>
          </div>
          <div
            className="assessment-column-options"
            role="group"
            aria-label="대상 컬럼"
          >
            {visibleColumns.map((column) => (
              <label key={column.name}>
                <input
                  type="checkbox"
                  aria-label={column.name}
                  checked={columns.includes(column.name)}
                  disabled={
                    busy ||
                    (!columns.includes(column.name) && columns.length >= 30)
                  }
                  onChange={(event) =>
                    setColumns((previous) =>
                      event.target.checked
                        ? [...previous, column.name]
                        : previous.filter((name) => name !== column.name),
                    )
                  }
                />
                <span>{column.name}</span>
              </label>
            ))}
            {!visibleColumns.length && <p>검색 결과가 없습니다.</p>}
          </div>
          <p className="assessment-note">
            미선택 시 전체 컬럼을 진단합니다. 원본 샘플 데이터는 사용하지
            않습니다.
          </p>
        </div>
      </details>
      {selected.includes("disclosure_assessment") && (
        <div className="assessment-disclosure">
          <label>
            개방 상황
            <select
              value={disclosureContext}
              onChange={(event) =>
                setDisclosureContext(
                  event.target.value as typeof disclosureContext,
                )
              }
            >
              <option value="public_release">일반 공개</option>
              <option value="restricted_sharing">제한된 대상에게 제공</option>
            </select>
          </label>
          <p>
            법령 근거를 포함한 검토 초안이며, 태그는 자동 적용되지 않습니다.
          </p>
        </div>
      )}
      <div className="assessment-run-row">
        <p className="assessment-note">
          {!columns.length && detail.columns.length > 30
            ? "진단할 컬럼을 선택하세요. 한 번에 최대 30개까지 가능합니다."
            : `${selected.length}개 진단 항목 · ${columns.length || detail.columns.length}개 컬럼`}
        </p>
        <button
          className="assessment-run-button"
          disabled={
            busy ||
            !selected.length ||
            columns.length > 30 ||
            (!columns.length && detail.columns.length > 30)
          }
          onClick={start}
        >
          <Play size={14} aria-hidden="true" />
          {busy ? "진단 요청 중…" : "진단 실행"}
        </button>
      </div>
      {error && (
        <p className="assessment-error" role="alert">
          {error}
        </p>
      )}
      <AssessmentHistory items={items} />
    </section>
  );
}
