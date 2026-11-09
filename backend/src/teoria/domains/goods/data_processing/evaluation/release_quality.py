"""Release evidence gate over the existing evaluator, never a second scorer.

Passing covers frozen extraction cases only. Deployment and standard application
require their own integration and environment checks.
"""
from teoria.domains.goods.data_processing.evaluation.scoring import CASE_NAMES, ERROR_NAMES


def check_release_quality(cycle: dict, processor_revision: str) -> dict:
    reasons = []
    def require(condition, code):
        if not condition:
            reasons.append(code)

    require(cycle.get("status") == "finished", "evaluation_not_finished")
    require(cycle.get("purpose") == "extraction_improvement", "improvement_evaluation_required")
    require(cycle.get("comparison", {}).get("decision") == "accepted", "evaluation_not_accepted")
    require(cycle.get("candidate_revision") == processor_revision, "processor_revision_mismatch")
    require(cycle.get("pipeline_tests_exit_code") == 0, "pipeline_tests_not_passed")
    require(cycle.get("cleanup", {}).get("status") == "complete", "evaluation_cleanup_incomplete")
    require(cycle.get("sampling", {}).get("freshness") == "history_checked", "source_history_not_verified")
    require(bool(cycle.get("settings", {}).get("model")), "model_not_configured")
    for split in ("development", "validation", "regression"):
        score = cycle.get("results", {}).get("candidate", {}).get(split, {})
        metrics = score.get("metrics", {})
        require(score.get("case_contract_version") == 2, f"{split}:case_contract_required")
        require(bool(score.get("documents")), f"{split}:documents_required")
        require(sum(metrics.get(k + "_cases_total", 0) for k in CASE_NAMES) > 0,
                f"{split}:frozen_cases_required")
        for kind in CASE_NAMES:
            total = metrics.get(kind + "_cases_total")
            found = metrics.get(kind + "_cases_found")
            require(type(total) is int and type(found) is int and total >= 0 and found == total,
                    f"{split}:{kind}_cases_incomplete")
        for name in ERROR_NAMES:
            require(type(metrics.get(name)) is int and metrics[name] == 0, f"{split}:{name}")
        if split == "validation":
            require(score.get("independent_gold") is True, "validation:human_reviewed_labels_required")
            require(all(not d.get("missing_cases") for d in score.get("documents", [])),
                    "validation:missing_cases")
    return {"status": "passed" if not reasons else "blocked", "reasons": sorted(set(reasons)),
            "scope": "frozen_extraction_cases_only", "deployment_ready": False,
            "remaining_checks": ["standard_application_integration", "storage_and_ui_integration",
                                 "identity_and_permissions", "deployment_and_restore_verification"]}
