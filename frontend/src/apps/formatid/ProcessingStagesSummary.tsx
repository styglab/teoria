import type { ProcessingStages } from "./api";

const labels = {
  completed: "완료",
  partial: "부분 완료",
  failed: "실패",
  excluded: "대상 제외",
  not_requested: "미수행",
  not_applicable: "대상 없음",
  review_required: "검토 필요",
  resolved: "연결 확인",
};
const bases = {
  pinned_profile: "고정 프로파일",
  fixed_extraction_rules: "고정 추출 규칙",
  extraction_draft: "추출 규칙 초안",
};

export function ProcessingStagesSummary({
  stages,
}: {
  stages?: ProcessingStages;
}) {
  if (!stages || stages.schema_version !== 1) {
    return (
      <section aria-label="단계별 처리 상태" className="context-banner">
        <p>
          단계별 상태가 기록되지 않은 실행입니다. 종합 상태로 의미 승인 여부를
          판단하지 않습니다.
        </p>
      </section>
    );
  }
  return (
    <section aria-label="단계별 처리 상태" className="context-banner">
      <dl className="specification-summary">
        <div>
          <dt>원문 추출</dt>
          <dd>{labels[stages.extraction.status]}</dd>
        </div>
        <div>
          <dt>원문 표현 등록</dt>
          <dd>{labels[stages.expression_registration.status]}</dd>
        </div>
        <div>
          <dt>의미 연결</dt>
          <dd>{labels[stages.meaning.status]}</dd>
        </div>
        <div>
          <dt>기준 적용</dt>
          <dd>
            {labels[stages.application.status]} ·{" "}
            {bases[stages.application.basis]}
          </dd>
        </div>
      </dl>
      <p>
        원문 표현 등록과 추출 규칙 적용은 Ontology 의미 승인·게시와 별개입니다.
      </p>
      {stages.meaning.counts.comparison_observations > 0 && (
        <p>
          Ontology 비교 {stages.meaning.counts.comparison_observations}건은
          제안이며 자동 적용되지 않았습니다.
        </p>
      )}
    </section>
  );
}
