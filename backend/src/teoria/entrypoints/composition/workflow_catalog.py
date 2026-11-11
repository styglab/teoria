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
    "model-train": ("모델 이미지 학습", "모델", "training"),
    "model-deploy": ("모델 이미지 서빙 배포", "모델", "serving"),
    "model-stop": ("모델 이미지 서빙 중지", "모델", "stop-serving"),
}


def workflow_catalog(
    mlops_enabled: bool,
    *,
    semantic_enabled: bool = True,
    formatid_enabled: bool = True,
    legal_enabled: bool = True,
):
    return {
        key: value
        for key, value in PIPELINES.items()
        if {
            "모델": mlops_enabled,
            "메타데이터": semantic_enabled,
            "규격서": formatid_enabled,
            "법령": legal_enabled,
        }.get(value[1], False)
    }
