"""Explicit, bounded backfill of catalog metadata and per-document object references."""
import os
from pathlib import Path

from teoria.features.specification_processing.catalog.repository import DocumentCatalogRepository
from teoria.features.specification_processing.catalog.results import store_document_results
from teoria.features.specification_processing.storage.artifact_store import artifact_store
from teoria.features.specification_processing.workspace_router import ProcessingWorkspaceRepository, verified_artifact


async def index_catalog(limit=100):
    database_url = os.environ['TEORIA_PIPELINE_DATA_DATABASE_URL']
    root = os.environ.get('TEORIA_SPECIFICATION_ARTIFACT_ROOT', 's3://teoria-artifacts')
    catalog = DocumentCatalogRepository(database_url)
    workspace = ProcessingWorkspaceRepository(database_url)
    indexed = failed = 0
    for run in await catalog.index_runs(limit):
        try:
            detail = await workspace.detail(run['run_id'])
            refs = detail['artifacts']
            extracted = next(r for r in refs if r['key'].endswith('/extracted.json') or r['key']=='extracted.json')
            normalized = next((r for r in refs if r['key'].endswith('/normalized.json')), None)
            corpus = await verified_artifact(extracted, Path('/app/specification_artifacts'), root, limit=50*1024*1024)
            norm = await verified_artifact(normalized, Path('/app/specification_artifacts'), root, limit=50*1024*1024) if normalized else None
            async with artifact_store(root) as store:
                references = await store_document_results(store, run['run_id'], corpus, norm)
            await catalog.index_metadata(run['run_id'], corpus.get('documents', []) + corpus.get('unavailable_documents', []), references)
            indexed += 1
        except Exception:
            # No private source text, storage credentials or provider errors in CLI output.
            failed += 1
    return {'indexed_runs': indexed, 'failed_runs': failed}
