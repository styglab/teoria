"""A bounded semantic context from verified, published Ontology artifacts."""
import hashlib

from teoria.features.semantic_modeling.goods_dictionary.meaning_contracts import parse_dictionary_snapshot
from teoria.features.semantic_modeling.ontology.publication_contracts import (
    PublishedOntology, PublishedOntologyContext, select_publication_concepts,
)
from teoria.features.specification_processing.storage.artifact_store import read_uri


def select_context(snapshot, concept_ids):
    """Only adapt extraction vocabulary; publication identity belongs to Ontology."""
    catalog = select_publication_concepts(snapshot.ontologies, concept_ids)
    kinds = {'object': 'entity', 'property': 'attribute', 'relationship': 'relation'}
    return {identifier: {**concept, 'kind': kinds[concept['kind']]}
            for identifier, concept in catalog.items()}


async def verify_publications(publications, api):
    for value in publications:
        publication = PublishedOntology.model_validate(value)
        actual = PublishedOntology.model_validate(
            await api.ontology_publication(publication.ontology.version_id))
        if actual != publication:
            raise ValueError('ontology_context_publication_unavailable')


async def verify_expression_examples(snapshot, catalog, api):
    """Legacy expression snapshots supply examples, never publication authority."""
    current = parse_dictionary_snapshot(await api.dictionary_meaning('GET', '/snapshot'))
    if current.schema_version != 2:
        raise ValueError('published_ontology_context_required')
    approved = {str(m['mapping_id']): m for m in current.mappings if m['status'] == 'approved'}
    sources = {str(s['entry_id']): s for s in current.sources}
    frozen_sources = {str(s['entry_id']): s for s in snapshot.sources}
    for mapping in snapshot.mappings:
        if mapping['status'] != 'approved' or str(mapping['target_concept_id']) not in catalog:
            continue
        if approved.get(str(mapping['mapping_id'])) != mapping:
            raise ValueError('ontology_context_dictionary_changed')
        pending = [str(mapping['source_entry_id'])]
        seen = set()
        while pending:
            identifier = pending.pop()
            if identifier in seen:
                raise ValueError('ontology_context_cyclic_expression_owner')
            seen.add(identifier)
            source = frozen_sources.get(identifier)
            if source is None or sources.get(identifier) != source or source['status'] != 'approved':
                raise ValueError('ontology_context_dictionary_changed')
            if source.get('owner_entry_id'):
                pending.append(str(source['owner_entry_id']))


async def load_published_context(config, api, *, standard=None):
    """Resolve pinned meaning through Ontology; dictionaries are optional examples."""
    if config.publications:
        publications = []
        for reference in config.publications:
            publication = PublishedOntology.model_validate(
                await api.ontology_publication(reference.version_id))
            if publication.ontology != reference:
                raise ValueError('ontology_context_publication_unavailable')
            publications.append(publication)
        snapshot = PublishedOntologyContext.from_publications(publications)
    else:
        raw = await read_uri(config.snapshot.uri)
        if hashlib.sha256(raw).hexdigest() != config.snapshot.sha256:
            raise ValueError('ontology_context_checksum_mismatch')
        import json
        payload = json.loads(raw)
        if payload.get('artifact_kind') == 'published_ontology_context':
            snapshot = PublishedOntologyContext.model_validate(payload)
        else:
            snapshot = parse_dictionary_snapshot(raw)
            if snapshot.schema_version != 2:
                raise ValueError('published_ontology_context_required')
        await verify_publications(snapshot.ontologies, api)
    catalog = select_context(snapshot, config.concept_ids)
    if not isinstance(snapshot, PublishedOntologyContext):
        await verify_expression_examples(snapshot, catalog, api)
    if standard is not None:
        package_raw = await read_uri(standard.uri)
        if hashlib.sha256(package_raw).hexdigest() != standard.sha256:
            raise ValueError('standard checksum mismatch')
        import json
        payload = json.loads(package_raw)
        if payload.get('artifact_kind') == 'goods_normalization_package':
            from teoria.features.goods_normalization.contracts import NormalizationPackage
            package = NormalizationPackage.model_validate(payload)
            if package.profile.ontology.model_dump(mode='json') not in [c['ontology'] for c in catalog.values()]:
                raise ValueError('ontology_context_profile_version_mismatch')
    return snapshot, catalog
