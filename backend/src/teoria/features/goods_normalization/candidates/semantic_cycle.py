"""One bounded meaning-to-Draft cycle; auto approval is an isolated evaluation policy."""

from uuid import UUID
from teoria.features.goods_normalization.candidates.semantic_resolution import (
    resolve_meanings,
)
from teoria.features.goods_normalization.candidates.semantic_authoring import (
    create_ontology_draft,
    materialize_profile,
)


async def run_semantic_cycle(
    repository,
    base_revision_id,
    bundles,
    *,
    model,
    version,
    actor,
    auto_approve=False,
    timeout=300,
):
    profile, ontology = await repository.candidate_context(base_revision_id)
    if auto_approve and not profile.ontology.namespace.startswith("goods_eval_"):
        raise ValueError(
            "automatic approval is limited to goods_eval_ evaluation ontologies"
        )
    report = await resolve_meanings(
        bundles, profile, ontology, model=model, timeout=timeout
    )
    accepted = [d for d in report["decisions"] if d["action"] != "hold"]
    result = {
        "status": "held",
        "semantic_report": report,
        "ontology_draft_id": None,
        "profile_revision_id": None,
        "auto_approved": False,
    }
    if not accepted:
        return result
    draft = await create_ontology_draft(
        repository, base_revision_id, bundles, report, version=version, actor=actor
    )
    result.update(draft)
    if draft["ontology_draft_id"] and not auto_approve:
        result["status"] = "ontology_draft_created"
        return result
    published_id = profile.ontology.version_id
    if draft["ontology_draft_id"]:
        published_id = UUID(draft["ontology_draft_id"])
        authoring = repository.ontology_authoring
        await authoring.transition(published_id, action="submit", actor=actor)
        await authoring.transition(published_id, action="approve", actor=actor)
        await authoring.publish(published_id, actor=actor)
    new_profile = await materialize_profile(
        repository,
        base_revision_id,
        bundles,
        report,
        published_version_id=published_id,
        version=version,
        actor=actor,
    )
    revision_id = UUID(new_profile["revision_id"])
    result.update(status="profile_draft_created", profile_revision_id=str(revision_id))
    if auto_approve:
        await repository.transition(
            revision_id,
            action="submit",
            actor=actor,
            comment="Explicit automatic approval for isolated evaluation",
        )
        await repository.transition(
            revision_id,
            action="approve",
            actor=actor,
            comment="Explicit automatic approval for isolated evaluation",
        )
        result.update(status="approved", auto_approved=True)
    return result
