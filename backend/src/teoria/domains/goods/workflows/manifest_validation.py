"""Validate goods workflow input before submitting a Prefect run."""

from fastapi import HTTPException
from pydantic import ValidationError


async def validate_manifest(
    pipeline_id, manifest, principal, application_standards=None
):
    from teoria.domains.goods.contracts import (
        SpecificationRun,
        StandardWorkflow,
    )

    try:
        if pipeline_id == "specification-standard-workflow":
            request = StandardWorkflow.model_validate(manifest)
            extraction = request.extraction
        else:
            if (
                pipeline_id == "specification-standard-management"
                and "mode" not in manifest
            ):
                from teoria.domains.goods.workflows.management_parameters import (
                    StandardManagementParameters,
                )

                parameters = StandardManagementParameters.model_validate(manifest)
                if (
                    parameters.management.purpose == "dictionary_management"
                    and parameters.management.auto_apply
                    and "ontology_owner" not in principal.roles
                ):
                    raise HTTPException(
                        403,
                        detail={"code": "automatic_standard_approval_role_required"},
                    )
                return parameters.model_dump(mode="json", exclude_none=True)
            request = SpecificationRun.model_validate(manifest)
            extraction = request
            expected = (
                "standard_management"
                if pipeline_id == "specification-standard-management"
                else "document_processing"
            )
            if request.mode != expected:
                raise ValueError("manifest mode does not match pipeline")
        if extraction.parser_python is not None:
            raise ValueError("parser executable is configured by the worker")
        if (
            extraction.auto_approve_application_standard
            and "ontology_owner" not in principal.roles
        ):
            raise HTTPException(
                403, detail={"code": "automatic_standard_approval_role_required"}
            )
        import os

        if configured_root := os.getenv("TEORIA_SPECIFICATION_ARTIFACT_ROOT"):
            extraction.artifact_root = configured_root
        validated = request.model_dump(mode="json", exclude_none=True)
        if extraction.application_release_id:
            if application_standards is None:
                raise ValueError("application standards unavailable")
            await application_standards.validate_execution(validated)
        return validated
    except (ValidationError, ValueError, KeyError):
        raise HTTPException(
            422,
            detail={
                "code": "invalid_workflow_manifest",
                "message": "규격서 실행 입력의 형식·필수값·mode를 확인하세요. parser_python은 Worker 설정을 사용합니다.",
            },
        ) from None
