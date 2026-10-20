"""Evaluate frozen metadata selection against independently recorded content review.

No parser or file-name heuristics create content labels here. Unknowns stay unknown.
"""

from collections import Counter, defaultdict
from dataclasses import dataclass
import math

from .attachment_selection import SELECTED_REVIEW_PRIORITIES


@dataclass(frozen=True, slots=True)
class ReviewedAttachment:
    notice_id: str
    attachment_id: str
    priority: str
    content_label: str
    evidence: str = ""
    target_item_match: bool | None = None
    byte_count: int = 0


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _wilson(successes: int, total: int) -> list[float] | None:
    if not total:
        return None
    z = 1.959963984540054
    p = successes / total
    denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    radius = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return [max(0, center - radius), min(1, center + radius)]


def evaluate_selection(
    attachments: list[ReviewedAttachment], *, notice_ids: set[str],
    selected_priorities: frozenset[str] = SELECTED_REVIEW_PRIORITIES,
) -> dict:
    priorities = {"first_review", "additional_review", "manual_review"}
    labels = {"includes_requirements", "no_requirements", "unconfirmed"}
    if not selected_priorities or not selected_priorities.issubset(priorities):
        raise ValueError("invalid selection policy")
    seen = set()
    counts = Counter()
    by_notice = defaultdict(list)
    for a in attachments:
        key = (a.notice_id, a.attachment_id)
        if key in seen or a.notice_id not in notice_ids:
            raise ValueError("duplicate attachment or unexpected notice")
        seen.add(key)
        if a.priority not in priorities or a.content_label not in labels or a.byte_count < 0:
            raise ValueError("invalid review state")
        if a.content_label != "unconfirmed" and not a.evidence.strip():
            raise ValueError("confirmed review requires content evidence")
        selected = a.priority in selected_priorities
        if selected:
            counts["selected_bytes"] += a.byte_count
            counts["selected_files"] += 1
        counts["all_bytes"] += a.byte_count
        by_notice[a.notice_id].append(a)
        if a.content_label == "unconfirmed":
            counts["selected_unknown" if selected else "unselected_unknown"] += 1
        elif a.content_label == "includes_requirements":
            counts["true_positive" if selected else "false_negative"] += 1
        else:
            counts["false_positive" if selected else "true_negative"] += 1

    tp, fp, fn = (counts[k] for k in ("true_positive", "false_positive", "false_negative"))
    us, un = counts["selected_unknown"], counts["unselected_unknown"]
    positive_notices = recovered_notices = complete_notices = 0
    known_positive = known_recovered = definite_misses = 0
    known_positive_recovery_unknown = []
    unknown_notice_ids = []
    for notice_id in sorted(notice_ids):
        rows = by_notice[notice_id]
        observed_target_rows = [a for a in rows if a.content_label == "includes_requirements" and a.target_item_match is True]
        if observed_target_rows:
            known_positive += 1
            recovered = any(a.priority in selected_priorities for a in observed_target_rows)
            known_recovered += recovered
            selected_possible_target = any(
                a.priority in selected_priorities and (
                    a.content_label == "unconfirmed" or (
                        a.content_label == "includes_requirements" and a.target_item_match is None
                    )
                ) for a in rows
            )
            if not recovered:
                if selected_possible_target:
                    known_positive_recovery_unknown.append(notice_id)
                else:
                    definite_misses += 1
        complete = bool(rows) and all(
            a.content_label != "unconfirmed" and (
                a.content_label != "includes_requirements" or type(a.target_item_match) is bool
            ) for a in rows
        )
        if not complete:
            unknown_notice_ids.append(notice_id)
            continue
        complete_notices += 1
        target_rows = [a for a in rows if a.content_label == "includes_requirements" and a.target_item_match]
        positive_notices += bool(target_rows)
        recovered_notices += any(a.priority in selected_priorities for a in target_rows)

    return {
        "notice_count": len(notice_ids), "attachment_count": len(attachments),
        "selected_priorities": sorted(selected_priorities),
        **{k: counts[k] for k in ("true_positive", "false_positive", "false_negative", "true_negative",
                                 "selected_unknown", "unselected_unknown", "selected_files", "selected_bytes", "all_bytes")},
        "precision_on_confirmed": _ratio(tp, tp + fp),
        "recall_on_confirmed": _ratio(tp, tp + fn),
        "precision_bounds_with_unknowns": [
            _ratio(tp, tp + fp + us), _ratio(tp + us, tp + fp + us),
        ],
        "recall_bounds_with_unknowns": [
            _ratio(tp, tp + fn + un), _ratio(tp + us, tp + fn + us),
        ] if tp + fn else None,
        "fully_reviewed_notices": complete_notices,
        "target_positive_notices": positive_notices,
        "target_recovered_notices": recovered_notices,
        "target_notice_recall_on_complete": _ratio(recovered_notices, positive_notices),
        "target_notice_recall_wilson_95": _wilson(recovered_notices, positive_notices),
        "known_target_positive_notices": known_positive,
        "known_target_recovered_notices": known_recovered,
        "definite_missed_target_notices": definite_misses,
        "known_target_recovery_unknown_ids": known_positive_recovery_unknown,
        "known_target_notice_recall_bounds": [
            _ratio(known_recovered, known_positive),
            _ratio(known_positive - definite_misses, known_positive),
        ],
        "known_target_notice_wilson_95": _wilson(known_recovered, known_positive)
        if not known_positive_recovery_unknown else None,
        "unknown_notice_ids": unknown_notice_ids,
        "saved_file_fraction": _ratio(len(attachments) - counts["selected_files"], len(attachments)),
        "saved_byte_fraction": _ratio(counts["all_bytes"] - counts["selected_bytes"], counts["all_bytes"]),
        "population_target_status": "not_established_by_this_sample",
    }
