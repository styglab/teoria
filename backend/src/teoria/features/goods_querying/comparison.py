"""Compare explicit, uniquely aligned requirements without guessing product equivalence."""

from collections import defaultdict
from decimal import Decimal


ALIGNMENT = (
    "subject_concept_id",
    "property_concept_id",
    "role",
    "semantic_scope",
    "unit",
)
VERSION = (
    "ontology_version_id",
    "ontology_checksum",
    "profile_revision_id",
    "package_checksum",
)


def compare_requirements(left: list[dict], right: list[dict]) -> dict:
    groups = []
    for rows in (left, right):
        grouped = defaultdict(list)
        for row in rows:
            grouped[tuple(row[key] for key in ALIGNMENT)].append(row)
        groups.append(grouped)
    comparisons = []
    for key in sorted(groups[0].keys() | groups[1].keys()):
        a, b = groups[0].get(key, []), groups[1].get(key, [])
        item = {"alignment": dict(zip(ALIGNMENT, key)), "left": a, "right": b}
        if not a or not b:
            item.update(status="not_comparable", reason="missing_aligned_requirement")
        elif len(a) != 1 or len(b) != 1:
            item.update(
                status="not_comparable", reason="ambiguous_subject_or_requirement"
            )
        elif any(a[0][field] != b[0][field] for field in VERSION):
            item.update(
                status="not_comparable", reason="different_semantic_or_profile_version"
            )
        elif (
            a[0]["operator"] != b[0]["operator"]
            or a[0]["qualifiers_raw"] != b[0]["qualifiers_raw"]
        ):
            item.update(
                status="not_comparable", reason="different_predicate_or_qualifiers"
            )
        else:
            delta = Decimal(str(b[0]["value_decimal"])) - Decimal(
                str(a[0]["value_decimal"])
            )
            item.update(
                status="equal" if delta == 0 else "different",
                right_minus_left=str(delta),
            )
        comparisons.append(item)
    return {
        "scope": "technical_requirements_only",
        "comparisons": comparisons,
        "comparable_count": sum(i["status"] != "not_comparable" for i in comparisons),
        "not_comparable_count": sum(
            i["status"] == "not_comparable" for i in comparisons
        ),
    }
