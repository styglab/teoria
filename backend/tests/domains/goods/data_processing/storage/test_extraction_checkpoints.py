"""Only matching source/model/stage revisions may reuse accepted observations."""
import hashlib
import json
from pathlib import Path
import pytest
from teoria.domains.goods.data_processing.storage.artifact_store import FileArtifactStore
from teoria.domains.goods.data_processing.storage.extraction_checkpoints import ExtractionCheckpoints


def cache(store,model='pinned_model',**changes):
    return ExtractionCheckpoints(store,model,{'parse':'parse_v1','composition':'composition_v1',
        'attributes':'attributes_v1','semantics':'semantics_v1',**changes})


async def test_semantic_change_keeps_composition_but_does_not_reuse_old_attribute_resolution(tmp_path):
    store=FileArtifactStore(tmp_path);old=cache(store);inputs={'source_sha256':'original','graph':{'entities':['root']}}
    await old.put('composition',inputs,{'accepted_entities':['root']})
    await old.put('semantics',inputs,{'accepted_resolution':'old'})
    new=cache(store,semantics='semantics_v2')
    assert await new.get('composition',inputs)=={'accepted_entities':['root']}
    assert await new.get('semantics',inputs) is None


async def test_source_model_upstream_observation_and_stage_code_changes_invalidate_reuse(tmp_path):
    store=FileArtifactStore(tmp_path);old=cache(store);inputs={'source_sha256':'original','graph':{'name':'CPU'}}
    await old.put('attributes',inputs,{'attributes':[{'value_raw':'16'}]})
    assert await old.get('attributes',inputs)=={'attributes':[{'value_raw':'16'}]}
    assert await old.get('attributes',{**inputs,'source_sha256':'different'}) is None
    assert await old.get('attributes',{**inputs,'graph':{'name':'GPU'}}) is None
    assert await cache(store,model='different_model').get('attributes',inputs) is None
    assert await cache(store,attributes='changed_policy').get('attributes',inputs) is None


async def test_disposable_workspace_paths_do_not_invalidate_identical_source_evidence(tmp_path):
    c=cache(FileArtifactStore(tmp_path));inputs={'source_sha256':'same','document':{'source_path':'/old/input','parse_path':'/old/native','text':'CPU 16core'}}
    await c.put('attribute_batch',inputs,{'attributes':[{'value_raw':'16'}]})
    new={**inputs,'document':{**inputs['document'],'source_path':'/new/input','parse_path':'/new/native'}}
    assert await c.get('attribute_batch',new)=={'attributes':[{'value_raw':'16'}]}


async def test_partial_run_can_reuse_one_accepted_batch_without_fabricating_the_failed_batch(tmp_path):
    c=cache(FileArtifactStore(tmp_path));inputs={'source_sha256':'same','fragments':['CPU 16core']}
    await c.put('attribute_batch',inputs,{'attributes':[{'value_raw':'16'}]})
    assert await c.get('attribute_batch',inputs) is not None
    assert await c.get('attribute_batch',{**inputs,'fragments':['GPU 141GB']}) is None
    assert await c.get('semantic_batch',inputs) is None


async def test_disabled_or_unpinned_cache_never_reuses_predictions(tmp_path):
    store=FileArtifactStore(tmp_path);old=cache(store)
    await old.put('composition',{}, {'graph':'accepted'})
    disabled=ExtractionCheckpoints(store,'pinned_model',old.revisions,enabled=False)
    assert await disabled.get('composition',{}) is None
    await disabled.put('composition',{}, {'graph':'unapproved'})
    assert await old.get('composition',{})=={'graph':'accepted'}
    assert await cache(store,model=None).get('composition',{}) is None


async def test_corrupted_checkpoint_cannot_supply_observations(tmp_path):
    c=cache(FileArtifactStore(tmp_path));await c.put('attribute_batch',{}, {'attributes':[]})
    path=next(tmp_path.rglob('*.json'));data=json.loads(path.read_text());data['data']['attributes']=[{'value_raw':'invented'}];path.write_text(json.dumps(data))
    with pytest.raises(ValueError,match='integrity'):await c.get('attribute_batch',{})


async def test_parser_checkpoint_rebases_paths_without_changing_the_native_source_hash(tmp_path):
    old=tmp_path/'old';old.mkdir();source=tmp_path/'source.pdf';source.write_bytes(b'original')
    sha=hashlib.sha256(source.read_bytes()).hexdigest();native=b'{"sha256":"'+sha.encode()+b'"}\n'
    (old/'native.json').write_bytes(native)
    context={'source_sha256':sha,'native_sha256':hashlib.sha256(native).hexdigest(),
             'source_path':'/disposable/old/source.pdf','parse_path':'/disposable/old/native.json'}
    (old/'document.json').write_text(json.dumps(context));(old/'document_assessment.json').write_text('{"status":"classified"}')
    c=cache(FileArtifactStore(tmp_path/'objects'));inputs={'source_sha256':sha,'parser_runtime':'pinned'}
    await c.record('parse',inputs,old)
    new=tmp_path/'new';assert await c.restore('parse',inputs,new,source)
    restored=json.loads((new/'document.json').read_text())
    assert restored['source_path']==str(source) and restored['parse_path']==str(new/'native.json')
    assert (new/'native.json').read_bytes()==native
    assert restored['native_sha256']==hashlib.sha256((new/'native.json').read_bytes()).hexdigest()


async def test_unexpected_checkpoint_paths_are_rejected_before_writing(tmp_path):
    c=cache(FileArtifactStore(tmp_path/'objects'));inputs={'source_sha256':'same'}
    await c.put('parse',inputs,{'files':{'../../outside.json':'{}'}})
    with pytest.raises(ValueError,match='file set'):await c.restore('parse',inputs,tmp_path/'out',tmp_path/'source')
    assert not (tmp_path/'outside.json').exists()


def test_stage_code_fingerprints_follow_the_owning_dependency_boundary(tmp_path,monkeypatch):
    from teoria.domains.goods.data_processing.storage import extraction_checkpoints as module
    monkeypatch.setattr(module,'ROOT',tmp_path)
    (tmp_path.parent/'contracts.py').write_text('contract = 1\n')
    (tmp_path/'parsing').mkdir();(tmp_path/'parsing/document_parser.py').write_text('parse_policy = 1\n')
    (tmp_path/'extraction').mkdir()
    semantic=tmp_path/'extraction/attribute_resolution.py';semantic.write_text('semantic_policy = 1\n')
    composition=tmp_path/'extraction/entity_relation_extraction.py';composition.write_text('composition_policy = 1\n')
    before=module.stage_revisions();semantic.write_text('semantic_policy = 2\n');after=module.stage_revisions()
    assert after['semantics']!=before['semantics']
    assert all(after[stage]==before[stage] for stage in ('parse','composition','attributes'))
    composition.write_text('composition_policy = 2\n');changed=module.stage_revisions()
    assert changed['composition']!=after['composition'] and changed['semantics']!=after['semantics']
    assert changed['parse']==after['parse']
