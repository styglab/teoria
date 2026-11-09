import { RefreshCw } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useServerQuery } from "../../api/server_queries";
import { CatalogPagination } from "../../components/workspace/CatalogPagination";
import { SelectionCatalog } from "../../components/workspace/SelectionCatalog";
import {
  FilterTabs,
  PageHeader,
  PageState,
} from "../../components/workspace/WorkspaceLayout";
import { modelOperationsApi, type InferenceService } from "./api";
import { dateLabel, runDurationLabel, stateLabels } from "./presentation";

export type InferenceTest = (service: InferenceService) => ReactNode;

export function InferenceServices({
  renderTest,
}: {
  renderTest?: InferenceTest;
}) {
  const [params, setParams] = useSearchParams();
  const selectedId = params.get("service") || "";
  const tab = params.get("tab") || "overview";
  const page = Math.max(0, Number(params.get("page")) || 0);
  const size = params.get("size") === "50" ? 50 : 25;
  const [query, setQuery] = useState("");

  const [refresh, setRefresh] = useState(0);

  const update = (values: Record<string, string>) =>
    setParams(
      (previous) => {
        const next = new URLSearchParams(previous);
        Object.entries(values).forEach(([k, v]) =>
          v ? next.set(k, v) : next.delete(k),
        );
        return next;
      },
      { replace: true },
    );
  const serviceResult = useServerQuery(
    ["mlops", "services"],
    (signal) => modelOperationsApi.services(signal),
    { refresh, interval: 10000 },
  );
  const items = serviceResult.data?.items ?? null;
  const error = serviceResult.error;
  const selected =
    items?.find((item) => item.id === selectedId) ||
    (!selectedId ? items?.[0] : undefined);
  const historyResult = useServerQuery(
    ["mlops", "pipelines", selected?.deployment_pipeline_id, page, size],
    (signal) =>
      modelOperationsApi.pipelines(
        { pipeline: selected!.deployment_pipeline_id, page, size },
        signal,
      ),
    { enabled: tab === "history" && !!selected, refresh },
  );
  const history = historyResult.data;
  const historyError = historyResult.error;
  useEffect(() => {
    if (history && page > 0 && page * size >= (history.total || 0))
      update({ page: "" });
  }, [history, page, size]);
  return (
    <SelectionCatalog
      title="추론 서비스"
      search={query}
      onSearch={setQuery}
      selected={selected?.id}
      onSelect={(id) => update({ service: id, tab: "", page: "" })}
      items={(items || [])
        .filter((item) =>
          `${item.name} ${item.endpoint}`
            .toLocaleLowerCase()
            .includes(query.toLocaleLowerCase()),
        )
        .map((item) => ({
          id: item.id,
          title: item.name,
          subtitle: item.endpoint,
          status: (
            <span
              className={`selection-status ${item.status === "ok" ? "COMPLETED" : "FAILED"}`}
            >
              {item.status === "ok" ? "정상" : "상태 확인 필요"}
            </span>
          ),
        }))}
      footer={<span>{items?.length || 0}개 엔드포인트 · 10초마다 갱신</span>}
    >
      <PageHeader
        title="추론 서비스"
        description="엔드포인트를 선택해 배포 상태와 요청·응답을 확인합니다."
        actions={
          <button
            className="page-icon-button"
            aria-label="추론 서비스 새로고침"
            onClick={() => setRefresh((v) => v + 1)}
          >
            <RefreshCw size={16} />
          </button>
        }
      />
      {error && (
        <p role="alert" className="workspace-error">
          {error}
        </p>
      )}
      {!items ? (
        <PageState
          loading={!error}
          title={
            error
              ? "서비스를 불러오지 못했습니다"
              : "서비스를 불러오고 있습니다…"
          }
        />
      ) : !selected ? (
        <PageState title="연결된 추론 서비스가 없습니다" />
      ) : (
        <>
          <div className="operations-detail-heading">
            <div>
              <span>{selected.environment}</span>
              <h3>{selected.name}</h3>
              <p>{selected.description}</p>
            </div>
            <span
              className={`model-state ${selected.status === "ok" ? "COMPLETED" : "FAILED"}`}
            >
              {selected.status === "ok" ? "정상" : "상태 확인 필요"}
            </span>
          </div>
          <FilterTabs
            label="추론 서비스 상세"
            value={tab}
            onChange={(value) => update({ tab: value, page: "" })}
            items={[
              { id: "overview", label: "개요" },
              { id: "test", label: "추론 테스트" },
              { id: "history", label: "배포 이력" },
            ]}
          />
          {tab === "overview" && (
            <section className="operations-section">
              <h4>배포 정보</h4>
              <dl className="operations-facts">
                <div>
                  <dt>엔드포인트</dt>
                  <dd>
                    <code>
                      {selected.method} {selected.endpoint}
                    </code>
                  </dd>
                </div>
                <div>
                  <dt>인증</dt>
                  <dd>추론 전용 Bearer token</dd>
                </div>
                <div>
                  <dt>배포 모델</dt>
                  <dd>
                    <Link
                      className="operations-link"
                      to={`/admin/models?model=${encodeURIComponent(selected.model_name)}`}
                    >
                      {selected.model_name}
                    </Link>
                  </dd>
                </div>
                <div>
                  <dt>실제 서비스 버전</dt>
                  <dd>
                    {selected.model_version
                      ? `v${selected.model_version}`
                      : "배포된 버전 없음"}
                  </dd>
                </div>
              </dl>
              <p className="operations-note">
                서비스 상태와 모델 버전은 현재 추론 서버에서 확인한 값입니다.
              </p>
            </section>
          )}
          {tab === "test" && (
            <section className="operations-section">
              <h4>추론 테스트</h4>
              <p className="operations-note">
                현재 서비스 중인 v{selected.model_version || "—"}에 요청합니다.
              </p>
              {renderTest ? (
                renderTest(selected)
              ) : (
                <p>이 서비스의 테스트 폼이 연결되지 않았습니다.</p>
              )}
            </section>
          )}
          {tab === "history" && (
            <section className="operations-section">
              <h4>배포 이력</h4>
              {historyError ? (
                <p role="alert" className="workspace-error">
                  {historyError}
                </p>
              ) : !history ? (
                <PageState loading title="배포 이력을 불러오고 있습니다…" />
              ) : (
                <>
                  <div className="page-table-wrap">
                    <table className="page-table">
                      <thead>
                        <tr>
                          <th>요청 시각</th>
                          <th>모델 버전</th>
                          <th>결과</th>
                          <th>소요 시간</th>
                          <th>실행 상세</th>
                        </tr>
                      </thead>
                      <tbody>
                        {history.runs.map((run) => (
                          <tr key={run.id}>
                            <td>{dateLabel(run.created)}</td>
                            <td>
                              {run.model_version
                                ? `v${run.model_version}`
                                : "—"}
                            </td>
                            <td>
                              {stateLabels[run.state_type] || run.state_name}
                            </td>
                            <td>{runDurationLabel(run)}</td>
                            <td>
                              <a
                                className="operations-link"
                                href={`/prefect/runs/flow-run/${run.id}`}
                                target="_blank"
                                rel="noreferrer"
                              >
                                Prefect 실행
                              </a>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    {!history.runs.length && (
                      <PageState title="배포 이력이 없습니다" />
                    )}
                  </div>
                  <CatalogPagination
                    page={page}
                    pageSize={size}
                    total={history.total || 0}
                    onPageChange={(value) => update({ page: String(value) })}
                    onPageSizeChange={(value) =>
                      update({ size: String(value), page: "" })
                    }
                  />
                </>
              )}
              <p className="operations-note">
                배포 실패 시 이전 모델을 복원한 실행도 실패 기록으로 유지합니다.
              </p>
            </section>
          )}
        </>
      )}
    </SelectionCatalog>
  );
}
