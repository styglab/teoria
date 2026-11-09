import type { processingApi } from "./api";
const reasons: Record<string, string> = {
  quality_metrics_missing: "품질 지표 없음",
  no_successful_documents: "처리된 문서 없음",
  source_validation_errors: "원문 검증 오류",
  failed_document_ratio: "문서 실패 비율 초과",
  held_attribute_ratio: "속성 보류 비율 초과",
  attribute_count_change_ratio: "동일 원본의 추출량 급변",
};
export function RunQuality({ summary }: { summary: Record<string, unknown> }) {
  const q = summary.quality as Record<string, number> | undefined;
  const approval = summary.automatic_application_standard as
    | {
        quality_gate?: {
          reasons: string[];
          attribute_count_change_ratio: number | null;
        };
      }
    | undefined;
  if (!q) return null;
  return (
    <section aria-label="처리 품질">
      <p>
        원문 검증 오류 {q.validation_errors}건 · 격리 속성{" "}
        {q.quarantined_attributes}건 · 문서 실패{" "}
        {(q.failed_document_ratio * 100).toFixed(1)}%
      </p>
      {!!approval?.quality_gate?.reasons.length && (
        <p>
          자동 승인 보류 사유:{" "}
          {approval.quality_gate.reasons
            .map((r) => reasons[r] || r)
            .join(" · ")}
        </p>
      )}
      {approval?.quality_gate?.attribute_count_change_ratio != null && (
        <p>
          동일 원본의 이전 실행 대비 추출량 변화{" "}
          {(approval.quality_gate.attribute_count_change_ratio * 100).toFixed(
            1,
          )}
          %
        </p>
      )}
    </section>
  );
}
export function VersionQuality({
  versions,
}: {
  versions: NonNullable<
    Awaited<ReturnType<typeof processingApi.operations>>["quality_versions"]
  >;
}) {
  if (!versions.length) return null;
  return (
    <div className="catalog-table-scroll">
      <table aria-label="버전별 처리 품질">
        <thead>
          <tr>
            <th>처리 엔진 버전</th>
            <th>실행</th>
            <th>자동 승인 / 보류</th>
            <th>원문 검증 오류</th>
            <th>속성 적용 / 보류</th>
          </tr>
        </thead>
        <tbody>
          {versions.map((v, i) => (
            <tr key={i}>
              <td title={v.processor_revision || ""}>
                {v.processor_revision?.slice(0, 10) || "이전 버전"}
                <br />
                {v.model_requested || "기본 모델"}
              </td>
              <td>
                {v.runs}
                {v.measured_runs < v.runs && (
                  <small> · 품질 미측정 {v.runs - v.measured_runs}건</small>
                )}
              </td>
              <td>
                {v.approved} / {v.held}
              </td>
              <td>{v.measured_runs ? v.validation_errors : "측정 없음"}</td>
              <td>
                {v.measured_runs
                  ? `${v.applied_attributes} / ${v.held_attributes}`
                  : "측정 없음"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
