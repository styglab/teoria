import pytest

from teoria_pipelines.domains.public_procurement.specification_intelligence.search_evaluation import save_json, sha256
from teoria_pipelines.domains.public_procurement.specification_intelligence.search_experiment import predict, verify_corpus
from teoria_pipelines.domains.public_procurement.specification_intelligence.search_semantic_review import review_names


async def test_retrieval_cannot_synthesize_a_fact_that_was_not_extracted(tmp_path):
    class Runner:
        async def generate(self, instruction, context, output):
            if output.name == "facts.json":
                return {"facts": [{"value": "128"}]}
            return {"answers": [{"question_id": "q1", "answer": {"value": "256"}}]}

    result = await predict({}, [], Runner(), tmp_path)
    assert result["answers"][0]["answer"] == {"provenance_error": "answer_not_in_extracted_facts"}


def test_source_changes_after_freeze_are_detected(tmp_path):
    source = tmp_path / "source.json"
    save_json(source, {"text": "memory 128GB"})
    save_json(tmp_path / "corpus_freeze.json", {source.name: sha256(source)})
    verify_corpus(tmp_path)
    save_json(source, {"text": "memory 256GB"})
    with pytest.raises(ValueError, match="frozen corpus changed"):
        verify_corpus(tmp_path)


async def test_semantic_judge_cannot_omit_cases(tmp_path):
    class Runner:
        async def generate(self, *args):
            return {"matches": []}

    with pytest.raises(ValueError, match="omitted"):
        await review_names([{"case_id": "server_a/q1"}], Runner(), tmp_path / "grade.json")


async def test_semantic_judge_boolean_contract_does_not_coerce_strings(tmp_path):
    class Runner:
        async def generate(self, *args):
            return {"matches": [{"case_id": "server_a/q1", "owner_equivalent": "false", "attribute_equivalent": True}]}

    with pytest.raises(ValueError, match="boolean"):
        await review_names([{"case_id": "server_a/q1"}], Runner(), tmp_path / "grade.json")


async def test_dictionary_search_uses_source_review_and_keeps_answer_provenance(tmp_path):
    fact = {"owner": "server", "attribute": "ram_size", "value": "128", "unit": "GB", "operator": "eq",
            "configuration": "installed", "aggregation": "total", "quote": "RAM 128GB"}
    draft = {"observation_groups": [{"group_id": "g1", "attribute": "ram_size", "unit": "GB",
              "configuration": "installed", "aggregation": "total"}],
             "properties": [{"property_id": "memory_capacity", "aliases": [], "source_groups": ["g1"]}]}
    calls = []

    class Runner:
        async def generate(self, instruction, context, output):
            calls.append(output.name)
            if output.name in {"facts.json", "reviewed_facts.json"}:
                assert "questions" not in context
                return {"facts": [fact]}
            canonical = context["facts"]["facts"][0]
            assert canonical["attribute"] == "memory_capacity"
            return {"answers": [{"question_id": "q1", "answer": canonical}]}

    result = await predict({"text": "RAM 128GB"}, [{"question_id": "q1", "question": "메모리는?"}],
                           Runner(), tmp_path, dictionary=draft)
    assert result["answers"][0]["answer"]["value"] == "128"
    assert calls == ["facts.json", "reviewed_facts.json", "answers.json"]
