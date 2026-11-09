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
