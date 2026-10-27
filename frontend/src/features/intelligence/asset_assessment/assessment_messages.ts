export const assessmentErrors: Record<string, string> = {
  asset_assessment_not_configured: "진단 모델과 Worker 설정이 필요합니다.",
  stale_evidence:
    "진단 중 원천 자산이 변경됐습니다. 최신 자산으로 다시 진단하세요.",
  model_unavailable: "진단 모델에 연결하지 못했습니다.",
  model_output_truncated: "모델 응답이 길이 제한으로 잘렸습니다. 컬럼 수를 줄여 다시 진단하세요.",
  model_output_invalid: "모델 결과가 제안 형식에 맞지 않습니다.",
  select_up_to_30_columns:
    "첫 버전은 한 번에 30개 컬럼까지 진단합니다. 대상 컬럼을 선택하세요.",
};
