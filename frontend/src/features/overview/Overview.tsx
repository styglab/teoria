import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { RefreshCw, ArrowRight } from "lucide-react";
import { metadataApi, type MetadataStatus } from "../../api/metadata";
import { workflowsApi, type ModelRun } from "../../api/workflows";
import { loadReviewWork } from "../intelligence/review_work";
import { ModelOperationsOverview } from "../model_operations/ModelOperationsOverview";
import { useModelOperationsAvailability } from "../model_operations/ModelOperationsAvailability";
import {
  PageHeader,
  PageState,
} from "../../components/workspace/WorkspaceLayout";
import { useAdminAccess } from "../access/AdminAccess";
import { stateLabels, dateLabel } from "../model_operations/presentation";

import { useDeploymentModules } from "../access/DeploymentAvailability";

type HomeRun = ModelRun & { pipeline_label?: string };

export function Overview() {
  const modules = useDeploymentModules();
  const { principal, requestLogin } = useAdminAccess();
  const [refresh, setRefresh] = useState(0);
  const [status, setStatus] = useState<MetadataStatus | null>(null);
  const [total, setTotal] = useState<number | null>(null);
  const [reviews, setReviews] = useState<Awaited<
    ReturnType<typeof loadReviewWork>
  > | null>(null);
  const [recent, setRecent] = useState<HomeRun[] | null>(null);
  const [failed, setFailed] = useState<HomeRun[] | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  useEffect(() => {
    let active = true;
    setErrors({});
    const fail = (key: string, message: string) => {
      if (active) setErrors((previous) => ({ ...previous, [key]: message }));
    };
    if (modules.semantic) {
      metadataApi
        .metadataStatus()
        .then((value) => {
          if (active) setStatus(value);
        })
        .catch(() =>
          fail("metadata", "메타데이터 연결을 확인하지 못했습니다."),
        );
      metadataApi
        .metadataTables({ limit: 1 })
        .then((value) => {
          if (active) setTotal(value.total);
        })
        .catch(() => fail("assets", "자산 수를 조회하지 못했습니다."));
    }
    setReviews(null);
    setRecent(null);
    setFailed(null);
    if (principal) {
      if (modules.semantic)
        loadReviewWork().then((value) => {
          if (active) setReviews(value);
        });
      workflowsApi
        .pipelines({ size: 25 })
        .then((value) => {
          if (active)
            setRecent(
              value.runs.map((run) => ({
                ...run,
                pipeline_label: value.items.find(
                  (item) => item.deployment_id === run.deployment_id,
                )?.name,
              })),
            );
        })
        .catch(() => fail("recent", "최근 실행을 조회하지 못했습니다."));
      workflowsApi
        .pipelines({ state: "FAILED", size: 25 })
        .then((value) => {
          if (active)
            setFailed(
              value.runs.map((run) => ({
                ...run,
                pipeline_label: value.items.find(
                  (item) => item.deployment_id === run.deployment_id,
                )?.name,
              })),
            );
        })
        .catch(() => fail("failed", "실패한 실행을 조회하지 못했습니다."));
    }
    return () => {
      active = false;
    };
  }, [principal?.actor, refresh, modules.semantic]);
  const execution = (
    title: string,
    items: HomeRun[] | null,
    error?: string,
  ) => (
    <section className="home-work-section">
      <header>
        <h3>{title}</h3>
        <Link
          to={`/admin/workflows${title === "실패한 실행" ? "?state=FAILED&tab=history" : ""}`}
        >
          전체 실행 <ArrowRight size={12} />
        </Link>
      </header>
      {error ? (
        <p role="alert">
          {error}{" "}
          <button onClick={() => setRefresh((v) => v + 1)}>다시 조회</button>
        </p>
      ) : items === null ? (
        <PageState loading title="실행을 확인하고 있습니다…" />
      ) : !items.length ? (
        <p className="home-empty">조회된 실행이 없습니다.</p>
      ) : (
        <ul>
          {items.slice(0, 5).map((run) => (
            <li key={run.id}>
              <Link to={`/admin/workflows?run=${run.id}&tab=history`}>
                <strong>{run.pipeline_label || run.name}</strong>
                <span>
                  {stateLabels[run.state_type] || run.state_name} ·{" "}
                  {dateLabel(run.created)}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
  return (
    <div className="workspace-page home-page">
      <PageHeader
        title="홈"
        description="검토할 변경과 실행 상태를 확인하고 작업을 이어갑니다."
        actions={
          <button
            className="page-icon-button"
            aria-label="홈 새로고침"
            onClick={() => setRefresh((v) => v + 1)}
          >
            <RefreshCw size={16} />
          </button>
        }
      />
      <div className="home-shortcuts">
        {modules.semantic && (
          <Link to="/admin/data-catalog">
            데이터 자산 찾기 <ArrowRight size={13} />
          </Link>
        )}
        {modules.formatid && (
          <Link to="/admin/specifications">
            FormatID 시작 <ArrowRight size={13} />
          </Link>
        )}
        {modules.semantic && (
          <Link to="/admin/semantic-model/ontology">
            의미 모델 탐색 <ArrowRight size={13} />
          </Link>
        )}
      </div>
      {!principal ? (
        <section className="home-work-section">
          <h3>작업 현황</h3>
          <p>관리자로 연결하면 검토 대기와 실행 이력을 확인할 수 있습니다.</p>
          <button className="page-primary-link" onClick={requestLogin}>
            관리자 연결
          </button>
        </section>
      ) : (
        <>
          {modules.semantic && (
            <section className="home-work-section">
              <header>
                <h3>검토 대기</h3>
                <Link to="/admin/changes/review">
                  검토함 열기 <ArrowRight size={12} />
                </Link>
              </header>
              {!reviews ? (
                <PageState loading title="검토할 작업을 확인하고 있습니다…" />
              ) : (
                <>
                  {!!reviews.errors.length && (
                    <p role="alert">
                      {reviews.errors.join(", ")} 조회 실패{" "}
                      <button onClick={() => setRefresh((v) => v + 1)}>
                        다시 조회
                      </button>
                    </p>
                  )}
                  {!reviews.items.length ? (
                    <p className="home-empty">
                      조회 범위에 검토할 작업이 없습니다.
                    </p>
                  ) : (
                    <ul>
                      {reviews.items.slice(0, 5).map((item) => (
                        <li key={`${item.kind}:${item.id}`}>
                          <Link to={item.href}>
                            <strong>{item.title}</strong>
                            <span>{item.state}</span>
                          </Link>
                        </li>
                      ))}
                    </ul>
                  )}
                  <p className="operations-note">
                    조회된 검토 범위 {reviews.items.length}개
                    {reviews.limited ? " · 추가 항목은 전체 목록에서 확인" : ""}
                  </p>
                </>
              )}
            </section>
          )}
          <div className="home-executions">
            {execution("실패한 실행", failed, errors.failed)}
            {execution("최근 실행", recent, errors.recent)}
          </div>
        </>
      )}
      {modules.semantic && (
        <footer className="home-service-status">
          <Link to="/admin/data-catalog">
            데이터 자산{" "}
            <strong>
              {total === null ? "—" : total.toLocaleString("ko-KR")}
            </strong>
            개
          </Link>
          <Link to="/admin/operations">
            메타데이터 연결 ·{" "}
            {status?.available
              ? "정상"
              : status
                ? status.enabled
                  ? "연결 확인 필요"
                  : "미설정"
                : "확인 중"}
          </Link>
          {(errors.metadata || errors.assets) && (
            <span role="alert">{errors.metadata || errors.assets}</span>
          )}
        </footer>
      )}
    </div>
  );
}
export function OperationsSettings() {
  const { principal, requestLogin } = useAdminAccess();
  const modelOperations = useModelOperationsAvailability();
  const [status, setStatus] = useState<MetadataStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let active = true;
    metadataApi
      .metadataStatus()
      .then((value) => {
        if (active) setStatus(value);
      })
      .catch((reason) => {
        if (active) setError((reason as Error).message);
      });
    return () => {
      active = false;
    };
  }, []);
  return (
    <div className="workspace-page">
      <PageHeader
        title="연결 및 설정"
        description="외부 서비스 연결, 실행 도구와 현재 접근 권한을 확인합니다."
      />
      <div className="overview-columns">
        <section className="workspace-card">
          <h3>메타데이터 연결</h3>
          {error ? (
            <p role="alert">{error}</p>
          ) : (
            <>
              <p>
                OpenMetadata ·{" "}
                {status
                  ? !status.enabled
                    ? "현재 구성에서 사용하지 않음"
                    : status.available
                      ? "정상 연결"
                      : "연결 확인 필요"
                  : "확인 중"}
              </p>
              <p>데이터 서비스: {status?.database_service || "—"}</p>
              {status?.reason && <p>{status.reason}</p>}
            </>
          )}
          <p>자산·설명·소유자·태그·용어의 원천은 OpenMetadata입니다.</p>
          <a
            href={`${window.location.protocol}//${window.location.hostname}:8585`}
            target="_blank"
            rel="noreferrer"
          >
            OpenMetadata 열기 ↗
          </a>
        </section>
        <section className="workspace-card">
          <h3>워크플로</h3>
          <p>데이터 동기화·학습·배포의 실행과 예약은 Prefect가 관리합니다.</p>
          <Link to="/admin/workflows">파이프라인 조회·실행 →</Link>
          <p>
            전체 등록 작업과 상세 운영 정보는 Prefect에서 확인할 수 있습니다.
          </p>
          <a href="/prefect/" target="_blank" rel="noreferrer">
            Prefect 열기 ↗
          </a>
        </section>
        <ModelOperationsOverview showDisabled />
        <section className="workspace-card">
          <h3>현재 접근</h3>
          <p>
            {principal
              ? `관리자: ${principal.actor}`
              : "조회 모드 · 메타데이터 조회 가능"}
          </p>
          {principal ? (
            <p>역할: {principal.roles.join(", ")}</p>
          ) : (
            <button onClick={requestLogin}>관리자 연결</button>
          )}
        </section>
      </div>
    </div>
  );
}
