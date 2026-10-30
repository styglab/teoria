import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { FileText, RefreshCw, Plus } from "lucide-react";
import {
  processingApi,
  type InputDocument,
  type ProcessingDetail,
  type ProcessingRun,
} from "../../api/specification_processing";
import { AnalysisExplorer, type MappingStatus } from "./AnalysisExplorer";
import { workflowsApi } from "../../api/workflows";
import {
  PageHeader,
  PageState,
  FilterTabs,
} from "../../components/workspace/WorkspaceLayout";
import { CatalogPagination } from "../../components/workspace/CatalogPagination";
import { useAdminAccess } from "../access/AdminAccess";
const states: Record<string, string> = {
  running: "처리 중",
  completed: "완료",
  partial: "일부 완료",
  failed: "실패",
  extracted: "추출 완료",
};
const modes: Record<string, string> = {
  standard_management: "추출 표준 작성",
  document_processing: "고정 표준 적용",
};

export function SpecificationWorkspace() {
  const [params, setParams] = useSearchParams();
  const run = params.get("run");
  const tab = params.get("tab") || "evidence";
  const creating = params.get("new") === "1";
  const page = Math.max(0, Number(params.get("page")) || 0);
  const size = params.get("size") === "50" ? 50 : 25;
  const { principal } = useAdminAccess();
  const [uploadsEnabled, setUploadsEnabled] = useState(false);
  useEffect(() => {
    let active = true;
    processingApi
      .status()
      .then((value) => {
        if (active) setUploadsEnabled(value.uploads_enabled);
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, []);
  const [rows, setRows] = useState<ProcessingRun[] | null>(null);
  const [total, setTotal] = useState(0);
  const [detail, setDetail] = useState<ProcessingDetail | null>(null);
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [artifact, setArtifact] = useState<Record<string, unknown> | null>(
    null,
  );
  const [artifactError, setArtifactError] = useState("");
  const [artifactBusy, setArtifactBusy] = useState(false);
  const previewSequence = useRef(0);
  const rawPreviewSequence = useRef(0);
  const [normalization, setNormalization] = useState<Record<
    string,
    unknown
  > | null>(null);
  const [mappingStatus, setMappingStatus] = useState<MappingStatus>("missing");
  const [rawPreview, setRawPreview] = useState<Record<string, unknown> | null>(
    null,
  );
  const update = (values: Record<string, string>) =>
    setParams((previous) => {
      const next = new URLSearchParams(previous);
      Object.entries(values).forEach(([k, v]) =>
        v ? next.set(k, v) : next.delete(k),
      );
      return next;
    });
  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    setError("");
    setRows(null);
    setDetail(null);
    setArtifact(null);
    setRawPreview(null);
    setNormalization(null);
    setMappingStatus("missing");
    setArtifactBusy(false);
    setArtifactError("");
    previewSequence.current += 1;
    rawPreviewSequence.current += 1;
    const load = async () => {
      try {
        if (run) {
          const value = await processingApi.detail(run);
          if (active) {
            setDetail(value);
            if (value.run.status === "running") timer = setTimeout(load, 5000);
          }
        } else {
          const value = await processingApi.runs(page, size);
          if (active) {
            setRows(value.items);
            setTotal(value.total);
          }
        }
      } catch (reason) {
        if (active) setError((reason as Error).message);
      }
    };
    if (!creating) void load();
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [run, page, size, refresh, creating]);
  useEffect(() => {
    const reference = detail?.artifacts.find((a) =>
      a.key.endsWith("extracted.json"),
    );
    if (!reference || !run) return;
    const sequence = ++previewSequence.current;
    let active = true;
    setArtifactBusy(true);
    setArtifactError("");
    processingApi
      .artifact(run, reference.key)
      .then((value) => {
        if (active && sequence === previewSequence.current) setArtifact(value);
      })
      .catch((reason: Error) => {
        if (active && sequence === previewSequence.current)
          setArtifactError(reason.message);
      })
      .finally(() => {
        if (active && sequence === previewSequence.current)
          setArtifactBusy(false);
      });
    return () => {
      active = false;
    };
  }, [detail, run]);
  useEffect(() => {
    const reference = detail?.artifacts.find((a) =>
      a.key.endsWith("normalized.json"),
    );
    setNormalization(null);
    if (!reference || !run) {
      setMappingStatus("missing");
      return;
    }
    let active = true;
    setMappingStatus("loading");
    processingApi
      .artifact(run, reference.key)
      .then((value) => {
        if (active) {
          setNormalization(value);
          setMappingStatus(
            Array.isArray(value.attributes) ? "available" : "error",
          );
        }
      })
      .catch(() => {
        if (active) setMappingStatus("error");
      });
    return () => {
      active = false;
    };
  }, [detail, run]);
  const preview = async (key: string) => {
    const sequence = ++rawPreviewSequence.current;
    setArtifactBusy(true);
    setArtifactError("");
    setRawPreview(null);
    try {
      const value = await processingApi.artifact(run!, key);
      if (sequence === rawPreviewSequence.current) setRawPreview(value);
    } catch (reason) {
      if (sequence === rawPreviewSequence.current)
        setArtifactError((reason as Error).message);
    } finally {
      if (sequence === rawPreviewSequence.current) setArtifactBusy(false);
    }
  };
  return (
    <div
      className={`workspace-page specification-workspace ${run && !creating ? "specification-analysis-result" : ""}`}
    >
      <PageHeader
        title="FormatID"
        description="규격서 기반 물품 구조화·분석. 물품·구성품의 관계와 규격·속성을 탐색하고 원문 근거를 확인합니다."
        actions={
          <>
            {!creating && (
              <button
                className="page-primary-link"
                disabled={
                  !uploadsEnabled ||
                  !principal?.roles.includes("metadata_admin")
                }
                onClick={() => update({ new: "1", run: "", tab: "" })}
              >
                <Plus size={14} />새 분석 시작
              </button>
            )}
            <button
              className="page-icon-button"
              aria-label="규격서 새로고침"
              onClick={() => setRefresh((v) => v + 1)}
            >
              <RefreshCw size={16} />
            </button>
          </>
        }
      />
      {error && (
        <p role="alert" className="workspace-error">
          {error}{" "}
          <button onClick={() => setRefresh((v) => v + 1)}>다시 조회</button>
        </p>
      )}
      {creating && !uploadsEnabled ? (
        <PageState
          title="문서 업로드가 설정되지 않았습니다"
          description="입력 저장소와 Worker 연결 설정을 확인하세요."
        />
      ) : creating ? (
        <>
          <button
            className="breadcrumb-link"
            onClick={() => update({ new: "" })}
          >
            ← 처리 목록
          </button>
          <ProcessingForm
            onStarted={(flowId, runId) =>
              update({ new: "", flow: flowId, pending: runId })
            }
          />
        </>
      ) : run ? (
        <>
          <button
            className="breadcrumb-link"
            onClick={() => update({ run: "", tab: "" })}
          >
            ← 처리 목록
          </button>
          {!detail ? (
            <PageState
              loading={!error}
              title={
                error
                  ? "처리 결과를 조회하지 못했습니다"
                  : "처리 결과를 조회하고 있습니다…"
              }
            />
          ) : (
            <>
              <div className="analysis-run-summary">
                <span className="analysis-status">
                  {states[detail.run.status]}
                </span>
                <span>{modes[detail.run.mode]}</span>
                <time>
                  {new Date(detail.run.started_at).toLocaleString("ko-KR")}
                </time>
                <Link
                  className="operations-link"
                  to={`/admin/workflows?pipeline=${detail.run.mode === "document_processing" ? "specification-document-processing" : "specification-standard-management"}&tab=history`}
                >
                  실행 이력
                </Link>
              </div>
              <FilterTabs
                label="규격서 결과"
                value={tab}
                onChange={(tab) => update({ tab })}
                items={[
                  { id: "evidence", label: "분석" },
                  { id: "documents", label: "문서별 결과" },
                  { id: "artifacts", label: "산출물·실행 정보" },
                ]}
              />
              <div className="specification-detail-scroll">
                {tab === "documents" && (
                  <>
                    <div className="page-table-wrap">
                      <table className="page-table">
                        <thead>
                          <tr>
                            <th>문서</th>
                            <th>결과</th>
                            <th>요약</th>
                          </tr>
                        </thead>
                        <tbody>
                          {detail.documents.map((d) => (
                            <tr key={d.document_id}>
                              <td>{d.document_id}</td>
                              <td>{states[d.status] || d.status}</td>
                              <td>
                                <dl className="specification-summary">
                                  {Object.entries(d.result_summary)
                                    .filter(([, v]) => typeof v !== "object")
                                    .map(([key, value]) => (
                                      <div key={key}>
                                        <dt>{key}</dt>
                                        <dd>{String(value)}</dd>
                                      </div>
                                    ))}
                                </dl>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                      {!detail.documents.length && (
                        <PageState
                          title={
                            detail.run.status === "running"
                              ? "문서를 처리하고 있습니다"
                              : "문서별 결과가 없습니다"
                          }
                        />
                      )}
                    </div>
                    {detail.run.error_code && (
                      <p role="alert">실패 원인: {detail.run.error_code}</p>
                    )}
                    <details>
                      <summary>실행 요약</summary>
                      <pre>{JSON.stringify(detail.run.summary, null, 2)}</pre>
                    </details>
                  </>
                )}
                {tab === "artifacts" && (
                  <div className="page-table-wrap">
                    <table className="page-table">
                      <thead>
                        <tr>
                          <th>산출물</th>
                          <th>크기</th>
                          <th>열기</th>
                        </tr>
                      </thead>
                      <tbody>
                        {detail.artifacts.map((a) => (
                          <tr key={a.key}>
                            <td>
                              <strong>{a.key.split("/").at(-1)}</strong>
                              <details>
                                <summary>저장 참조</summary>
                                <code>{a.uri}</code>
                                <code>{a.sha256}</code>
                              </details>
                            </td>
                            <td>{(a.size_bytes / 1024).toFixed(1)}KB</td>
                            <td>
                              {a.media_type.includes("json") && (
                                <button
                                  className="operations-link"
                                  disabled={artifactBusy}
                                  onClick={() => preview(a.key)}
                                >
                                  결과 보기
                                </button>
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
                {artifactBusy && (
                  <PageState loading title="산출물을 확인하고 있습니다…" />
                )}
                {artifactError && (
                  <p role="alert" className="workspace-error">
                    {artifactError}
                  </p>
                )}
                {artifact && tab === "evidence" && (
                  <AnalysisExplorer
                    value={artifact}
                    normalization={normalization}
                    mappingStatus={mappingStatus}
                  />
                )}
                {!artifact &&
                  !artifactBusy &&
                  !artifactError &&
                  tab === "evidence" && (
                    <PageState
                      title="문서 분석 결과가 아직 없습니다"
                      description="추출 결과가 저장되면 구성품과 속성을 확인할 수 있습니다."
                    />
                  )}
                {rawPreview && tab === "artifacts" && (
                  <details open>
                    <summary>JSON 산출물 원문</summary>
                    <pre>{JSON.stringify(rawPreview, null, 2)}</pre>
                  </details>
                )}
              </div>
            </>
          )}
        </>
      ) : (
        <>
          {params.get("flow") && (
            <div className="context-banner">
              <span>
                실행 요청을 제출했습니다. 처리 기록은 Worker가 실행을 시작하면
                표시됩니다.
              </span>
              <Link
                to={`/admin/workflows?run=${params.get("flow")}&tab=history`}
              >
                실행 상태 확인
              </Link>
              <button onClick={() => setRefresh((v) => v + 1)}>
                결과 새로고침
              </button>
            </div>
          )}
          <div className="page-table-wrap specification-run-list">
            <table className="page-table">
              <thead>
                <tr>
                  <th>처리 실행</th>
                  <th>방식</th>
                  <th>상태</th>
                  <th>시작 시각</th>
                </tr>
              </thead>
              <tbody>
                {rows?.map((item) => (
                  <tr key={item.run_id}>
                    <td>
                      <button
                        className="operations-link"
                        onClick={() =>
                          update({
                            run: item.run_id,
                            tab: "",
                            flow: "",
                            pending: "",
                          })
                        }
                      >
                        {item.run_id}
                      </button>
                    </td>
                    <td>{modes[item.mode] || item.mode}</td>
                    <td>{states[item.status] || item.status}</td>
                    <td>{new Date(item.started_at).toLocaleString("ko-KR")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {rows === null ? (
              <PageState
                loading={!error}
                title={
                  error
                    ? "처리 이력을 조회하지 못했습니다"
                    : "처리 이력을 조회하고 있습니다…"
                }
              />
            ) : (
              !rows.length && (
                <PageState
                  title="처리한 규격서가 없습니다"
                  description="새 분석 시작에서 파일과 처리 방식을 선택하세요."
                />
              )
            )}
          </div>
          <CatalogPagination
            page={page}
            pageSize={size}
            total={total}
            loading={rows === null}
            error={!!error}
            onPageChange={(page) => update({ page: String(page) })}
            onPageSizeChange={(size) =>
              update({ size: String(size), page: "" })
            }
          />
        </>
      )}
    </div>
  );
}

function ProcessingForm({
  onStarted,
}: {
  onStarted: (flow: string, run: string) => void;
}) {
  const [files, setFiles] = useState<File[]>([]);
  const [mode, setMode] = useState("standard_management");
  const [classification, setClassification] = useState("");
  const [model, setModel] = useState("");
  const [uri, setUri] = useState("");
  const [checksum, setChecksum] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [progress, setProgress] = useState("");
  const [runId] = useState(
    () =>
      `ui_${Date.now()}_${crypto.getRandomValues(new Uint32Array(1))[0].toString(16)}`,
  );
  const [documents, setDocuments] = useState<InputDocument[]>([]);
  const [key] = useState(() => {
    const bytes = crypto.getRandomValues(new Uint8Array(16));
    bytes[6] = (bytes[6] & 15) | 64;
    bytes[8] = (bytes[8] & 63) | 128;
    const h = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join(
      "",
    );
    return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
  });
  return (
    <form
      className="processing-form"
      onSubmit={async (event) => {
        event.preventDefault();
        if (busy) return;
        setBusy(true);
        setError("");
        try {
          if (files.some((file) => file.size > 40 * 1024 * 1024))
            throw Error("파일은 각각 40MB 이하로 선택하세요.");
          const uploaded = [...documents];
          for (let i = uploaded.length; i < files.length; i++) {
            setProgress(`문서 등록 ${i + 1}/${files.length}`);
            uploaded.push(await processingApi.upload(files[i]));
            setDocuments([...uploaded]);
          }
          setProgress("처리 실행 요청 중…");
          const manifest = {
            run_id: runId,
            mode,
            documents: uploaded,
            artifact_root: "file:///app/specification_artifacts",
            ...(classification ? { classification_code: classification } : {}),
            ...(model ? { model } : {}),
            dictionary_auto_approve: false,
            ...(mode === "document_processing"
              ? { standard: { uri, sha256: checksum } }
              : {}),
          };
          const id =
            mode === "document_processing"
              ? "specification-document-processing"
              : "specification-standard-management";
          const result = await workflowsApi.run(id, key, { manifest });
          onStarted(result.flow_run_id, runId);
        } catch (reason) {
          setError((reason as Error).message);
        } finally {
          setBusy(false);
        }
      }}
    >
      <h3>1. 문서 선택</h3>
      <label>
        규격서 파일
        <input
          type="file"
          required
          multiple
          accept=".hwp,.hwpx,.pdf,.docx,.xlsx,.pptx"
          disabled={busy}
          onChange={(event) => {
            setFiles(Array.from(event.target.files || []));
            setDocuments([]);
          }}
        />
        <small>
          문서당 최대 40MB, 최대 100개. Worker가 읽을 수 있는 입력 저장소에
          등록됩니다.
        </small>
      </label>
      <h3>2. 처리 방식</h3>
      <label>
        작업
        <select
          value={mode}
          onChange={(event) => setMode(event.target.value)}
          disabled={busy}
        >
          <option value="standard_management">
            문서 추출 및 표준 후보 작성
          </option>
          <option value="document_processing">고정 표준 적용</option>
        </select>
      </label>
      <label>
        분류 코드(선택)
        <input
          value={classification}
          pattern="[0-9]{10}"
          placeholder="물품 분류 코드 10자리"
          onChange={(event) => setClassification(event.target.value)}
          disabled={busy}
        />
      </label>
      {mode === "document_processing" && (
        <>
          <label>
            고정 표준 URI
            <input
              required
              value={uri}
              onChange={(event) => setUri(event.target.value)}
              placeholder="file:// 또는 s3://"
              disabled={busy}
            />
          </label>
          <label>
            표준 checksum(SHA256)
            <input
              required
              pattern="[a-f0-9]{64}"
              value={checksum}
              onChange={(event) => setChecksum(event.target.value)}
              disabled={busy}
            />
          </label>
        </>
      )}
      <details>
        <summary>고급 설정</summary>
        <label>
          추론 모델(선택)
          <input
            value={model}
            onChange={(event) => setModel(event.target.value)}
            disabled={busy}
          />
          <small>비우면 Worker 설정을 사용합니다.</small>
        </label>
        <p>
          추출된 의미 후보는 자동 승인하지 않습니다. 검토 후 게시 절차를
          진행하세요.
        </p>
      </details>
      <h3>3. 실행</h3>
      <p className="operations-note">
        원본 문서와 추출 결과는 저장소에 유지됩니다. 실행 상태는 파이프라인에서
        확인할 수 있습니다.
      </p>
      {error && (
        <p role="alert" className="workspace-error">
          {error}
        </p>
      )}
      {busy && <p role="status">{progress}</p>}
      <button
        className="page-primary-link"
        type="submit"
        disabled={busy || !files.length || files.length > 100}
      >
        {busy ? "처리 요청 중…" : "문서 처리 실행"}
      </button>
    </form>
  );
}
