"""Controlled source -> approved meaning/profile -> frozen view -> Runtime HTTP -> FormatID.

Synthetic authority fixtures are never applied to the operating authoring database.
"""

import hashlib
import json
import shutil
from copy import deepcopy
from pathlib import Path
from uuid import UUID

import httpx
import pytest
import yaml
from teoria.domains.goods.expression_links.expression_contracts import (
    expression_snapshot,
)
from teoria.domains.goods.normalization.profiles.compiler import compile_package
from teoria.domains.goods.normalization.contracts import checksum
from teoria.domains.goods.runtime import (
    CAPABILITY_ID,
    PROCESSOR_ID,
    RequirementsView,
    compile_requirements_view,
    load_requirements_view,
    requirements_handler,
)
from teoria.platform.ontology.contracts.artifact import (
    RuntimeBundleCompiler,
    RuntimeBundleLoader,
)
from teoria.platform.ontology.contracts.loader import RegistryLoader
from teoria.platform.ontology.contracts.release import publish_registry
from teoria.platform.ontology.runtime.capability.contracts import (
    CapabilityExecutionError,
)
from teoria.platform.ontology.runtime.capability.handlers import CapabilityHandlers
from teoria.platform.ontology.runtime.capability.presentation import (
    serialize_capability_result,
)
from teoria.platform.ontology.runtime.capability.runner import CapabilityRunner

from backend.tests.integration.test_document_api_meanings import memory_case
from backend.tests.integration.test_goods_normalization_contract import uid


@pytest.fixture
def reviewed_inputs():
    _, profile, ontology, corpus, publications, _ = memory_case()
    package = compile_package(
        profile,
        ontology,
        revision_id=UUID(int=900),
        approval_actor="fixture:authenticated-reviewer",
    )
    document = corpus["documents"][0]
    alignment = {
        "documents": [
            {
                "document_id": document["document_id"],
                "source_sha256": document["source"]["sha256"],
                "entities": deepcopy(document["entities"]),
                "attributes": deepcopy(document["attributes"]),
            }
        ]
    }
    sources, mappings = [], []
    source_ids = {}
    for index, entity in enumerate(alignment["documents"][0]["entities"]):
        entry_id = uid(1000 + index)
        source_ids[entity["id"]] = entry_id
        entity["source_term_ref"] = "source_term:" + entry_id
        concept = uid(4) if entity["id"] == "root" else uid(1)
        sources.append(
            {
                "entry_id": entry_id,
                "kind": "item_type",
                "status": "approved",
                "preferred_name": entity["name"],
            }
        )
        mappings.append(
            {
                "mapping_id": uid(2000 + index),
                "source_entry_id": entry_id,
                "ontology_version_id": str(profile.ontology.version_id),
                "target_concept_id": concept,
                "owner_concept_id": None,
                "status": "approved",
                "relation": "equivalent",
                "scope_mode": "classified",
                "classification_code": corpus["classification_code"],
            }
        )
    for index, attribute in enumerate(alignment["documents"][0]["attributes"]):
        entry_id = uid(3000 + index)
        attribute["source_term_ref"] = "source_term:" + entry_id
        sources.append(
            {
                "entry_id": entry_id,
                "kind": "characteristic",
                "owner_entry_id": source_ids[attribute["subject_ids"][0]],
                "status": "approved",
                "preferred_name": attribute["property_key"],
            }
        )
        mappings.append(
            {
                "mapping_id": uid(4000 + index),
                "source_entry_id": entry_id,
                "ontology_version_id": str(profile.ontology.version_id),
                "target_concept_id": uid(3)
                if attribute["property_key"] == "quantity"
                else uid(2),
                "owner_concept_id": uid(1),
                "status": "approved",
                "relation": "equivalent",
                "scope_mode": "classified",
                "classification_code": corpus["classification_code"],
            }
        )
    snapshot = expression_snapshot(
        [{"ontology": profile.ontology.model_dump(mode="json"), "content": ontology}],
        mappings,
        sources,
    )
    return dict(
        version="2026.11.10.1",
        run_id="memory_fixture",
        corpus=corpus,
        alignment=alignment,
        package=package,
        snapshot=snapshot,
        extraction_ref={"uri": "file:///controlled/extracted.json", "sha256": "a" * 64},
        alignment_ref={"uri": "file:///controlled/alignment.json", "sha256": "b" * 64},
        receipt_ref={
            "uri": "file:///controlled/execution_receipt.json",
            "sha256": "c" * 64,
        },
    ), publications


def write_view(tmp_path, inputs):
    view = compile_requirements_view(**inputs)
    directory = tmp_path / "views" / view.version
    directory.mkdir(parents=True)
    path = directory / "view.json"
    path.write_text(view.model_dump_json())
    return view, path, hashlib.sha256(path.read_bytes()).hexdigest()


def test_compiler_preserves_module_value_scope_and_review_provenance(
    reviewed_inputs, tmp_path
):
    inputs, publications = reviewed_inputs
    original = deepcopy(inputs["corpus"])
    view, path, digest = write_view(tmp_path, inputs)
    restored = load_requirements_view(path, digest, publications)
    observation = next(
        o for o in restored.documents[0].observations if o.scope == "per_module"
    )
    assert observation.value["decimal"] == "32" and observation.value["unit"] == "GB"
    assert observation.value_raw == "32" and observation.unit_raw == "GB"
    assert (
        observation.information_kind == "requirement" and observation.operator == "eq"
    )
    assert observation.source["property_connection"]["mapping_ids"] == [uid(4001)]
    assert observation.source["subject_connections"][0]["mapping_ids"] == [uid(2002)]
    assert (
        observation.source["expression_snapshot_checksum"]
        == view.expression_snapshot_checksum
    )
    assert inputs["corpus"] == original
    assert view.ontology == inputs["package"].profile.ontology


@pytest.mark.parametrize(
    "change",
    [
        "draft_link",
        "related_link",
        "changed_value",
        "changed_source",
        "stale_publication",
    ],
)
def test_compiler_does_not_promote_unreviewed_or_changed_inputs(
    reviewed_inputs, change
):
    inputs, _ = reviewed_inputs
    if change in {"draft_link", "related_link"}:
        snapshot = inputs["snapshot"]
        mappings = deepcopy(snapshot.mappings)
        for m in mappings:
            m["status"] = "draft" if change == "draft_link" else "approved"
            if change == "related_link":
                m["relation"] = "related"
        inputs["snapshot"] = expression_snapshot(
            snapshot.ontologies, mappings, snapshot.sources
        )
    if change == "changed_value":
        inputs["alignment"]["documents"][0]["attributes"][0]["value_raw"] = "999"
    if change == "changed_source":
        inputs["alignment"]["documents"][0]["source_sha256"] = "f" * 64
    if change == "stale_publication":
        inputs["package"] = inputs["package"].model_copy(
            update={
                "profile": inputs["package"].profile.model_copy(
                    update={
                        "ontology": inputs["package"].profile.ontology.model_copy(
                            update={"version": "other"}
                        )
                    }
                )
            }
        )
    with pytest.raises(ValueError):
        compile_requirements_view(**inputs)


def test_view_loader_rejects_tampering_and_an_unrelated_bundle(
    reviewed_inputs, tmp_path
):
    inputs, publications = reviewed_inputs
    _, path, digest = write_view(tmp_path, inputs)
    with pytest.raises(ValueError, match="not_in_runtime_bundle"):
        load_requirements_view(path, digest, [])
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="file_checksum_mismatch"):
        load_requirements_view(path, digest, publications)


async def test_registered_query_returns_only_frozen_observations_with_pagination(
    reviewed_inputs, tmp_path
):
    inputs, publications = reviewed_inputs
    view, _, _ = write_view(tmp_path, inputs)
    handlers = CapabilityHandlers()
    handlers.register_processor(PROCESSOR_ID, requirements_handler(view))
    root = tmp_path / "registry"
    shutil.copytree("backend/contracts/runtime", root)
    cap_path = root / "domains/goods/capabilities/get_goods_document_requirements.yaml"
    cap = yaml.safe_load(cap_path.read_text())
    cap["capability"]["lifecycle"]["status"] = "active"
    cap_path.write_text(yaml.safe_dump(cap))
    catalog = RegistryLoader(root).load()
    runner = CapabilityRunner(handlers=handlers)
    args = {"run_id": "memory_fixture", "document_id": "doc", "offset": 0, "limit": 1}
    result = await runner.run(catalog, CAPABILITY_ID, args)
    assert len(result.objects[0].semantic_observations) == 1
    assert result.objects[0].properties["total"] == 4
    assert result.outcome["package_checksum"] == inputs["package"].checksum
    later = await runner.run(catalog, CAPABILITY_ID, {**args, "offset": 1})
    assert later.objects[0].semantic_observations[0].scope == "per_module"
    assert (
        serialize_capability_result(later)["objects"][0]["semantic_observations"][0][
            "value"
        ]["decimal"]
        == "32"
    )
    with pytest.raises(CapabilityExecutionError, match="no published requirements"):
        await runner.run(catalog, CAPABILITY_ID, {**args, "run_id": "unpublished"})


async def test_compiled_bundle_runtime_http_and_formatid_preserve_meaning_and_actor(
    reviewed_inputs, tmp_path
):
    from fastapi import FastAPI
    from teoria.apps.formatid.router import create_processing_workspace_router
    from teoria.entrypoints.runtime_api import create_runtime_app
    from teoria.platform.access_control.auth import AdminAuthorizer
    from teoria.platform.ontology.runtime.context.runtime_client import (
        ContextRuntimeClient,
    )
    from teoria.settings import Settings

    inputs, publications = reviewed_inputs
    view, path, digest = write_view(tmp_path, inputs)
    root = tmp_path / "registry"
    shutil.copytree("backend/contracts/runtime", root)
    cap_path = root / "domains/goods/capabilities/get_goods_document_requirements.yaml"
    definition = yaml.safe_load(cap_path.read_text())
    definition["capability"]["lifecycle"]["status"] = (
        "active"  # Isolated synthetic release only.
    )
    cap_path.write_text(yaml.safe_dump(definition))
    publish_registry(
        root,
        version="2026.11.10.1",
        output=tmp_path / "registries",
        git_commit="controlled-integration-fixture",
    )
    RuntimeBundleCompiler().compile(
        tmp_path / "registries/2026.11.10.1",
        ontologies=publications,
        bindings=[],
        output=tmp_path / "runtime",
        version="2026.11.10.1",
    )
    runtime = create_runtime_app(
        settings=Settings(
            environment="test",
            runtime_api_token="runtime-token",
            runtime_artifact_path=tmp_path / "runtime/2026.11.10.1",
            goods_runtime_view_path=path,
            goods_runtime_view_sha256=digest,
            policy_mode="disabled",
        )
    )
    headers = []
    runtime_actors = []
    @runtime.middleware("http")
    async def record_authenticated_forwarding(request, call_next):
        if request.url.path.endswith(":execute"):
            runtime_actors.append(request.headers.get("X-Teoria-Actor"))
        return await call_next(request)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=runtime), base_url="http://runtime"
    ) as http:
        assert (await http.get("/v1/capabilities")).status_code == 401
        discovered = await http.get(
            "/v1/capabilities", headers={"Authorization": "Bearer runtime-token"}
        )
        assert discovered.json()["capabilities"][0]["id"] == CAPABILITY_ID
        invalid = await http.post(
            f"/v1/capabilities/{CAPABILITY_ID}:execute",
            headers={"Authorization": "Bearer runtime-token"},
            json={
                "inputs": {
                    "run_id": "memory_fixture",
                    "document_id": "doc",
                    "limit": 101,
                }
            },
        )
        assert invalid.status_code == 422
        client = ContextRuntimeClient("http://runtime", "runtime-token", client=http)

        async def execute(principal, arguments):
            headers.append(principal.actor)
            return await client.execute(
                CAPABILITY_ID,
                arguments,
                actor=principal.actor,
                roles=principal.roles,
                service="formatid",
            )

        app = FastAPI()
        app.include_router(
            create_processing_workspace_router(
                authorizer=AdminAuthorizer(
                    Settings(
                        admin_auth_mode="bearer",
                        admin_api_token="admin-token",
                        admin_api_actor="user:reviewer",
                    )
                ),
                database_url=None,
                runtime_query=execute,
            )
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://admin"
        ) as admin:
            endpoint = "/v1/admin/specification-processing/runtime-requirements?run_id=memory_fixture&document_id=doc&offset=1&limit=1"
            assert (await admin.get(endpoint)).status_code == 401
            result = await admin.get(
                endpoint, headers={"Authorization": "Bearer admin-token"}
            )
        assert result.status_code == 200, result.text
        body = result.json()
        observation = body["objects"][0]["semantic_observations"][0]
        assert (
            observation["value"]["decimal"] == "32"
            and observation["scope"] == "per_module"
        )
        assert observation["source"]["property_connection"]["mapping_ids"] == [
            uid(4001)
        ]
        assert body["runtime_artifact"]["version"] == "2026.11.10.1"
        assert body["outcome"]["package_checksum"] == inputs["package"].checksum
        assert headers == ["user:reviewer"]
        assert runtime_actors[-1] == "user:reviewer"
    await runtime.state.runtime_services.runner.cache.aclose()


async def test_export_reads_approved_owner_endpoints_and_creates_an_immutable_view(
    reviewed_inputs, tmp_path
):
    from teoria.domains.goods.authoring_client import GoodsAuthoringClient
    from teoria.domains.goods.runtime import prepare_requirements_view

    inputs, _ = reviewed_inputs
    extraction = tmp_path / "extracted.json"
    extraction.write_text(json.dumps(inputs["corpus"]))
    ref = {
        "uri": extraction.as_uri(),
        "sha256": hashlib.sha256(extraction.read_bytes()).hexdigest(),
    }
    alignment = tmp_path / "alignment.json"
    alignment.write_text(json.dumps({**inputs["alignment"], "extraction_ref": ref}))
    manifest = {
        "version": inputs["version"],
        "run_id": inputs["run_id"],
        "profile_revision_id": str(inputs["package"].profile_revision_id),
        "extraction": ref,
        "alignment": {
            "uri": alignment.as_uri(),
            "sha256": hashlib.sha256(alignment.read_bytes()).hexdigest(),
        },
    }
    receipt = tmp_path / "execution_receipt.json"
    receipt.write_text(
        json.dumps(
            {
                "run_id": inputs["run_id"],
                "artifacts": [manifest["extraction"], manifest["alignment"]],
                "sources": [
                    {"document_id": d["document_id"], "sha256": d["source"]["sha256"]}
                    for d in inputs["corpus"]["documents"]
                ],
            }
        )
    )
    manifest["execution_receipt"] = {
        "uri": receipt.as_uri(),
        "sha256": hashlib.sha256(receipt.read_bytes()).hexdigest(),
    }
    calls = []

    def respond(request):
        assert request.headers["Authorization"] == "Bearer authoring-test-token"
        calls.append(request.url.path)
        if request.url.path.endswith("/package"):
            return httpx.Response(200, json=inputs["package"].model_dump(mode="json"))
        if request.url.path.endswith("/snapshot"):
            return httpx.Response(200, json=inputs["snapshot"].model_dump(mode="json"))
        return httpx.Response(
            200,
            json={
                "ontology": inputs["package"].profile.ontology.model_dump(mode="json"),
                "content": inputs["snapshot"].ontologies[0]["content"],
            },
        )

    async with GoodsAuthoringClient(
        base_url="http://admin",
        token="authoring-test-token",
        transport=httpx.MockTransport(respond),
    ) as api:
        result = await prepare_requirements_view(
            manifest, tmp_path / "views", authoring_client=api
        )
        repeated = await prepare_requirements_view(
            manifest, tmp_path / "views", authoring_client=api
        )
    assert (
        result == repeated
        and result["observations"] == 4
        and result["deployment_ready"] is False
    )
    assert any(path.endswith("/package") for path in calls) and any(
        path.endswith("/publication") for path in calls
    )
    assert (tmp_path / "views" / inputs["version"] / "view.json").exists()


def interpretation_inputs():
    from backend.tests.domains.goods.normalization.test_interpretations import meaning_case
    request, result, package, publication, approval = meaning_case()
    document = result['extracted']['documents'][0]
    corpus = {'classification_code': None, 'documents': [deepcopy(document)]}
    alignment = {'documents': [{'document_id': document['document_id'], 'source_sha256': request.source_sha256,
        'entities': deepcopy(document['entities']), 'attributes': deepcopy(document['attributes'])}]}
    snapshot = expression_snapshot([publication], [], [])
    return dict(version='2026.11.10.2', run_id='interpreted_fixture', corpus=corpus, alignment=alignment,
        package=package, snapshot=snapshot,
        extraction_ref={'uri': 'file:///fixture/extracted.json', 'sha256': 'a'*64},
        alignment_ref={'uri': 'file:///fixture/alignment.json', 'sha256': 'b'*64},
        receipt_ref={'uri': 'file:///fixture/execution_receipt.json', 'sha256': 'c'*64},
        interpretations=[{'approval': approval, 'source_result': result}])


async def test_runtime_keeps_approved_owner_scope_and_composition_quantity_separate(tmp_path):
    inputs = interpretation_inputs()
    original = deepcopy(inputs['corpus'])
    view = compile_requirements_view(**inputs)
    assert inputs['corpus'] == original
    document, = view.documents
    assert len(document.observations) == 3 and len(document.compositions) == 1
    by_id = {o.source['attribute_id']: o for o in document.observations}
    assert by_id['limit'].scope == 'per_socket'
    assert by_id['count'].source['original_subject_ids'] == ['slots']
    assert 'quantity' not in by_id
    result = await requirements_handler(view)(None, None, CAPABILITY_ID,
        {'run_id': inputs['run_id'], 'document_id': 'd'})
    assert result.outcome['compositions'][0]['quantity']['value'] == '2'
    assert result.outcome['interpretation_approval_ids'] == [str(view.interpretation_approvals[0].revision_id)]
    raw = view.model_dump(mode='json')
    assert RequirementsView.model_validate(raw).checksum == view.checksum
    # A file checksum alone does not make unreferenced interpretation provenance valid.
    raw['interpretation_approvals'] = []
    raw['checksum'] = checksum({k:v for k,v in raw.items() if k!='checksum'})
    with pytest.raises(ValueError, match='approval_required'):
        RequirementsView.model_validate(raw)


@pytest.mark.parametrize('change', ['overlap', 'different_source_document', 'unapproved'])
def test_view_rejects_overlapping_or_unrelated_interpretation_exports(change):
    inputs = interpretation_inputs()
    if change=='overlap': inputs['interpretations'] *= 2
    elif change=='different_source_document': inputs['interpretations'][0]['source_result']['extracted']['documents'][0]['attributes'][0]['value_raw']='64'
    else:
        body = inputs['interpretations'][0]['approval'].model_dump(mode='json')
        body['status'] = 'draft'
        inputs['interpretations'][0]['approval'] = body
    with pytest.raises(ValueError): compile_requirements_view(**inputs)


def test_legacy_view_without_interpretation_fields_remains_loadable(reviewed_inputs):
    inputs,_=reviewed_inputs
    view=compile_requirements_view(**inputs).model_dump(mode='json')
    view.pop('interpretation_approvals')
    for document in view['documents']: document.pop('compositions')
    view['checksum']=checksum({k:v for k,v in view.items() if k!='checksum'})
    assert RequirementsView.model_validate(view).documents[0].compositions==[]


async def test_view_preparation_fetches_current_approval_and_reads_its_verified_result(tmp_path):
    from unittest.mock import AsyncMock
    from teoria.domains.goods.runtime import prepare_requirements_view
    from teoria.domains.goods.normalization.application.meaning_application import ApprovedInterpretation
    inputs=interpretation_inputs()
    def write(name,value):
        path=tmp_path/name;raw=json.dumps(value).encode();path.write_bytes(raw)
        return {'uri':path.as_uri(),'sha256':hashlib.sha256(raw).hexdigest()}
    result_ref=write('result.json',inputs['interpretations'][0]['source_result'])
    body=inputs['interpretations'][0]['approval'].model_dump(mode='json',exclude={'checksum'})
    body['request']['result']=result_ref
    approval=ApprovedInterpretation(**body,checksum=checksum(body))
    extraction=write('extracted.json',inputs['corpus'])
    alignment=write('alignment.json',{**inputs['alignment'],'extraction_ref':extraction})
    receipt=write('receipt.json',{'run_id':inputs['run_id'],'artifacts':[extraction,alignment],
        'sources':[{'document_id':'d','sha256':approval.request.source_sha256}]})
    manifest=dict(version=inputs['version'],run_id=inputs['run_id'],profile_revision_id=str(inputs['package'].profile_revision_id),
        extraction=extraction,alignment=alignment,execution_receipt=receipt,
        interpretation_revision_ids=[str(approval.revision_id)])
    api=AsyncMock();api.package.return_value=inputs['package'].model_dump_json().encode()
    api.expression_snapshot.return_value=inputs['snapshot']
    api.ontology_publication.return_value=inputs['snapshot'].ontologies[0]
    api.interpretation_approval.return_value=approval.model_dump(mode='json')
    exported=await prepare_requirements_view(manifest,tmp_path/'views',authoring_client=api)
    assert exported['observations']==3
    api.interpretation_approval.assert_awaited_once_with(str(approval.revision_id))
    view=RequirementsView.model_validate_json((tmp_path/'views'/inputs['version']/'view.json').read_bytes())
    assert len(view.documents[0].compositions)==1
    # A saved approval does not override an Admin refusal on a later build.
    api.interpretation_approval.side_effect=RuntimeError('approval no longer active')
    with pytest.raises(RuntimeError,match='no longer active'):
        await prepare_requirements_view({**manifest,'version':'2026.11.10.3'},tmp_path/'views',authoring_client=api)
    assert not (tmp_path/'views/2026.11.10.3/view.json').exists()
