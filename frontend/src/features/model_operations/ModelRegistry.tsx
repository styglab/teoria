import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ExternalLink, RefreshCw } from "lucide-react";
import {
  modelOperationsApi,
  type ModelCatalog,
  type ModelVersion,
} from "../../api/model_operations";
import { SelectionCatalog } from "../../components/workspace/SelectionCatalog";
import {
  PageHeader,
  PageState,
  FilterTabs,
} from "../../components/workspace/WorkspaceLayout";
import { dateLabel, metricLabel } from "./presentation";

function experimentUrl(item: ModelVersion) {
  return item.experiment_id
    ? `/mlflow/#/experiments/${encodeURIComponent(item.experiment_id)}/runs/${encodeURIComponent(item.run_id)}`
    : `/mlflow/#/models/${encodeURIComponent(item.name)}/versions/${encodeURIComponent(item.version)}`;
}
export function ModelRegistry() {
  const [params, setParams] = useSearchParams();
  const model = params.get("model") || "";
  const token = params.get("token") || "";
  const versionToken = params.get("versions") || "";
  const query = params.get("q") || "";
  const tab = params.get("tab") || "overview";
  const [catalog, setCatalog] = useState<ModelCatalog | null>(null);
  const [error, setError] = useState("");
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
  useEffect(() => {
    let active = true;
    setError("");
    const timer = setTimeout(() => {
      modelOperationsApi
        .models({ model, token, versionToken, q: query })
        .then((value) => {
          if (active) setCatalog(value);
        })
        .catch((reason) => {
          if (active) setError(reason.message);
        });
    }, 200);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [model, token, versionToken, query, refresh]);
  const selected =
    catalog?.items.find((v) => v.version === params.get("version")) ||
    catalog?.items[0];
  const details = catalog?.registered_models.find(
    (m) => m.name === catalog.model_name,
  );
  return (
    <SelectionCatalog
      title="모델 레지스트리"
      search={query}
      onSearch={(value) => update({ q: value, token: "" })}
      selected={catalog?.model_name}
      onSelect={(id) => {
        setCatalog(null);
        update({ model: id, versions: "", version: "", tab: "" });
      }}
      items={(catalog?.registered_models || []).map((item) => ({
        id: item.name,
        title: item.name,
        subtitle:
          item.latest_versions.map((v) => `v${v.version}`).join(" · ") ||
          "버전 없음",
        status:
          catalog?.serving.status === "ok" &&
          catalog.serving.model_name === item.name ? (
            <span className="selection-status COMPLETED">서비스 중</span>
          ) : undefined,
      }))}
      footer={
        <>
          <span>페이지당 최대 25개</span>
          <div>
            <button
              disabled={!token}
              onClick={() =>
                update({ token: "", model: "", versions: "", version: "" })
              }
            >
              처음
            </button>
            <button
              disabled={!catalog?.next_page_token}
              onClick={() =>
                update({
                  token: catalog!.next_page_token!,
                  model: "",
                  versions: "",
                  version: "",
                })
              }
            >
              다음 목록
            </button>
          </div>
        </>
      }
    >
      <PageHeader
        title="모델 레지스트리"
        description="모델을 선택해 버전과 학습 이력을 확인합니다."
        actions={
          <>
            <a
              className="operations-link"
              href="/mlflow/#/models"
              target="_blank"
              rel="noreferrer"
            >
              MLflow 열기 <ExternalLink size={13} />
            </a>
            <button
              className="page-icon-button"
              aria-label="모델 목록 새로고침"
              onClick={() => setRefresh((v) => v + 1)}
            >
              <RefreshCw size={16} />
            </button>
          </>
        }
      />
      {error && (
        <p role="alert" className="workspace-error">
          {error}
        </p>
      )}
      {!catalog ? (
        <PageState
          loading={!error}
          title={
            error ? "모델을 불러오지 못했습니다" : "모델을 불러오고 있습니다…"
          }
        />
      ) : !catalog.registered_models.length && !model ? (
        <PageState
          title="등록된 모델이 없습니다"
          description="검색 조건을 확인하거나 학습 파이프라인에서 모델을 등록하세요."
        />
      ) : (
        <>
          <div className="operations-detail-heading">
            <div>
              <span>등록 모델</span>
              <h3>{catalog.model_name}</h3>
              <p>{details?.description || "등록된 설명이 없습니다."}</p>
            </div>
            <a
              className="operations-link"
              href={`/mlflow/#/models/${encodeURIComponent(catalog.model_name)}`}
              target="_blank"
              rel="noreferrer"
            >
              MLflow 모델 상세 <ExternalLink size={12} />
            </a>
          </div>
          <FilterTabs
            label="모델 상세"
            value={tab}
            onChange={(value) => update({ tab: value })}
            items={[
              { id: "overview", label: "개요" },
              { id: "versions", label: "버전" },
              { id: "history", label: "학습 이력" },
            ]}
          />
          {tab === "overview" && (
            <section className="operations-section">
              <h4>모델 정보</h4>
              <dl className="operations-facts">
                <div>
                  <dt>최근 등록 버전</dt>
                  <dd>
                    {catalog.items[0]
                      ? `v${catalog.items[0].version}${versionToken ? " (현재 조회 페이지)" : ""}`
                      : "등록된 버전 없음"}
                  </dd>
                </div>
                <div>
                  <dt>수정 시각</dt>
                  <dd>{dateLabel(details?.last_updated_timestamp)}</dd>
                </div>
                <div>
                  <dt>별칭</dt>
                  <dd>
                    {details?.aliases
                      .map((a) => `${a.alias} → v${a.version}`)
                      .join(", ") || "지정된 별칭 없음"}
                  </dd>
                </div>
                <div>
                  <dt>연결된 추론 서비스</dt>
                  <dd>
                    {catalog.serving.model_name === catalog.model_name ? (
                      <Link className="operations-link" to="/admin/serving">
                        {catalog.serving.status === "ok"
                          ? `v${catalog.serving.model_version} 서비스 중`
                          : "서비스 상태 확인"}
                      </Link>
                    ) : (
                      "연결된 서비스 없음"
                    )}
                  </dd>
                </div>
                <div>
                  <dt>태그</dt>
                  <dd>
                    {details?.tags
                      ?.map((tag) => `${tag.key}: ${tag.value}`)
                      .join(", ") || "등록된 태그 없음"}
                  </dd>
                </div>
              </dl>
              <p className="operations-note">
                최근 등록 버전과 실제 서비스 중인 버전은 별도로 관리합니다.
              </p>
            </section>
          )}
          {tab === "versions" && (
            <section className="operations-section">
              <h4>모델 버전</h4>
              <div className="page-table-wrap">
                <table className="page-table">
                  <thead>
                    <tr>
                      <th>버전</th>
                      <th>상태</th>
                      <th>등록 시각</th>
                      <th>서빙</th>
                    </tr>
                  </thead>
                  <tbody>
                    {catalog.items.map((item) => (
                      <tr
                        key={item.version}
                        className={
                          selected?.version === item.version ? "selected" : ""
                        }
                      >
                        <td>
                          <button
                            className="operations-link"
                            onClick={() => update({ version: item.version })}
                          >
                            v{item.version}
                          </button>
                        </td>
                        <td>{item.status}</td>
                        <td>{dateLabel(item.creation_timestamp)}</td>
                        <td>
                          {catalog.serving.model_name === item.name &&
                          catalog.serving.status === "ok" &&
                          catalog.serving.model_version === Number(item.version)
                            ? "서비스 중"
                            : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {selected && (
                <div className="operations-section operations-version">
                  <h4>v{selected.version} · 평가 지표</h4>
                  <dl className="operations-facts">
                    {Object.entries(selected.metrics || {}).map(
                      ([key, value]) => (
                        <div key={key}>
                          <dt>{key}</dt>
                          <dd>{metricLabel(value)}</dd>
                        </div>
                      ),
                    )}
                  </dl>
                  {!Object.keys(selected.metrics || {}).length && (
                    <p className="operations-note">
                      기록된 평가 지표가 없습니다.
                    </p>
                  )}
                  {selected.metrics_unavailable && (
                    <p role="alert">평가 정보를 불러오지 못했습니다.</p>
                  )}
                  <h4>학습 데이터 참조</h4>
                  <dl className="operations-facts">
                    {Object.entries(selected.parameters || {}).map(
                      ([key, value]) => (
                        <div key={key}>
                          <dt>{key}</dt>
                          <dd>
                            <code>{value}</code>
                          </dd>
                        </div>
                      ),
                    )}
                  </dl>
                  <a
                    className="operations-link"
                    href={experimentUrl(selected)}
                    target="_blank"
                    rel="noreferrer"
                  >
                    MLflow 학습 Run <ExternalLink size={12} />
                  </a>
                </div>
              )}
              {!catalog.items.length && (
                <PageState title="등록된 버전이 없습니다" />
              )}
            </section>
          )}
          {tab === "history" && (
            <section className="operations-section">
              <h4>등록 버전의 학습 이력</h4>
              <p className="operations-note">
                모델 버전으로 등록된 실험입니다. 전체 실험과 비교는 MLflow에서
                확인하세요.
              </p>
              <div className="page-table-wrap">
                <table className="page-table">
                  <thead>
                    <tr>
                      <th>버전</th>
                      <th>학습 Run</th>
                      <th>파이프라인</th>
                      <th>등록 시각</th>
                    </tr>
                  </thead>
                  <tbody>
                    {catalog.items.map((item) => (
                      <tr key={item.version}>
                        <td>v{item.version}</td>
                        <td>
                          {item.run_id ? (
                            <a
                              className="operations-link"
                              href={experimentUrl(item)}
                              target="_blank"
                              rel="noreferrer"
                            >
                              {item.run_id.slice(0, 12)}…{" "}
                              <ExternalLink size={12} />
                            </a>
                          ) : (
                            "기록 없음"
                          )}
                        </td>
                        <td>
                          {item.pipeline_run_id || item.prefect_run_id ? (
                            <a
                              className="operations-link"
                              href={`/prefect/runs/flow-run/${encodeURIComponent(item.pipeline_run_id || item.prefect_run_id!)}`}
                              target="_blank"
                              rel="noreferrer"
                            >
                              Prefect 실행 <ExternalLink size={12} />
                            </a>
                          ) : (
                            "연결 기록 없음"
                          )}
                        </td>
                        <td>{dateLabel(item.creation_timestamp)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}
          {tab !== "overview" && (
            <div className="operations-pagination">
              <button
                disabled={!versionToken}
                onClick={() => update({ versions: "", version: "" })}
              >
                최신 버전
              </button>
              <button
                disabled={!catalog.next_version_token}
                onClick={() =>
                  update({ versions: catalog.next_version_token!, version: "" })
                }
              >
                다음 버전 목록
              </button>
              <span>페이지당 최대 25개</span>
            </div>
          )}
        </>
      )}
    </SelectionCatalog>
  );
}
