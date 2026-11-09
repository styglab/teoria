import { useState } from "react";
import type { InferenceService } from "../../platform/mlops/api";
import { customerChurnApi } from "./api";

const inputLabels: Record<string, string> = {
  tenure_months: "이용 기간(개월)",
  monthly_spend: "월 이용 금액(합성 단위)",
  login_days_30d: "최근 30일 로그인 일수",
  support_tickets_30d: "최근 30일 문의 건수",
};
const initialValues: Record<string, number> = {
  tenure_months: 12,
  monthly_spend: 50,
  login_days_30d: 8,
  support_tickets_30d: 3,
};
export function PredictionForm({
  service: selected,
}: {
  service: InferenceService;
}) {
  const [inputs, setInputs] = useState<Record<string, number>>(initialValues);
  const [prediction, setPrediction] = useState<Awaited<
    ReturnType<typeof customerChurnApi.predict>
  > | null>(null);
  const [predictError, setPredictError] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <>
      <form
        className="operations-test-form"
        onSubmit={async (event) => {
          event.preventDefault();
          if (busy) return;
          setBusy(true);
          setPredictError("");
          setPrediction(null);
          try {
            setPrediction(await customerChurnApi.predict(inputs));
          } catch (reason) {
            setPredictError((reason as Error).message);
          } finally {
            setBusy(false);
          }
        }}
      >
        <div className="operations-inputs">
          {Object.entries(selected.request_schema.properties).map(
            ([key, field]) => (
              <label key={key}>
                {inputLabels[key] || field.title || key}
                <input
                  required={selected.request_schema.required?.includes(key)}
                  type="number"
                  min={field.minimum}
                  max={field.maximum}
                  step={field.type === "integer" ? 1 : "any"}
                  value={inputs[key] ?? field.minimum ?? 0}
                  onChange={(event) => {
                    setInputs((previous) => ({
                      ...previous,
                      [key]: Number(event.target.value),
                    }));
                    setPrediction(null);
                  }}
                />
              </label>
            ),
          )}
        </div>
        <button
          className="page-primary-link"
          type="submit"
          disabled={busy || selected.status !== "ok"}
        >
          {busy ? "추론 중…" : "추론 실행"}
        </button>
      </form>
      {predictError && (
        <p role="alert" className="workspace-error">
          {predictError}
        </p>
      )}
      {prediction && (
        <section className="operations-response" aria-label="추론 응답">
          <h4>응답</h4>
          <p role="status">
            모델 v{prediction.model_version} · 합성 고객 이탈 확률{" "}
            {(prediction.churn_probability * 100).toFixed(1)}%
          </p>
          <pre>{JSON.stringify(prediction, null, 2)}</pre>
        </section>
      )}
    </>
  );
}

export function customerChurnTest(service: InferenceService) {
  return service.id === "customer-churn" ? (
    <PredictionForm
      key={`${service.id}:${service.model_version}`}
      service={service}
    />
  ) : (
    <p>이 서비스의 테스트 폼이 연결되지 않았습니다.</p>
  );
}
