from __future__ import annotations

from datetime import datetime
from pathlib import Path
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from prefect import flow
from prefect.runtime import flow_run
from teoria.integrations.provider_api.executor import ProviderExecutor
from teoria.integrations.provider_api.errors import ProviderExecutionError
from teoria.integrations.provider_api.secrets import EnvironmentSecretProvider

from teoria.features.legal_information.collection.client import MolegLawClient
from teoria.features.legal_information.collection.parsing import LawValidationError
from teoria.features.legal_information.collection.tasks import (
    PIPELINE_ID,
    load_targets,
    start_law_run,
    resolve_law_target,
    collect_law_catalog,
    save_law_raw,
    select_law_versions,
    fetch_law_version,
    normalize_law,
    load_law_snapshot,
    record_law_progress,
)
from teoria.integrations.data_operations.execution.tasks import (
    start_pipeline_run,
    fail_pipeline_run,
    update_checkpoint,
    complete_pipeline_run,
)
from teoria.integrations.data_operations.models import CollectionWindow, LoadSummary
from teoria.integrations.data_operations.settings import bootstrap_pipeline_settings


def _error_code(exc: Exception) -> str:
    if isinstance(exc, LawValidationError):
        return str(exc)
    if isinstance(exc, ProviderExecutionError):
        return exc.code
    return type(exc).__name__


@flow(name="법령 원문 및 시행일별 버전 동기화", persist_result=False)
async def sync_moleg_laws(
    pipeline_root: str = "/app/backend",
    target_ids: list[str] | None = None,
    reconcile_all: bool = False,
    requests_per_second: float = 1,
):
    settings = bootstrap_pipeline_settings()
    targets = load_targets(pipeline_root, target_ids)
    today = datetime.now(ZoneInfo("Asia/Seoul")).date()
    run_id = flow_run.get_id()
    execution_id = UUID(run_id) if run_id else uuid4()
    checkpoint_id = (
        PIPELINE_ID
        if target_ids is None
        else PIPELINE_ID + ":" + ",".join(sorted(target_ids))
    )
    await start_pipeline_run(
        execution_id, checkpoint_id, CollectionWindow(today, today)
    )
    catalog_count = collected = provisions = raw_count = 0
    failures = []
    try:
        await start_law_run(execution_id, reconcile_all, len(targets))
        async with ProviderExecutor(
            timeout_seconds=settings.source_timeout_seconds,
            max_attempts=settings.source_max_attempts,
            backoff_seconds=settings.source_retry_backoff_seconds,
            secret_provider=EnvironmentSecretProvider(),
        ) as executor:
            client = MolegLawClient.from_pipeline_root(
                Path(pipeline_root),
                executor=executor,
                requests_per_second=requests_per_second,
            )
            for target in targets:
                try:
                    law_id, resolution_responses = await resolve_law_target(
                        client, target
                    )
                    raw_count += len(
                        (await save_law_raw(execution_id, resolution_responses))
                    )
                    catalog = await collect_law_catalog(client, law_id)
                    raw_count += len(
                        (await save_law_raw(execution_id, catalog.responses))
                    )
                    catalog_count += len(catalog.versions)
                    versions = await select_law_versions(
                        target, catalog, reconcile_all, today
                    )
                    version_failures = []
                    for version in versions:
                        try:
                            response = await fetch_law_version(client, version)
                            source_hash = (
                                await save_law_raw(execution_id, [response])
                            )[0]
                            raw_count += 1
                            parsed = normalize_law(response, version)
                            await load_law_snapshot(parsed, response, source_hash)
                            collected += 1
                            provisions += len(parsed.provisions)
                        except Exception as exc:
                            # Continue other versions, but never mark a partial law complete.
                            version_failures.append(
                                {
                                    "mst": version.mst,
                                    "effective_date": version.effective_date.isoformat(),
                                    "error_code": _error_code(exc),
                                }
                            )
                    if version_failures:
                        failures.append(
                            {"target_id": target.id, "versions": version_failures}
                        )
                except Exception as exc:
                    failures.append(
                        {"target_id": target.id, "error_code": _error_code(exc)}
                    )
                await record_law_progress(
                    execution_id, catalog_count, collected, provisions, failures
                )
        if failures:
            raise LawValidationError("law_collection_incomplete")
        summary = await update_checkpoint(
            execution_id, checkpoint_id, today, raw_count, LoadSummary()
        )
        await complete_pipeline_run(execution_id, summary)
        return {
            "execution_id": str(execution_id),
            "targets": len(targets),
            "catalog_versions": catalog_count,
            "collected_versions": collected,
            "provisions": provisions,
            "raw_responses": raw_count,
        }
    except BaseException as exc:
        (await fail_pipeline_run(execution_id, type(exc).__name__))
        raise


@flow(name="저장 법령 원문 재가공", persist_result=False)
async def reparse_moleg_laws(target_id: str | None = None, reparse_all: bool = False):
    from teoria.features.legal_information.collection.tasks import (
        stored_law_versions,
        read_archived_law,
    )

    rows = await stored_law_versions(target_id, reparse_all)
    count = 0
    for row in rows:
        version, response = await read_archived_law(row)
        parsed = normalize_law(response, version)
        await load_law_snapshot(parsed, response, row["source_record_hash"])
        count += 1
    return {"reparsed_versions": count}
