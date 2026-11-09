from types import SimpleNamespace
from copy import deepcopy
from unittest.mock import AsyncMock
import pytest
from teoria.features.specification_processing.processing_quality import AutomaticApprovalLimits,automatic_approval_quality,processing_quality
from backend.tests.features.specification_processing.extraction.test_extraction_isolation import corpus_fixture


def quality_fixture():
    corpus,_,_=corpus_fixture()
    request=SimpleNamespace(model='pinned',classification_code=None)
    return processing_quality(request,corpus,{'applied':2},'revision')


def test_default_limits_hold_invalid_source_data_without_silently_losing_counts():
    quality=quality_fixture();quality['validation_errors']=1
    gate=automatic_approval_quality(quality,AutomaticApprovalLimits())
    assert not gate['ready'] and gate['reasons']==['source_validation_errors']
    assert not automatic_approval_quality(None,AutomaticApprovalLimits())['ready']


def test_count_drift_compares_only_the_same_originals_model_and_parser():
    before=quality_fixture();before['accepted_attributes']=100;before['run_id']='before'
    after=deepcopy(before);after['accepted_attributes']=20
    gate=automatic_approval_quality(after,AutomaticApprovalLimits(),before)
    assert not gate['ready'] and gate['attribute_count_change_ratio']==0.8
    before['model_requested']='other'
    assert automatic_approval_quality(after,AutomaticApprovalLimits(),before)['ready']
    before=quality_fixture();before['source_group_sha256']='different'
    assert automatic_approval_quality(after,AutomaticApprovalLimits(),before)['attribute_count_change_ratio'] is None


async def test_quality_hold_never_opens_an_approval_http_request(monkeypatch):
    from teoria.features.specification_processing import application_standard_approval as automatic
    from teoria.features.specification_processing.models import SpecificationRun,RunResult
    request=SpecificationRun(run_id='held_quality',mode='standard_management',artifact_root='file:///tmp/fixture',
        auto_approve_application_standard=True,documents=[{'document_id':'d','filename':'d.pdf','source_uri':'file:///tmp/d.pdf'}])
    q=quality_fixture();q['model_requested']=None;q['validation_errors']=1
    result=RunResult(run_id=request.run_id,status='partial',summary={'quality':q},document_results=[],artifacts=[])
    class Repository:record_application_standard=AsyncMock()
    monkeypatch.setattr(automatic.SpecificationRepository,'from_environment',lambda:Repository())
    def forbidden():raise AssertionError('quality-rejected data must not request approval')
    monkeypatch.setattr(automatic,'GoodsAuthoringClient',forbidden)
    updated=await automatic.approve_application_standard.fn(request,result)
    assert updated.summary['automatic_application_standard']['reason']=='quality_threshold_exceeded'
    Repository.record_application_standard.assert_awaited_once()
