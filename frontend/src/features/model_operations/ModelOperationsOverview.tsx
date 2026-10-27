import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowRight } from "lucide-react";
import {
  modelOperationsApi,
  type ModelCatalog,
} from "../../api/model_operations";
import { useModelOperationsAvailability } from "./ModelOperationsAvailability";

export function ModelOperationsOverview({
  showDisabled = false,
}: {
  showDisabled?: boolean;
}) {
  const availability = useModelOperationsAvailability();
  const [catalog, setCatalog] = useState<ModelCatalog | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let active = true;
    setCatalog(null);
    setError(null);
    if (availability.enabled)
      modelOperationsApi
        .models()
        .then((value) => {
          if (active) setCatalog(value);
        })
        .catch((reason) => {
          if (active) setError((reason as Error).message);
        });
    return () => {
      active = false;
    };
  }, [availability.enabled]);
  if (!availability.enabled && !showDisabled) return null;
  return (
    <section
      className="workspace-card model-operations-overview"
      aria-label="모델 운영 현황"
    >
      <header>
        <div>
          <h3>모델 운영</h3>
          <p>등록 모델과 현재 추론 서비스의 상태를 확인합니다.</p>
        </div>
        <span>
          {availability.checking
            ? "확인 중"
            : availability.error
              ? "연결 확인 필요"
              : availability.enabled
                ? "기능 활성화"
                : "미설정"}
        </span>
      </header>
      {availability.enabled ? (
        <>
          {error ? (
            <p role="alert">
              모델 운영 상태를 불러오지 못했습니다. 다른 작업은 계속 사용할 수
              있습니다.
            </p>
          ) : (
            <dl>
              <div>
                <dt>최근 등록 모델</dt>
                <dd>
                  {catalog?.items[0]
                    ? `v${catalog.items[0].version}`
                    : catalog
                      ? "미등록"
                      : "확인 중"}
                </dd>
              </div>
              <div>
                <dt>추론 서비스</dt>
                <dd>
                  {catalog?.serving.status === "ok"
                    ? `정상 · v${catalog.serving.model_version}`
                    : catalog
                      ? "상태 확인 필요"
                      : "확인 중"}
                </dd>
              </div>
            </dl>
          )}
          <div className="model-overview-links">
            <Link to="/admin/models">
              모델 레지스트리 <ArrowRight size={13} />
            </Link>
            <Link to="/admin/serving">
              추론 서비스 <ArrowRight size={13} />
            </Link>
            <Link to="/admin/workflows">
              파이프라인 <ArrowRight size={13} />
            </Link>
          </div>
        </>
      ) : (
        <>
          <p>
            {availability.error
              ? "선택 기능의 활성화 상태를 확인하지 못했습니다."
              : "모델 운영 기능은 설정된 환경에서 표시됩니다."}
          </p>
          {availability.error && (
            <button onClick={availability.refresh}>다시 확인</button>
          )}
        </>
      )}
    </section>
  );
}
