from __future__ import annotations

import asyncio
import logging


from teoria.features.semantic_modeling.binding.repository import BindingRepository
from teoria.features.legal_information.search import LawSearchReader
from teoria.features.metadata_management.intelligence.asset_assessment.model_client import AssessmentModelClient
from teoria.features.metadata_management.intelligence.asset_assessment.repository import AssessmentRepository
from teoria.features.metadata_management.intelligence.asset_assessment.service import AssetAssessmentService
from teoria.integrations.openmetadata import OpenMetadataClient
from teoria.settings import bootstrap_settings


async def run():
    settings = bootstrap_settings()
    if not (
        settings.assessment_enabled
        and settings.app_database_url
        and settings.openmetadata_enabled
        and settings.assessment_model_url
        and settings.assessment_model_name
    ):
        raise ValueError(
            "Configure the assessment model, Application DB and OpenMetadata before starting the Worker"
        )
    repository = AssessmentRepository(settings.app_database_url)
    service = AssetAssessmentService(
        repository,
        OpenMetadataClient(
            settings.openmetadata_base_url,
            settings.openmetadata_auth_token,
            timeout_seconds=settings.openmetadata_timeout_seconds,
            verify_ssl=settings.openmetadata_verify_ssl,
        ),
        BindingRepository(settings.app_database_url),
        AssessmentModelClient(
            settings.assessment_model_url,
            settings.assessment_model_name,
            settings.assessment_model_token,
            timeout=settings.assessment_model_timeout_seconds,
            max_tokens=settings.assessment_model_max_tokens,
        ),
        LawSearchReader(settings.admin_data_database_url)
        if settings.admin_data_database_url else None,
    )
    while True:
        try:
            job = await repository.claim()
            if job:
                await service.process(job)
                continue
        except Exception:
            logging.error(
                "Asset assessment worker iteration failed; waiting before retry"
            )
        await asyncio.sleep(5)


def main():
    asyncio.run(run())


if __name__ == "__main__":
    main()
