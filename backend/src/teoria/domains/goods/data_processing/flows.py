"""Extraction task sequence for operational and evaluation callers."""

from prefect import flow
from teoria.domains.goods.contracts import SpecificationRun
from teoria.domains.goods.data_processing import tasks


async def extract_documents(request: SpecificationRun, workspace: str):
    """Shared production/evaluation Task sequence; no DB lifecycle or standard selection."""
    reused = await tasks.stage_original_documents(request, workspace)
    if not reused:
        await tasks.parse_documents(request, workspace)
        await tasks.extract_entity_relations(request, workspace)
        await tasks.extract_requirements(request, workspace)
        await tasks.resolve_attribute_semantics(request, workspace)
    ref = await tasks.persist_extraction(request, workspace, reused)
    return ref, reused


@flow(name="procurement-extraction-evaluation", persist_result=False, log_prints=False)
async def extraction_evaluation_flow(manifest: dict, workspace: str):
    request = SpecificationRun.model_validate(manifest)
    if request.extraction_checkpoint is not None:
        raise ValueError("IE evaluation must rerun extraction, not reuse a checkpoint")
    # Evaluation must measure fresh inference, never operational checkpoint reuse.
    request = request.model_copy(update={"reuse_stage_checkpoints": False})
    ref, _ = await extract_documents(request, workspace)
    return ref
