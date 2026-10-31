"""Profile authoring policy, candidate coordination and immutable approval packages."""

import json
from uuid import UUID

from teoria.features.goods_normalization.contracts import (
    NormalizationPackage,
    NormalizationProfile,
    checksum,
)
from teoria.features.goods_normalization.profiles.compiler import (
    compile_package,
    resolve_profile_template,
)
from teoria.features.goods_normalization.profiles.repository import (
    NormalizationProfileRepository,
)
from teoria.features.semantic_modeling.ontology.service import OntologyAuthoringService


def profile_result(row):
    return {
        k: str(v)
        if isinstance(v, UUID)
        else v.isoformat()
        if hasattr(v, "isoformat")
        else v
        for k, v in row.items()
        if k != "package"
    }


class NormalizationProfileService:
    def __init__(
        self,
        database_url: str | None = None,
        *,
        repository=None,
        ontology_authoring=None,
    ):
        if repository is None and not database_url:
            raise ValueError("Profile database configuration is required")
        self.repository = repository or NormalizationProfileRepository(database_url)
        self.ontology_authoring = ontology_authoring or OntologyAuthoringService(
            database_url
        )

    async def candidate_context(self, revision_id, *, allow_deprecated=False):
        async with self.repository.transaction() as conn:
            row = await self.repository.get(conn, revision_id)
            if row["status"] != "approved":
                raise ValueError(
                    "candidate comparison requires an approved base profile"
                )
            profile = NormalizationProfile.model_validate(row["content"])
            if checksum(profile) != row["content_checksum"]:
                raise ValueError("profile checksum mismatch")
            snapshot = await self.ontology_authoring.published_artifact(
                profile.ontology.version_id,
                allow_deprecated=allow_deprecated,
                connection=conn,
            )
            if (
                snapshot is None
                or checksum(snapshot["content"]) != snapshot["checksum"]
            ):
                raise ValueError("published ontology artifact unavailable or invalid")
        return profile, snapshot["content"]

    async def candidate_proposals(self, base_revision_id, bundles):
        from teoria.features.goods_normalization.candidates.proposals import (
            propose_candidates,
        )

        profile, ontology = await self.candidate_context(base_revision_id)
        return propose_candidates(bundles, profile, ontology)

    async def create_from_candidates(
        self, base_revision_id, bundles, selections, *, version, actor
    ):
        from teoria.features.goods_normalization.candidates.proposals import (
            draft_from_candidates,
        )

        profile, ontology = await self.candidate_context(base_revision_id)
        draft, proposal_checksum = draft_from_candidates(
            bundles, profile, ontology, selections, version=version
        )
        provenance = json.dumps(
            {
                "source": "candidate_proposals",
                "base_revision_id": str(base_revision_id),
                "proposal_checksum": proposal_checksum,
                "input_checksums": sorted({b.checksum for b in bundles}),
                "selections": [s.model_dump(mode="json") for s in selections],
            },
            sort_keys=True,
        )
        return await self.create(draft, actor=actor, provenance_comment=provenance)

    async def create_from_template(
        self, version_id: UUID, template: dict, *, actor: str
    ):
        row = await self.ontology_authoring.published_artifact(version_id)
        if row is None:
            raise ValueError("template requires a published ontology artifact")
        if checksum(row["content"]) != row["checksum"]:
            raise ValueError("ontology artifact checksum mismatch")
        profile = resolve_profile_template(
            template, row["content"], version_id=version_id
        )
        return await self.create(profile, actor=actor)

    async def create(
        self, profile: NormalizationProfile, *, actor: str, provenance_comment=None
    ):
        async with self.repository.transaction() as conn:
            row = await self.repository.insert(
                conn, profile, actor=actor, digest=checksum(profile)
            )
            await self.repository.record_event(
                conn, row, "created", actor, provenance_comment
            )
        return profile_result(row)

    async def get(self, revision_id: UUID):
        async with self.repository.transaction() as conn:
            return profile_result(await self.repository.get(conn, revision_id))

    async def find_revision(self, profile_key, version):
        async with self.repository.transaction() as conn:
            row = await self.repository.find_revision(conn, profile_key, version)
        return profile_result(row) if row else None

    async def update(
        self, revision_id: UUID, profile: NormalizationProfile, *, actor: str
    ):
        async with self.repository.transaction() as conn:
            current = await self.repository.get(conn, revision_id, lock=True)
            if current["status"] != "draft":
                raise ValueError("only draft profiles may be edited")
            if (profile.profile_key, profile.version) != (
                current["profile_key"],
                current["version"],
            ):
                raise ValueError(
                    "profile identity cannot change; create a new revision"
                )
            row = await self.repository.update(
                conn, revision_id, profile, actor=actor, digest=checksum(profile)
            )
            await self.repository.record_event(conn, row, "updated", actor, None)
        return profile_result(row)

    async def transition(
        self, revision_id: UUID, *, action: str, actor: str, comment=None,
        expected_content_checksum: str | None = None, expected_status: str | None = None
    ):
        transitions = {
            ("draft", "submit"): "in_review",
            ("in_review", "request_changes"): "draft",
            ("in_review", "approve"): "approved",
            ("in_review", "reject"): "rejected",
            ("approved", "deprecate"): "deprecated",
        }
        async with self.repository.transaction() as conn:
            row = await self.repository.get(conn, revision_id, lock=True)
            if ((expected_content_checksum is not None and row["content_checksum"] != expected_content_checksum)
                    or (expected_status is not None and row["status"] != expected_status)):
                raise ValueError("profile changed since review; reload before transitioning")
            status = transitions.get((row["status"], action))
            if status is None:
                raise ValueError("invalid profile transition")
            package = row["package"]
            if action in {"submit", "approve"}:
                profile = NormalizationProfile.model_validate(row["content"])
                if checksum(profile) != row["content_checksum"]:
                    raise ValueError("profile content checksum mismatch")
                snapshot = await self.ontology_authoring.published_artifact(
                    profile.ontology.version_id,
                    expected_checksum=profile.ontology.checksum,
                    connection=conn,
                    lock=True,
                )
                if snapshot is None or snapshot["status"] != "published":
                    raise ValueError("profile requires a published ontology artifact")
                compiled = compile_package(
                    profile,
                    snapshot["content"],
                    revision_id=revision_id,
                    approval_actor=actor,
                )
                if action == "approve":
                    package = compiled.model_dump(mode="json")
            row = await self.repository.set_status(
                conn, revision_id, status=status, package=package, actor=actor
            )
            await self.repository.record_event(conn, row, action, actor, comment)
        return profile_result(row)

    async def export(self, revision_id: UUID) -> NormalizationPackage:
        async with self.repository.transaction() as conn:
            row = await self.repository.get(conn, revision_id)
        if row["status"] != "approved":
            raise ValueError("only approved profiles can be exported")
        package = NormalizationPackage.model_validate(row["package"])
        if package.profile_checksum != row["content_checksum"]:
            raise ValueError("approved profile checksum mismatch")
        return package

    async def audit(self, revision_id: UUID):
        async with self.repository.transaction() as conn:
            await self.repository.get(conn, revision_id)
            rows = await self.repository.audit(conn, revision_id)
        return [
            {
                **dict(r),
                "event_id": str(r["event_id"]),
                "created_at": r["created_at"].isoformat(),
            }
            for r in rows
        ]
