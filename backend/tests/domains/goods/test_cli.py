"""The maintained CLI accepts both batch management inputs and explicit processing runs."""
from argparse import Namespace
import json
from unittest.mock import AsyncMock

from teoria.domains.goods.cli import _run_processing
from teoria.domains.goods.contracts import RunResult


def test_cli_runs_typed_standard_management_and_reports_held(tmp_path,monkeypatch,capsys):
    from teoria.domains.goods.workflows import specifications as flows
    flow=AsyncMock(return_value={'status':'held','reason':'no_specification_files'})
    monkeypatch.setattr(flows,'standard_management_flow',flow)
    manifest=tmp_path/'batch.json'
    manifest.write_text(json.dumps({'classification_code':'4321150102','target_specifications':2,
        'documents':[{'document_id':'server','filename':'server.hwp','source_uri':'file:///server.hwp'}]}))
    assert _run_processing(Namespace(manifest=manifest))==1
    assert flow.await_args.kwargs['manifest']['target_specifications']==2
    assert json.loads(capsys.readouterr().out)['reason']=='no_specification_files'


def test_cli_preserves_explicit_run_dispatch(tmp_path,monkeypatch,capsys):
    from teoria.domains.goods.workflows import specifications as flows
    flow=AsyncMock(return_value=RunResult(run_id='cli_verify',status='partial',artifacts=[],
        document_results=[],summary={}))
    monkeypatch.setattr(flows,'standard_management_flow',flow)
    manifest=tmp_path/'run.json'
    manifest.write_text(json.dumps({'mode':'standard_management','run_id':'cli_verify',
        'artifact_root':tmp_path.as_uri(),'documents':[
            {'document_id':'server','filename':'server.hwp','source_uri':'file:///server.hwp'}]}))
    assert _run_processing(Namespace(manifest=manifest))==0
    assert flow.await_args.args[0]['mode']=='standard_management'
    assert json.loads(capsys.readouterr().out)['status']=='partial'


def test_cli_dispatches_meaning_review_without_running_extraction(tmp_path, monkeypatch, capsys):
    from teoria.domains.goods.cli import run_command
    from teoria.domains.goods.normalization.meaning_proposals import meaning_review
    from unittest.mock import Mock
    validated = object()
    validate = Mock(return_value=validated)
    prepare = AsyncMock(return_value={'review_id': 'fixture', 'summary': {'held': 0}, 'auto_applied': False})
    monkeypatch.setattr(meaning_review.MeaningReviewInput, 'model_validate', validate)
    monkeypatch.setattr(meaning_review, 'prepare_meaning_review', prepare)
    manifest = tmp_path / 'review.json'
    manifest.write_text('{"review_id":"fixture"}')
    root = (tmp_path / 'artifacts').as_uri()
    assert run_command(Namespace(specification_command='review-meanings', manifest=manifest, output_root=root)) == 0
    validate.assert_called_once_with({'review_id': 'fixture'})
    prepare.assert_awaited_once_with(validated, root)
    assert not json.loads(capsys.readouterr().out)['auto_applied']
