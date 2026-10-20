import pytest

from teoria_pipelines.domains.public_procurement.specification_intelligence.search_dictionary import build_dictionary, canonicalize_facts
from teoria_pipelines.domains.public_procurement.specification_intelligence.search_evaluation import save_json


def create_observations(root):
    fact = {"owner": "server_a", "attribute": "memory_capacity", "value": "256", "unit": "GB",
            "operator": "ge", "configuration": "installed", "aggregation": "total", "quote": "RAM 256GB 이상"}
    save_json(root / "sources/development/dev.json", {"text": fact["quote"]})
    save_json(root / "predictions/baseline/development/dev/facts.json", {"facts": [fact, {**fact, "value": "56"}]})
    save_json(root / "predictions/baseline/validation/hidden/facts.json", {"facts": [{**fact, "attribute": "holdout_only"}]})


async def test_dictionary_uses_only_development_and_rejects_ungrounded_values(tmp_path):
    create_observations(tmp_path)

    class Runner:
        async def generate(self, instruction, context, output):
            assert len(context["source_groups"]) == 1
            group = context["source_groups"][0]
            assert group["documents"] == ["dev"]
            assert group["attribute"] == "memory_capacity"
            return {"properties": [{"property_id": "memory_capacity", "definition": "Memory capacity",
                    "dimension": "data_capacity", "aliases": [], "source_groups": [group["group_id"]]}], "held_groups": []}

    result = await build_dictionary(tmp_path, "baseline", Runner())
    assert result["status"] == "suggestion; unapproved"
    assert len(result["invalid_observations"]) == 1
    assert result["invalid_observations"][0]["reason"] == "ungrounded_fact"


async def test_dictionary_rejects_unmapped_observation_groups(tmp_path):
    create_observations(tmp_path)

    class Runner:
        async def generate(self, *args):
            return {"properties": [], "held_groups": []}

    with pytest.raises(ValueError, match="cover each development group"):
        await build_dictionary(tmp_path, "baseline", Runner())


def test_dictionary_normalization_preserves_scope_and_holds_ambiguous_aliases():
    draft = {"observation_groups": [
        {"group_id": "g1", "attribute": "ram_size", "unit": "GB", "configuration": "installed", "aggregation": "total"},
        {"group_id": "g2", "attribute": "gpu_size", "unit": "GB", "configuration": "installed", "aggregation": "per_instance"},
    ], "properties": [
        {"property_id": "memory_capacity", "aliases": ["capacity"], "source_groups": ["g1"]},
        {"property_id": "gpu_memory_capacity", "aliases": ["capacity"], "source_groups": ["g2"]},
    ]}
    fact = {"owner": "server_a", "attribute": "ram_size", "value": "256", "unit": "GB", "operator": "ge",
            "configuration": "installed", "aggregation": "total", "quote": "RAM 256GB 이상"}
    normalized, mappings = canonicalize_facts({"facts": [fact, {**fact, "attribute": "capacity"},
                                                        {**fact, "attribute": "new_property"}]}, draft)
    assert normalized["facts"][0] == {**fact, "attribute": "memory_capacity"}
    assert fact["attribute"] == "ram_size"
    assert [m["status"] for m in mappings] == ["proposed_mapping", "ambiguous", "unmapped"]
