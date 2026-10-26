"""Resumable meaning resolution and approval coordination."""

from collections import Counter
from uuid import UUID
from teoria.features.goods_normalization.contracts import checksum
from teoria.features.goods_normalization.candidates.semantic_resolution import (
    resolve_meanings,
)
from teoria.features.goods_normalization.candidates.semantic_authoring import (
    create_ontology_draft,
    materialize_profile,
)
from teoria.features.goods_normalization.candidates.semantic_operation_repository import (
    SemanticOperationRepository,
)


class SemanticOperationService:
    def __init__(
        self, profiles, repository: SemanticOperationRepository, ontology_authoring
    ):
        self.profiles = profiles
        self.repository = repository
        self.ontology_authoring = ontology_authoring

    @staticmethod
    def public(row):
        state = row["checkpoint"]
        return {
            "operation_id": row["operation_id"],
            "status": row["status"],
            "ontology_draft_id": state.get("ontology_draft_id"),
            "profile_revision_id": state.get("profile_revision_id"),
            "decisions": dict(
                Counter(
                    d["action"]
                    for d in state.get("semantic_report", {}).get("decisions", [])
                )
            ),
            "error_code": row["error_code"],
        }

    async def get(self, operation_id, *, actor):
        row = await self.repository.get(operation_id)
        if row is None or row["actor"] != actor:
            raise KeyError(operation_id)
        return self.public(row)

    async def _save(self, operation_id, state, status, error=None):
        return self.public(
            await self.repository.save(operation_id, state, status, error)
        )

    async def execute(self, operation_id, payload, *, actor):
        row = await self.repository.ensure(operation_id, checksum(payload), actor)
        async with self.repository.serialized(operation_id) as acquired:
            if not acquired:
                return {**self.public(row), "status": "running"}
            try:
                row = await self.repository.get(operation_id)
                if row["status"] in {"approved", "held", "rejected"}:
                    return self.public(row)
                state = row["checkpoint"]
                return await self._advance(operation_id, payload, state, actor)
            except BaseException as exc:
                await self._save(
                    operation_id,
                    state if "state" in locals() else row["checkpoint"],
                    "failed",
                    type(exc).__name__,
                )
                raise

    async def _advance(self, operation_id, payload, state, actor):
        from teoria.features.goods_normalization.contracts.candidates import (
            CandidateBundle,
        )

        bundles = [CandidateBundle.model_validate(b) for b in payload["bundles"]]
        base_id = UUID(payload["base_revision_id"])
        profile, ontology = await self.profiles.candidate_context(
            base_id, allow_deprecated=True
        )
        automatic = payload.get("auto_approve", False)
        if automatic and not profile.ontology.namespace.startswith("goods_eval_"):
            raise ValueError("automatic approval requires an evaluation ontology")
        await self._save(operation_id, state, "running")
        if "semantic_report" not in state:
            state["semantic_report"] = await resolve_meanings(
                bundles,
                profile,
                ontology,
                model=payload["model"],
                timeout=payload.get("timeout", 300),
            )
            await self._save(operation_id, state, "running")
        report = state["semantic_report"]
        if all(d["action"] == "hold" for d in report["decisions"]):
            return await self._save(operation_id, state, "held")
        if "ontology_draft_id" not in state:
            state.update(
                await create_ontology_draft(
                    self.profiles,
                    base_id,
                    bundles,
                    report,
                    version=payload["version"],
                    actor=actor,
                    resume=True,
                )
            )
            await self._save(operation_id, state, "running")
        published_id = profile.ontology.version_id
        authoring = self.ontology_authoring
        if state["ontology_draft_id"]:
            published_id = UUID(state["ontology_draft_id"])
            detail = await authoring.get_version(published_id)
            if automatic:
                if detail["status"] == "draft":
                    await authoring.transition(
                        published_id, action="submit", actor=actor
                    )
                    detail = await authoring.get_version(published_id)
                if detail["status"] == "in_review":
                    await authoring.transition(
                        published_id, action="approve", actor=actor
                    )
                    detail = await authoring.get_version(published_id)
                if detail["status"] == "approved":
                    await authoring.publish(published_id, actor=actor)
                    detail = await authoring.get_version(published_id)
            if detail["status"] in {"rejected", "deprecated"}:
                return await self._save(operation_id, state, "rejected")
            if detail["status"] != "published":
                return await self._save(operation_id, state, "awaiting_approval")
        if "profile_revision_id" not in state:
            new = await materialize_profile(
                self.profiles,
                base_id,
                bundles,
                report,
                published_version_id=published_id,
                version=payload["version"],
                actor=actor,
                resume=True,
            )
            state["profile_revision_id"] = new["revision_id"]
            await self._save(operation_id, state, "running")
        revision_id = UUID(state["profile_revision_id"])
        detail = await self.profiles.get(revision_id)
        if automatic:
            if detail["status"] == "draft":
                await self.profiles.transition(
                    revision_id, action="submit", actor=actor
                )
                detail = await self.profiles.get(revision_id)
            if detail["status"] == "in_review":
                await self.profiles.transition(
                    revision_id,
                    action="approve",
                    actor=actor,
                    comment="Explicit automatic approval for isolated evaluation",
                )
                detail = await self.profiles.get(revision_id)
        if detail["status"] in {"rejected", "deprecated"}:
            return await self._save(operation_id, state, "rejected")
        if detail["status"] != "approved":
            return await self._save(operation_id, state, "awaiting_approval")
        await self.profiles.export(revision_id)
        return await self._save(operation_id, state, "approved")
