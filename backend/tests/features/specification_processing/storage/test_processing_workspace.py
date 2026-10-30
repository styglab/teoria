import importlib
import io
import json
import shutil
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path
import pytest
from teoria.features.specification_processing.storage.artifact_store import FileArtifactStore
module=importlib.import_module('teoria.features.specification_processing.storage.processing_workspace')


@pytest.fixture
def storage(tmp_path,monkeypatch):
    store=FileArtifactStore(tmp_path/'objects')
    @asynccontextmanager
    async def factory(root):yield store
    monkeypatch.setattr(module,'artifact_store',factory)
    return store


async def test_verified_archive_precedes_cleanup_and_excludes_disposable_model_files(storage):
    async with module.processing_workspace('s3://test','run','extraction') as work:
        saved=work.path;folder=saved/'processing'/'doc';folder.mkdir(parents=True)
        (folder/'document.json').write_text('{"text":"source evidence"}')
        (folder/'prompt.json').write_text('temporary prompt')
        (saved/'work.json').write_text('[]')
        refs=await work.publish()
        assert saved.exists() and len(refs)==1
        body=await storage.get(refs[0]['key'])
        with zipfile.ZipFile(io.BytesIO(body)) as archive:
            assert 'processing/doc/document.json' in archive.namelist()
            assert 'processing/doc/prompt.json' not in archive.namelist()
    assert not saved.exists()


async def test_processing_failure_archives_diagnostic_then_cleans_local(storage):
    with pytest.raises(ValueError,match='processing failed'):
        async with module.processing_workspace('s3://test','run','processing') as work:
            path=work.path;(path/'work.json').write_text('[]')
            raise ValueError('processing failed')
    assert not path.exists()
    archive=next(storage.root.rglob('*.zip'))
    with zipfile.ZipFile(archive) as files:
        assert json.loads(files.read('workspace_status.json'))['error_code']=='ValueError'


async def test_storage_failure_retains_local_results(tmp_path,monkeypatch):
    class Broken:
        async def put(self,*args):raise OSError('object storage unavailable')
    @asynccontextmanager
    async def factory(root):yield Broken()
    monkeypatch.setattr(module,'artifact_store',factory)
    with pytest.raises(OSError):
        async with module.processing_workspace('s3://test','run','processing') as work:
            path=work.path;(path/'work.json').write_text('[]')
    assert (path/'work.json').exists()
    shutil.rmtree(path)


async def test_unconfirmed_source_upload_preserves_original_cache(storage):
    with pytest.raises(ValueError):
        async with module.processing_workspace('s3://test','run','processing') as work:
            path=work.path;(path/'sources').mkdir();(path/'sources'/'original.pdf').write_bytes(b'%PDF-original')
            raise ValueError('source upload failed')
    assert (path/'sources'/'original.pdf').exists()
    shutil.rmtree(path)
