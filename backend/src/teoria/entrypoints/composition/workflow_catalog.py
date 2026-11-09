"""Published operator workflows; archived deployments are never discovered implicitly."""

PIPELINES = {
    "openmetadata-postgres-metadata-sync": ("메타데이터 동기화", "메타데이터", "none"),
    "moleg-law-daily": ("법령 정기 수집", "법령", "none"),
    "moleg-law-weekly-reconciliation": ("법령 전체 이력 재확인", "법령", "none"),
    "specification-standard-management": (
        "규격서 추출 표준 작성",
        "규격서",
        "manifest",
    ),
    "specification-document-processing": ("규격서 표준 적용", "규격서", "manifest"),
    "specification-standard-workflow": ("규격서 표준관리", "규격서", "manifest"),
    "demo-customer-churn-pipeline": ("고객 이탈 모델 학습·배포", "모델", "model"),
}
INTERNAL_PIPELINES = {
    "demo-seed-customers": ("합성 고객 데이터 준비", "모델", "none"),
    "demo-train-customer-churn": ("고객 이탈 모델 학습·평가", "모델", "none"),
    "demo-deploy-customer-churn": ("고정 모델 버전 서빙 배포·복구", "모델", "version"),
}


def workflow_catalog(
    mlops_enabled: bool,
    include_internal: bool = False,
    *,
    semantic_enabled: bool = True,
    formatid_enabled: bool = True,
    legal_enabled: bool = True,
):
    items = {**PIPELINES, **(INTERNAL_PIPELINES if include_internal else {})}
    return {
        key: value
        for key, value in items.items()
        if {
            "모델": mlops_enabled,
            "메타데이터": semantic_enabled,
            "규격서": formatid_enabled,
            "법령": legal_enabled,
        }.get(value[1], False)
    }
