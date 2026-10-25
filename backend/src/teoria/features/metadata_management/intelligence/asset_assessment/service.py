from __future__ import annotations

import asyncio


from teoria.features.metadata_management.intelligence.asset_assessment.context_builder import build_context
from teoria.features.metadata_management.intelligence.asset_assessment.law_evidence import collect_law_evidence
from teoria.features.metadata_management.intelligence.asset_assessment.model_client import AssessmentError
from teoria.features.metadata_management.intelligence.asset_assessment.models import (
    AssessmentAnalysis,
    AssessmentJob,
    AssessmentOutput,
)
from teoria.features.metadata_management.intelligence.asset_assessment.prompts import ASSESSMENT_INSTRUCTION
from teoria.features.metadata_management.intelligence.asset_assessment.validation import (
    require_bounded_context,
    validate_output,
    verify_table,
)


class AssetAssessmentService:
    def __init__(self, repository, metadata, bindings, model, law_reader=None):
        self.repository, self.metadata, self.bindings = repository, metadata, bindings
        self.model, self.law_reader = model, law_reader

    async def process(self, job: AssessmentJob) -> None:
        try:
            # Work is bounded below the ten-minute lease; no network call can renew ownership.
            async with asyncio.timeout(480):
                if job["model_name"] != self.model.model:
                    raise AssessmentError("assessment_model_changed")
                proposals, findings, partial = await self.analyze(job)
            await self.repository.finish(
                job, proposals=proposals, findings=findings, partial=partial
            )
        except Exception as exc:
            # Exception messages can contain provider payloads; persist only stable codes.
            code = (
                exc.code
                if isinstance(exc, AssessmentError)
                else "assessment_timeout"
                if isinstance(exc, TimeoutError)
                else "assessment_failed"
            )
            await self.repository.finish(
                job, proposals=[], findings=[], error_code=code
            )

    async def analyze(self, job: AssessmentJob) -> AssessmentAnalysis:
        target = job["target_ref"]
        table = await self.metadata.get_table_by_name(target["fully_qualified_name"])
        verify_table(table, target)
        prepared = await build_context(job, table, self.bindings)
        context = prepared.model_input
        require_bounded_context(context)
        diagnostics, partial = await collect_law_evidence(
            job,
            list(prepared.columns.values()),
            context,
            prepared.evidence,
            self.model,
            self.law_reader,
        )
        context["evidence"] = prepared.evidence
        require_bounded_context(context)
        output = await self.model.generate(
            instruction=ASSESSMENT_INSTRUCTION,
            context=context,
            output_type=AssessmentOutput,
        )
        proposals, findings, rejected = await validate_output(
            job,
            table,
            prepared.columns,
            prepared.concepts,
            prepared.candidates_by_column,
            prepared.evidence,
            output,
            self.bindings,
        )
        if "disclosure_assessment" in job["scopes"] and not any(
            f.get("scope") == "disclosure_assessment" for f in findings
        ):
            partial = True
            diagnostics.append(
                {
                    "scope": "disclosure_assessment",
                    "summary": "모델이 개방 진단 결과를 반환하지 않았습니다. 추가 검토가 필요합니다.",
                    "code": "disclosure_result_missing",
                }
            )
        # Reject all effects if the source changed during inference.
        verify_table(
            await self.metadata.get_table_by_name(target["fully_qualified_name"]),
            target,
        )
        return AssessmentAnalysis(
            proposals, diagnostics + findings, partial or rejected
        )
