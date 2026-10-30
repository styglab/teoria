"""Publish accepted intermediate results before removing disposable local workspaces."""
import asyncio
from contextlib import asynccontextmanager
import hashlib
import io
import json
from pathlib import Path
import shutil
import tempfile
from urllib.parse import urlsplit
import zipfile
from teoria.features.specification_processing.storage.artifact_store import artifact_store

ACCEPTED_NAMES={
    'work.json','extracted.json','normalized.json','document.json','native.json',
    'graph.json','summary.json','status.json','inventory.json','held_relations.json',
    'inventory_validation.json','details_validation.json','attribute_graph.json',
    'identifier_projection.json','document_assessment.json','failure.json','coverage.json',
}
DECISION_NAMES={kind+suffix+'_'+result+'.json'
    for kind in ['item_type','characteristic'] for suffix in ['','_repair_1'] for result in ['plan','check']}
DECISION_NAMES.add('validation_check.json')


class ProcessingWorkspace:
    def __init__(self,root_uri,run_id,label):
        self.root_uri=root_uri;self.run_id=run_id;self.label=label
        self.path=Path(tempfile.mkdtemp(prefix='specification_'+label+'_'))
        self.references=[];self.published=False

    def archive(self,error_code):
        buffer=io.BytesIO();total=0
        with zipfile.ZipFile(buffer,'w',compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(self.path.rglob('*.json')):
                if path.name not in ACCEPTED_NAMES|DECISION_NAMES or path.is_symlink() or not path.resolve().is_relative_to(self.path):continue
                relative=path.relative_to(self.path)
                if any(part in {'inference','semantic_inference','batches'} for part in relative.parts):continue
                if relative.parts[0] not in {'processing','work.json','extracted.json','normalized.json'} and relative.as_posix() not in DECISION_NAMES:continue
                data=path.read_bytes();total+=len(data)
                if total>100*1024*1024:raise ValueError('diagnostic archive exceeds 100 MiB; local workspace retained')
                archive.writestr(zipfile.ZipInfo(relative.as_posix(),date_time=(1980,1,1,0,0,0)),data,compress_type=zipfile.ZIP_DEFLATED)
            archive.writestr('workspace_status.json',json.dumps({'run_id':self.run_id,'error_code':error_code}))
        return buffer.getvalue()

    async def publish(self,error_code=None):
        if self.published:return self.references
        if urlsplit(self.root_uri).scheme=='s3':
            raw=await asyncio.to_thread(self.archive,error_code)
            digest=hashlib.sha256(raw).hexdigest()
            key=f'specification_processing/{self.run_id}/diagnostics/{self.label}_{digest}.zip'
            async with artifact_store(self.root_uri) as store:
                ref=await store.put(key,raw,'application/zip')
            self.references.append(ref.model_dump(mode='json'))
        self.published=True
        return self.references


@asynccontextmanager
async def processing_workspace(root_uri,run_id,label):
    workspace=ProcessingWorkspace(root_uri,run_id,label)
    try:
        yield workspace
    except BaseException as error:
        try:await asyncio.shield(workspace.publish(type(error).__name__))
        except BaseException:
            error.add_note('Intermediate upload failed; local workspace retained at '+str(workspace.path))
            raise error
        if (workspace.path/'sources').exists() and not (workspace.path/'work.json').exists():
            error.add_note('Source upload not confirmed; local workspace retained at '+str(workspace.path))
            raise
        await asyncio.to_thread(shutil.rmtree,workspace.path)
        raise
    else:
        try:await workspace.publish()
        except BaseException as error:
            error.add_note('Local workspace retained at '+str(workspace.path))
            raise
        await asyncio.to_thread(shutil.rmtree,workspace.path)
