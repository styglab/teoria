import { Button } from "../../components/ui/button";
import { goodsDictionaryApi, type ApplicationStandard } from "../../api/goods_dictionary";
import {
  SpecificationCatalog,
  CatalogDocumentView,
  DocumentComparison,
} from "./SpecificationCatalog";
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
import { RunQuality, VersionQuality } from "./ProcessingQuality";
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
  standard_management: "규격서 구조화",
  document_processing: "고정 표준 적용",
};

export function SpecificationWorkspace() {
  const [params] = useSearchParams();
  if (
    params.get("run") ||
    params.get("new") ||
    params.get("flow") ||
    params.get("view") === "runs"
  )
    return <RunWorkspace />;
  if (params.get("document"))
    return (
      <CatalogDocumentView
        key={params.get("document")}
        id={params.get("document")!}
      />
    );
  if (params.get("compare"))
    return <DocumentComparison ids={params.get("compare")!.split(",")} />;
  return <SpecificationCatalog />;
}
function RunWorkspace() {
  const [params, setParams] = useSearchParams();
  const run = params.get("run");
  const requestedTab = params.get("tab");
  const tab =
    requestedTab === "documents" || requestedTab === "artifacts"
      ? requestedTab
      : "evidence";
  useEffect(() => {
    if (requestedTab === "review" || params.has("review_revision")) {
      setParams(
        (previous) => {
          const next = new URLSearchParams(previous);
          if (next.get("tab") === "review") next.set("tab", "evidence");
          next.delete("review_revision");
          return next;
        },
        { replace: true },
      );
    }
  }, [requestedTab, params, setParams]);
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
  const [operations, setOperations] = useState<Awaited<ReturnType<typeof processingApi.operations>> | null>(null);
  const [operationsError, setOperationsError] = useState("");
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    if (run || creating) return;
    let active = true;
    setOperations(null); setOperationsError("");
    processingApi.operations().then(value => { if (active) setOperations(value); })
      .catch(() => { if (active) setOperationsError("운영 현황을 조회하지 못했습니다."); });
    return () => { active = false; };
  }, [run, creating, refresh]);
  const [detail, setDetail] = useState<ProcessingDetail | null>(null);
  const automaticApproval = detail?.run.summary.automatic_application_standard as
    {status: string; release_id?: string; reason?: string} | undefined;
  const [error, setError] = useState("");
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
        description="규격서별 처리 결과에서 엔티티·관계·속성과 원문 근거를 확인합니다."
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
      {creating && !uploadsEnabled && !params.get("reprocess") ? (
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
            key={`${params.get("reprocess") || "new"}:${params.get("release") || ""}:${params.get("retry") || ""}`}
            retryFailed={params.get("retry") === "failed"}
            sourceRun={params.get("reprocess") || undefined}
            initialReleaseId={params.get("release") || undefined}
            onStarted={(flowId, runId) =>
              update({ new: "", reprocess: "", view: "runs", flow: flowId, pending: runId })
            }
          />
        </>
      ) : run ? (
        <>
          <button
            className="breadcrumb-link"
            onClick={() => update({ run: "", tab: "", document: "" })}
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
              <RunQuality summary={detail.run.summary} />
              <section aria-label="검토와 다음 작업" className="context-banner">
                <div>
                  <strong>검토와 다음 작업</strong>
                  <p>실행 상태와 업무 정확도는 별개입니다. 원문 근거와 보류 항목을 확인하세요.</p>
                  {detail.run.status === "partial" && <p>일부 항목이 처리되지 않았거나 보류됐습니다. 결과를 검토한 뒤 기준을 수정해 다시 처리할 수 있습니다.</p>}
                  {detail.run.status === "failed" && <p>문서별 실패 원인과 실행 이력을 확인한 뒤 다시 처리하세요.</p>}
                  {detail.run.mode === "standard_management" && <p>원문 표현의 의미 연결을 검토하고, 사용할 표준과 사전 버전을 처리 기준으로 승인하세요.</p>}
                </div>
                <Link to="/admin/domains/goods/dictionary">표현·의미 연결 검토</Link>
                {automaticApproval?.status === "approved" && <p>처리 기준이 자동 승인됐습니다. 이 버전으로 같은 문서를 다시 처리할 수 있습니다.</p>}
                {automaticApproval?.status === "held" && <p>자동 승인이 보류됐습니다. 적용 규칙과 사전 버전을 확인하세요.</p>}
                {principal?.roles.includes("ontology_owner") && automaticApproval?.status !== "approved" && detail.run.mode === "standard_management" && ["completed", "partial"].includes(detail.run.status) &&
                  <Link to={`/admin/specifications/standards?source_run=${encodeURIComponent(run!)}`}>이 결과로 처리 기준 승인</Link>}
                {principal?.roles.includes("metadata_admin") && ["completed", "partial", "failed"].includes(detail.run.status) &&
                  <Link to={`/admin/specifications?new=1&reprocess=${encodeURIComponent(run!)}${automaticApproval?.release_id ? `&release=${encodeURIComponent(automaticApproval.release_id)}` : ""}`}>같은 문서를 승인된 기준으로 재처리</Link>}
                {principal?.roles.includes("metadata_admin") && detail.documents.some(d => d.status === "failed" || Number(d.result_summary.quarantined_attributes || 0) > 0) &&
                  <Link to={`/admin/specifications?new=1&reprocess=${encodeURIComponent(run!)}&retry=failed`}>실패·검증 보류 문서만 다시 추출</Link>}
              </section>
              <FilterTabs
                label="규격서 결과"
                value={tab}
                onChange={(tab) => update({ tab })}
                items={[
                  { id: "evidence", label: "규격서 결과" },
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
                              <td>
                                <button
                                  className="operations-link"
                                  onClick={() =>
                                    update({
                                      tab: "evidence",
                                      document: d.document_id,
                                    })
                                  }
                                >
                                  {d.document_id}
                                </button>
                              </td>
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
                    runId={run || undefined}
                    key={run}
                    value={artifact}
                    documentId={params.get("document") || ""}
                    onDocumentChange={(document) => update({ document })}
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
              {params.get("pending") && <Link to={`/admin/specifications?run=${encodeURIComponent(params.get("pending")!)}`}>처리 결과 확인</Link>}
            </div>
          )}
          <div className="page-table-wrap specification-run-list">
            {operations && <section aria-label="최근 처리 현황">
              <p>최근 {operations.days}일 · 실행 실패 {operations.runs.failed || 0}건 · 일부 완료 {operations.runs.partial || 0}건 · 처리 중 {operations.runs.running || 0}건</p>
              <p>문서 실패 {operations.documents.failed || 0}건 · 일부 추출 {operations.documents.partial || 0}건. 독립 품질 평가 결과는 별도로 확인해야 합니다.</p>
              <VersionQuality versions={operations.quality_versions || []} />
            </section>}
            {operationsError && <p role="status">{operationsError}</p>}
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
                            document: "",
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
  sourceRun,
  initialReleaseId,
  retryFailed = false,
}: {
  onStarted: (flow: string, run: string) => void;
  sourceRun?: string;
  initialReleaseId?: string;
  retryFailed?: boolean;
}) {
  const { principal } = useAdminAccess();
  const canAutoApprove = Boolean(principal?.roles.includes("ontology_owner"));
  const [files, setFiles] = useState<File[]>([]);
  const [mode, setMode] = useState(sourceRun && !retryFailed ? "document_processing" : "standard_management");
  const [autoApplyPreference, setAutoApply] = useState(true);
  const autoApply = canAutoApprove && autoApplyPreference;
  const [classification, setClassification] = useState("");
  const [model, setModel] = useState("");
  const [releaseId, setReleaseId] = useState("");
  const [releases, setReleases] = useState<ApplicationStandard[]>([]);
  const [initialRelease, setInitialRelease] = useState<ApplicationStandard | null>(null);
  const [releasePage, setReleasePage] = useState(0);
  const [releaseTotal, setReleaseTotal] = useState(0);
  const [releaseError, setReleaseError] = useState("");
  useEffect(() => {
    if (!initialReleaseId) return;
    let active = true;
    goodsDictionaryApi.standard(initialReleaseId).then(value => {
      if (active) { setInitialRelease(value); setReleaseId(value.release_id); }
    }).catch(reason => { if (active) setReleaseError(reason.message); });
    return () => { active = false; };
  }, [initialReleaseId]);
  useEffect(() => {
    if (mode !== "document_processing") return;
    let active = true; setReleaseError("");
    if (!initialReleaseId) setReleaseId("");
    goodsDictionaryApi.standards(releasePage).then(value => {
      if (active) { setReleases(value.items); setReleaseTotal(value.total); }
    }).catch(reason => { if (active) setReleaseError(reason.message); });
    return () => { active = false; };
  }, [mode, releasePage, initialReleaseId]);
  const availableReleases = initialRelease && !releases.some(release => release.release_id === initialRelease.release_id)
    ? [initialRelease, ...releases] : releases;
  const selectedRelease = availableReleases.find(release => release.release_id === releaseId && release.status === "approved");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [progress, setProgress] = useState("");
  const [runId] = useState(
    () =>
      `ui_${Date.now()}_${crypto.getRandomValues(new Uint32Array(1))[0].toString(16)}`,
  );
  const [documents, setDocuments] = useState<InputDocument[]>([]);
  const [inputLoading, setInputLoading] = useState(Boolean(sourceRun));
  useEffect(() => {
    if (!sourceRun) return;
    let active = true;
    (retryFailed ? processingApi.inputs(sourceRun, true) : processingApi.inputs(sourceRun)).then(value => {
      if (active) {
        setDocuments(value.documents);
        setClassification(value.classification_code || "");
      }
    }).catch(reason => { if (active) setError(reason.message); })
      .finally(() => { if (active) setInputLoading(false); });
    return () => { active = false; };
  }, [sourceRun, retryFailed]);
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
        if (busy || inputLoading) return;
        setBusy(true);
        setError("");
        try {
          if (files.some((file) => file.size > 40 * 1024 * 1024))
            throw Error("파일은 각각 40MB 이하로 선택하세요.");
          if (mode === "document_processing" && !selectedRelease) throw Error("승인된 처리 기준을 선택하세요.");
          const uploaded = [...documents];
          if (!files.length && !uploaded.length) throw Error("처리할 문서가 없습니다.");
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
            ...(mode !== "document_processing" && classification ? { classification_code: classification } : {}),
            ...(model ? { model } : {}),
            dictionary_auto_approve: mode === "standard_management" && autoApply,
            dictionary_meaning_auto_approve: false,
            auto_apply_source_literals: mode === "standard_management" && autoApply,
            auto_approve_application_standard: mode === "standard_management" && autoApply,
            ...(mode === "document_processing" && selectedRelease
              ? { application_release_id: selectedRelease.release_id,
                  standard: selectedRelease.standard_ref,
                  dictionary_standard: selectedRelease.dictionary_ref,
                  ...(selectedRelease.classification_code ? { classification_code: selectedRelease.classification_code } : {}) }
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
      {sourceRun ? <div>
        <p>기존 실행의 원본과 해시를 재사용합니다. 새 실행 결과는 이전 결과와 별도로 보존됩니다.</p>
        {inputLoading ? <p role="status">원본 문서 확인 중…</p> :
          <ul>{documents.map(document => <li key={document.document_id}>{document.filename}</li>)}</ul>}
      </div> : <>
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
      </>}
      <h3>2. 처리 방식</h3>
      <label>
        작업
        <select
          value={mode}
          onChange={(event) => setMode(event.target.value)}
          disabled={busy}
        >
          <option value="standard_management">규격서 구조화 추출</option>
          <option value="document_processing">고정 표준 적용</option>
        </select>
      </label>
      {mode === "standard_management" && <label>
        <input type="checkbox" checked={autoApply} disabled={busy || !canAutoApprove} onChange={event => setAutoApply(event.target.checked)} />
        원문 표현과 추출 기준을 자동 승인·적용
        <small>원문 근거가 확인된 항목을 적용하고 처리 기준 버전을 고정합니다. 모호한 항목은 보류합니다.</small>
      </label>}
      <label>
        분류 코드(선택)
        <input
          value={mode === "document_processing" ? selectedRelease?.classification_code || "" : classification}
          disabled={busy || mode === "document_processing"}
          pattern="[0-9]{10}"
          placeholder="물품 분류 코드 10자리"
          onChange={(event) => setClassification(event.target.value)}
        />
      </label>
      {mode === "document_processing" && (
        <>
          <label>
            승인된 처리 기준
            <select required disabled={busy} value={releaseId} onChange={event => setReleaseId(event.target.value)}>
              <option value="">표준·사전 버전 선택</option>
              {availableReleases.filter(release => release.status === "approved").map(release => <option key={release.release_id} value={release.release_id}>{release.name} · {release.classification_code || "미분류"}</option>)}
            </select>
          </label>
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" size="sm" type="button" disabled={busy || releasePage === 0} onClick={() => setReleasePage(page => page - 1)}>이전 처리 기준</Button>
            <Button variant="outline" size="sm" type="button" disabled={busy || (releasePage + 1) * 25 >= releaseTotal} onClick={() => setReleasePage(page => page + 1)}>다음 처리 기준</Button>
          </div>
          <Link to="/admin/specifications/standards">규격서 처리 기준 관리</Link>
          {releaseError && <p role="alert">{releaseError}</p>}
          {!releaseError && !releases.length && <p>승인된 처리 기준이 없습니다. 의미 관리 담당자가 규격서 처리 기준에서 먼저 승인해야 합니다.</p>}
          {selectedRelease && <p>표준과 사전이 함께 고정됩니다. 승인자: {selectedRelease.approved_by} · {selectedRelease.standard_kind === "ontology_profile" ? "Ontology 프로파일" : "추출용 표준 초안"}</p>}
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
          처리 결과에서 문서별 엔티티·관계·속성과 원문 근거를 확인할 수
          있습니다.
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
        disabled={busy || inputLoading || (!files.length && !documents.length) || files.length > 100 || (mode === "document_processing" && !selectedRelease)}
      >
        {busy ? "처리 요청 중…" : "문서 처리 실행"}
      </button>
    </form>
  );
}
