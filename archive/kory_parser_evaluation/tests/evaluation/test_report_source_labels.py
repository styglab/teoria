import pytest

from evaluations.public_procurement.report import generate
from evaluations.runner import sha, write_json


def test_report_selects_corrected_frozen_labels_without_overwriting_original(tmp_path):
    for directory in ['sample', 'benchmark/case', 'acceptance']:
        (tmp_path / directory).mkdir(parents=True)
    write_json(tmp_path / 'source_labels.json', {'corpus': 'original'})
    write_json(tmp_path / 'final_labels.json', {'corpus': 'separate_correction'})
    original = (tmp_path / 'source_labels.json').read_bytes()
    engines = ['baseline', 'candidate', 'kordoc']
    write_json(tmp_path / 'sample/sampling.json', {'sampled_count': 1, 'formats': {'hwpx': 1},
               'splits': {'development': 1}, 'notice_frame_count': 1})
    write_json(tmp_path / 'benchmark/benchmark.json', {'manifest_sha256': 'same', 'reference_version': 'test',
               'results': [{'document_id': 'case', 'engines': {e: {'success': True, 'version': 'test', 'median_seconds': 1} for e in engines}}]})
    for engine in engines:
        write_json(tmp_path / 'benchmark/case' / (engine + '.json'), {'blocks': []})
    write_json(tmp_path / 'quality.json', {'benchmark_manifest_sha256': 'same',
               'labels_sha256': sha((tmp_path / 'final_labels.json').read_bytes()), 'labelled_documents': 1,
               'totals': {e: {} for e in engines}})
    write_json(tmp_path / 'acceptance/acceptance.json', {'accepted': True, 'applied': True,
               'tests_passed': True, 'changed_documents': []})
    with pytest.raises(ValueError, match='Source labels changed'):
        generate(tmp_path, tmp_path / 'wrong', cleanup_intermediates=False)
    result = generate(tmp_path, tmp_path / 'correct', labels_name='final_labels.json', cleanup_intermediates=False)
    assert result['source_labels_sha256'] == sha((tmp_path / 'final_labels.json').read_bytes())
    assert (tmp_path / 'source_labels.json').read_bytes() == original
