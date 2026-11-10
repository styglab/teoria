"""Fingerprint processing code and the public contracts it consumes."""

import hashlib
from pathlib import Path


def processor_revision():
    import teoria.domains.goods.normalization.contracts
    import teoria.integrations.codex
    import inspect
    from teoria.domains.goods.expression_links.contracts import (
        source_literal_definition,
    )
    import teoria.domains.goods.expression_links.snapshot_contracts as meaning_contracts

    root = Path(__file__).resolve().parent
    paths = sorted(p for p in root.rglob("*.py") if "evaluation" not in p.parts)
    contract_root = Path(teoria.domains.goods.normalization.contracts.__file__).parent
    contract_paths = sorted(contract_root.rglob("*.py"))
    body = b"".join(
        p.relative_to(root).as_posix().encode() + p.read_bytes() for p in paths
    )
    body += b"".join(
        b"goods_normalization/"
        + p.relative_to(contract_root).as_posix().encode()
        + p.read_bytes()
        for p in contract_paths
    )
    body += (
        b"goods_dictionary_contract/"
        + Path(inspect.getfile(source_literal_definition)).read_bytes()
    )
    body += (
        b"goods_dictionary_meaning_contract/"
        + Path(inspect.getfile(meaning_contracts)).read_bytes()
    )
    from teoria.platform.ontology.authoring.publication_contracts import PublishedOntology

    for contract in (
        PublishedOntology,
        teoria.domains.goods.normalization.contracts.normalize_property_number,
        teoria.domains.goods.normalization.contracts.SemanticObservation,
    ):
        body += (
            contract.__module__.encode() + Path(inspect.getfile(contract)).read_bytes()
        )
    runner_root = Path(teoria.integrations.codex.__file__).parent
    body += b"".join(
        b"codex_inference/"
        + p.relative_to(runner_root).as_posix().encode()
        + p.read_bytes()
        for p in sorted(runner_root.rglob("*.py"))
    )
    return hashlib.sha256(body).hexdigest()


def workflow_stage_versions():
    """Keep completed observations reusable across unrelated authoring/UI changes."""
    from teoria.domains.goods.data_processing.storage.extraction_checkpoints import stage_revisions
    root = Path(__file__).resolve().parent
    def digest(patterns):
        paths = {p for pattern in patterns for p in root.glob(pattern) if p.is_file()}
        return hashlib.sha256(b''.join(str(p.relative_to(root)).encode() + p.read_bytes()
                                       for p in sorted(paths))).hexdigest()
    from teoria.domains.goods.normalization import contracts
    from teoria.domains.goods.expression_links import snapshot_contracts
    from teoria.platform.ontology.authoring import publication_contracts, observations, value_policy
    dependencies = sorted({*Path(contracts.__file__).parent.rglob('*.py'),
        Path(snapshot_contracts.__file__), Path(publication_contracts.__file__),
        Path(observations.__file__), Path(value_policy.__file__)})
    dependency_digest = hashlib.sha256(b''.join(p.name.encode() + p.read_bytes() for p in dependencies)).hexdigest()
    versions = {
        'extraction': stage_revisions(),
        'semantics': digest(['normalization/candidates/*.py', 'normalization/contracts/*.py',
                             'normalization/profiles/compiler.py', 'expression_links/expression_contracts.py',
                             'normalization/meaning_proposals/expression_candidates.py',
                             'normalization/meaning_proposals/expression_alignment.py']),
        'application': digest(['normalization/application/*.py', 'normalization/contracts/*.py',
                               'normalization/meaning_proposals/expression_alignment.py',
                               'normalization/meaning_proposals/expression_candidates.py',
                               'expression_links/expression_contracts.py', 'expression_links/snapshot_contracts.py',
                               'workflows/tasks.py']),
    }
    for stage in ('semantics', 'application'):
        versions[stage] = hashlib.sha256((versions[stage] + dependency_digest).encode()).hexdigest()
    return versions


def extraction_revision():
    """Evaluation identity excludes Ontology/API/runtime code unrelated to extraction."""
    from teoria.domains.goods.data_processing.storage.extraction_checkpoints import stage_revisions
    root = Path(__file__).resolve().parent / 'data_processing'
    paths = sorted(p for folder in ('extraction', 'parsing') for p in (root / folder).glob('*.py'))
    body = repr(sorted(stage_revisions().items())).encode()
    body += b''.join(str(p.relative_to(root)).encode() + p.read_bytes() for p in paths)
    return hashlib.sha256(body).hexdigest()


def processing_revision():
    """Identity of document processing, independent of authoring services and Runtime views."""
    root = Path(__file__).resolve().parent
    versions = workflow_stage_versions()
    body = repr((versions['extraction'], versions['application'])).encode()
    paths = sorted({*root.glob('data_processing/storage/*.py'), root/'data_processing/flows.py',
                    root/'workflows/specifications.py', root/'workflows/processing_quality.py',
                    root/'workflows/processing_status.py'})
    return hashlib.sha256(body + b''.join(str(p.relative_to(root)).encode() + p.read_bytes() for p in paths)).hexdigest()
