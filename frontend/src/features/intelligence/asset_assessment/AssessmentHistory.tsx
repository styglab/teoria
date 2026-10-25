import { Link } from "react-router-dom";
import { ChevronDown } from "lucide-react";
import type { AssetAssessment } from "../../../api/asset_assessment";
import { assessmentErrors as errors } from "./assessment_messages";

const labels = {
  queued: "대기 중",
  running: "진단 중",
  completed: "진단 완료",
  partial: "일부 확인 필요",
  failed: "진단 실패",
};
const recommendations: Record<string, string> = {
  review_required: "추가 검토 필요",
  withhold_raw: "원문 개방 보류 권고",
  transform_and_reassess: "가공 후 재검토 권고",
  candidate: "개방 후보 (최종 검토 필요)",
};

export function AssessmentHistory({ items }: { items: AssetAssessment[] }) {
  return (
    <>
      {!!items.length && (
        <div className="assessment-results">
          <h4 className="assessment-results-title">최근 진단</h4>
          {items.map((item) => (
            <article className="assessment-result" key={item.assessment_id}>
              <header>
                <h4>
                  {labels[item.status]} · 제안 {item.suggestion_ids.length}건
                </h4>
                <span className="assessment-status" data-status={item.status}>
                  {labels[item.status]}
                </span>
              </header>
              <p className="assessment-result-meta">
                {new Date(item.created_at).toLocaleString()} · {item.model_name}
                {item.assessment_date &&
                  ` · 평가 기준일 ${item.assessment_date}`}
              </p>
              {item.error_code && (
                <p className="assessment-error" role="alert">
                  {errors[item.error_code] ||
                    `진단을 완료하지 못했습니다 (${item.error_code}). 새 진단을 요청할 수 있습니다.`}
                </p>
              )}
              {!!item.suggestion_ids.length && (
                <div className="assessment-result-links">
                  {item.suggestion_ids.map((id) => (
                    <Link
                      key={id}
                      to={`/admin/changes/review?suggestion=${encodeURIComponent(id)}`}
                    >
                      변경 제안 검토 · {id.slice(0, 8)}
                    </Link>
                  ))}
                </div>
              )}
              {item.findings.map((finding, index) => (
                <details className="assessment-finding" key={index}>
                  <summary>
                    <span>{finding.column_name || "검토 사항"}</span>
                    <ChevronDown size={14} aria-hidden="true" />
                  </summary>
                  <div className="assessment-finding-body">
                    <p>{finding.summary}</p>
                    {finding.information_type && (
                      <p>정보 유형 후보: {finding.information_type}</p>
                    )}
                    {finding.internal_processing && (
                      <p>
                        내부 처리:{" "}
                        {finding.internal_processing === "review_required"
                          ? "처리 근거 검토 필요"
                          : "평가하지 않음"}
                      </p>
                    )}
                    {finding.disclosure_recommendation && (
                      <p>
                        외부 개방:{" "}
                        {recommendations[finding.disclosure_recommendation] ||
                          "추가 검토 필요"}{" "}
                        · AI 검토 초안
                      </p>
                    )}
                    {finding.protection_recommendation && (
                      <p>보호조치 권고: {finding.protection_recommendation}</p>
                    )}
                    {!!finding.tag_candidates?.length && (
                      <p>
                        미검증 태그 후보: {finding.tag_candidates.join(", ")}
                      </p>
                    )}
                    {finding.evidence?.map((evidence, i) => (
                      <p key={i}>
                        <code>{evidence.source_ref}</code>
                        {typeof evidence.provenance?.law_name === "string" &&
                          ` · ${evidence.provenance.law_name} · 시행일 ${String(evidence.provenance.effective_date ?? "")}`}
                      </p>
                    ))}
                  </div>
                </details>
              ))}
            </article>
          ))}
        </div>
      )}
    </>
  );
}
