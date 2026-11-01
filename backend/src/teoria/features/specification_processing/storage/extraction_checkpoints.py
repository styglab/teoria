"""Source- and code-pinned extraction observations; never cache raw model responses."""
import asyncio
from contextlib import asynccontextmanager
import hashlib
import json
from pathlib import Path

from teoria.features.specification_processing.storage.artifact_store import artifact_store

ROOT=Path(__file__).resolve().parents[1]
STAGE_MODULES={
    'parse':('parsing/*.py',),
    'composition':('extraction/entity_relation_extraction.py','extraction/target_names.py',
                   'extraction/document_context.py','extraction/value_normalization.py',
                   'parsing/document_evidence.py','parsing/document_assessment.py'),
    'attributes':('extraction/requirement_extraction.py','extraction/attribute_extraction.py',
                  'extraction/attribute_chunking.py','extraction/attribute_validation.py',
                  'extraction/document_context.py','extraction/target_recovery.py',
                  'extraction/value_normalization.py','extraction/requirement_clauses.py',
                  'parsing/document_assessment.py','parsing/document_evidence.py'),
    'semantics':('extraction/attribute_resolution.py','extraction/composition_review.py',
                 'extraction/entity_relation_extraction.py','extraction/attribute_extraction.py',
                 'extraction/attribute_validation.py','extraction/requirement_clauses.py',
                 'extraction/document_context.py','extraction/value_normalization.py',
                 'extraction/target_names.py','parsing/document_evidence.py'),
}
STAGE_FILES={
    'parse':('native.json','document.json','document_assessment.json'),
    'composition':('inventory/document.json','inventory/graph.json','inventory/inventory.json',
                   'inventory/summary.json','inventory/status.json','inventory/inventory_validation.json',
                   'inventory/details_validation.json','inventory/held_relations.json','inventory/identifier_projection.json'),
    'attributes':('attributes/attribute_graph.json','attributes/summary.json','attributes/coverage.json'),
    'semantics':('attributes/attribute_graph.json','attributes/summary.json'),
}
MAX_CHECKPOINT_BYTES=50*1024*1024


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


def stage_revisions():
    from teoria.integrations.codex import runner
    from teoria.features.specification_processing import tasks
    import inspect
    base=[Path(__file__),ROOT/'models.py',*Path(runner.__file__).parent.rglob('*.py')]
    task_names={'parse':'parse_documents','composition':'extract_entity_relations',
                'attributes':'extract_requirements','semantics':'resolve_attribute_semantics'}
    result={}
    for stage,patterns in STAGE_MODULES.items():
        files=set(base)
        for pattern in patterns:files.update(ROOT.glob(pattern))
        code=[(str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else p.name,
               hashlib.sha256(p.read_bytes()).hexdigest()) for p in sorted(files)]
        task=getattr(tasks,task_names[stage])
        code.append(('task',inspect.getsource(getattr(task,'fn',task))))
        result[stage]=digest(code)
    return result


def normalized_inputs(value):
    if isinstance(value,dict):
        return {k:normalized_inputs(v) for k,v in value.items() if k not in {'source_path','parse_path'}}
    if isinstance(value,list):return [normalized_inputs(v) for v in value]
    return value


class ExtractionCheckpoints:
    def __init__(self,store,model,revisions,enabled=True):
        self.store=store;self.model=model;self.revisions=revisions;self.enabled=enabled and bool(model)

    @classmethod
    async def create(cls,store,model,*,enabled=True):
        revisions=await asyncio.to_thread(stage_revisions) if enabled and model else {}
        return cls(store,model,revisions,enabled)

    def identity(self,stage,inputs):
        owner={'inventory':'composition','attribute_batch':'attributes','semantic_batch':'semantics'}.get(stage,stage)
        return digest({'contract':1,'stage':stage,'code':self.revisions[owner],
                       'model':self.model,'inputs':normalized_inputs(inputs)})

    async def get(self,stage,inputs):
        if not self.enabled:return None
        identity=self.identity(stage,inputs);key=f'specification_processing/stage_checkpoints/v1/{stage}/{identity}.json'
        try:raw=await self.store.get(key)
        except FileNotFoundError:return None
        if len(raw)>MAX_CHECKPOINT_BYTES:raise ValueError('extraction checkpoint exceeds size limit')
        payload=json.loads(raw)
        if (payload.get('identity')!=identity or payload.get('payload_sha256')!=digest(payload.get('data'))
                or not isinstance(payload.get('data'),dict)):
            raise ValueError('extraction checkpoint integrity mismatch')
        return payload['data']

    async def put(self,stage,inputs,data):
        if not self.enabled:return
        identity=self.identity(stage,inputs);key=f'specification_processing/stage_checkpoints/v1/{stage}/{identity}.json'
        if await self.get(stage,inputs) is not None:return
        raw=json.dumps({'identity':identity,'payload_sha256':digest(data),'data':data},ensure_ascii=False).encode()
        if len(raw)>MAX_CHECKPOINT_BYTES:return
        try:await self.store.put(key,raw)
        except ValueError as exc:
            # Concurrent runs may produce different valid observations. First writer wins;
            # neither run overwrites it or replaces its own result with a competing prediction.
            if 'immutable' not in str(exc) or await self.get(stage,inputs) is None:raise

    async def restore(self,stage,inputs,folder,source_path):
        data=await self.get(stage,inputs)
        if data is None:return False
        files=data.get('files',{})
        if set(files)!=set(STAGE_FILES[stage]) or any(not isinstance(v,str) for v in files.values()):
            raise ValueError('invalid extraction checkpoint file set')
        def restore_files():
            if stage=='parse':
                context=json.loads(files['document.json'])
                if (context['native_sha256']!=hashlib.sha256(files['native.json'].encode()).hexdigest()
                        or json.loads(files['native.json']).get('sha256')!=inputs['source_sha256']):
                    raise ValueError('extraction checkpoint native source mismatch')
            for name,raw in files.items():
                path=Path(folder)/name;path.parent.mkdir(parents=True,exist_ok=True)
                if name in {'document.json','inventory/document.json'}:
                    context=json.loads(raw)
                    if context['source_sha256']!=inputs['source_sha256']:
                        raise ValueError('extraction checkpoint source mismatch')
                    context.update(source_path=str(source_path),parse_path=str(Path(folder)/'native.json'))
                    raw=json.dumps(context,ensure_ascii=False,indent=2)+'\n'
                path.write_bytes(raw.encode())
        await asyncio.to_thread(restore_files)
        return True

    async def record(self,stage,inputs,folder):
        if not self.enabled:return
        def files():
            output={}
            for name in STAGE_FILES[stage]:
                raw=(Path(folder)/name).read_bytes().decode()
                if name in {'document.json','inventory/document.json'}:
                    context=json.loads(raw);context.pop('source_path',None);context.pop('parse_path',None)
                    raw=json.dumps(context,ensure_ascii=False,indent=2)+'\n'
                output[name]=raw
            return output
        await self.put(stage,inputs,{'files':await asyncio.to_thread(files)})


@asynccontextmanager
async def extraction_checkpoints(request):
    async with artifact_store(request.artifact_root) as store:
        yield await ExtractionCheckpoints.create(store,request.model,enabled=request.reuse_stage_checkpoints)
