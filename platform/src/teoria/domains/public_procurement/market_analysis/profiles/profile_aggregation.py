from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from ..field_identity import _normalized_category, _procurement_field_identity
from ..related_projects.similarity import (
    number as _number,
)
from ..related_projects.similarity import (
    primary_project_type as _primary_project_type,
)
from ..related_projects.similarity import (
    project_type_label as _project_type_label,
)
from ..related_projects.similarity import (
    work_type_label as _work_type_label,
)


def _amount_completeness(statuses: list[str]) -> str:
    if not statuses or all(status == "unknown" for status in statuses):
        return "unknown"
    if all(status == "complete" for status in statuses):
        return "complete"
    return "partial"


def _filter_profile_rows(
    rows: list[dict[str, Any]],
    *,
    large_category: str | None,
    middle_category: str | None,
    field_code: str | None,
    work_type: str | None,
) -> list[dict[str, Any]]:
    filtered = []
    for row in rows:
        if work_type and str(row.get("work_type") or "unknown") != work_type:
            continue
        field_identity = _procurement_field_identity(row)
        if large_category or middle_category or field_code:
            if large_category == "미분류":
                if field_identity is not None or middle_category or field_code:
                    continue
                filtered.append(row)
                continue
            if field_identity is None:
                continue
            if (
                large_category
                and _normalized_category(field_identity.get("large_category"))
                != large_category
            ):
                continue
            if (
                middle_category
                and _normalized_category(field_identity.get("middle_category"))
                != middle_category
            ):
                continue
            if field_code and str(field_identity.get("code") or "") != field_code:
                continue
        filtered.append(row)
    return filtered


def _contract_project_key(row: dict[str, Any]) -> tuple[str, str, str, str]:
    """Identify one logical contract relationship independently of its versions."""
    event_key = str(row.get("event_key") or "").strip()
    notice_id = str(row.get("bid_notice_id") or "").strip()
    contract_event_id = event_key or notice_id
    return (
        str(row.get("organization_code") or ""),
        str(row.get("company_number") or ""),
        str(row.get("work_type") or "unknown"),
        contract_event_id,
    )


def _collapse_profile_contract_versions(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Keep the latest contract version and retain the raw version count."""
    contracts: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
    result = []
    for row in rows:
        if row.get("activity_type") != "contract":
            result.append(row)
            continue
        contracts.setdefault(_contract_project_key(row), []).append(row)
    for versions in contracts.values():
        latest = max(
            versions,
            key=lambda row: (
                row.get("latest_contract_version_date")
                or row.get("activity_date")
                or date.min
            ),
        )
        collapsed = dict(latest)
        first_contract_dates = [
            (
                row["first_contract_date"]
                if "first_contract_date" in row
                else row.get("activity_date")
            )
            for row in versions
            if (
                row.get("first_contract_date") is not None
                or (
                    "first_contract_date" not in row
                    and row.get("activity_date") is not None
                )
            )
        ]
        first_contract_date = (
            min(first_contract_dates) if first_contract_dates else None
        )
        collapsed["first_contract_date"] = first_contract_date
        collapsed["activity_date"] = first_contract_date
        collapsed["attribution_date_basis"] = "first_contract_date"
        collapsed["contract_version_count"] = sum(
            int(row.get("contract_version_count") or 1) for row in versions
        )
        version_dates = {
            value
            for row in versions
            for value in (
                row.get("contract_version_dates")
                or [row.get("latest_contract_version_date")]
            )
            if value
        }
        collapsed["contract_version_dates"] = sorted(version_dates)
        result.append(collapsed)
    return result


def _drilldown_field_distribution(
    fields: list[dict[str, Any]],
    *,
    large_category: str | None,
    middle_category: str | None,
    field_code: str | None,
    work_type: str | None,
) -> tuple[str, list[dict[str, Any]]]:
    if large_category == "미분류":
        return "unclassified", fields
    if work_type == "construction":
        return ("detail" if field_code else "construction_field"), fields
    if work_type == "goods":
        return ("detail" if field_code else "field"), fields
    if field_code:
        return "detail", fields
    if middle_category:
        return "field", fields
    group_property = "middle_category" if large_category else "large_category"
    level = "middle" if large_category else "large"
    grouped: dict[tuple[str, str | None], dict[str, Any]] = {}
    for field in fields:
        category = _normalized_category(field.get(group_property)) or "미분류"
        field_work_types = list(field.get("work_types") or [])
        unclassified_work_type = (
            field_work_types[0]
            if category == "미분류" and len(field_work_types) == 1
            else None
        )
        group_key = (category, unclassified_work_type)
        item = grouped.setdefault(
            group_key,
            {
                group_property: category,
                "event_count": 0,
                "participation_count": 0,
                "award_event_count": 0,
                "result_confirmed_participation_count": 0,
                "successful_participation_count": 0,
                "contract_event_count": 0,
                "attributed_contract_amount": Decimal("0"),
                "work_types": set(),
            },
        )
        if category == "미분류":
            item.update(
                {
                    "field_code": None,
                    "field_name": None,
                    "middle_category": None,
                    "classification_source": "unclassified",
                }
            )
        for count_field in (
            "event_count",
            "participation_count",
            "award_event_count",
            "contract_event_count",
            "result_confirmed_participation_count",
            "successful_participation_count",
        ):
            item[count_field] += int(field.get(count_field) or 0)
        item["attributed_contract_amount"] += Decimal(
            str(field.get("attributed_contract_amount") or 0)
        )
        item["work_types"].update(field.get("work_types") or [])
    total_amount = sum(
        (item["attributed_contract_amount"] for item in grouped.values()), Decimal("0")
    )
    distribution = []
    for item in grouped.values():
        amount = item["attributed_contract_amount"]
        item["attributed_contract_amount"] = _number(amount)
        item["amount_share"] = (
            round(float(amount / total_amount), 6) if total_amount else None
        )
        item["award_success_rate"] = (
            round(
                item["successful_participation_count"]
                / item["result_confirmed_participation_count"],
                6,
            )
            if item["result_confirmed_participation_count"]
            else None
        )
        item["work_types"] = sorted(item["work_types"])
        distribution.append(item)
    distribution.sort(key=lambda item: item["event_count"], reverse=True)
    return level, distribution


def _profile_aggregate(
    rows: list[dict[str, Any]],
    *,
    relationship_dimension: str,
    require_contract_relationship: bool = False,
    notice_rows: list[dict[str, Any]] | None = None,
    period_from: date | None = None,
    period_to: date | None = None,
) -> tuple[
    dict[str, Any],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    key_field = (
        "company_number" if relationship_dimension == "company" else "organization_code"
    )
    name_field = (
        "company_name" if relationship_dimension == "company" else "organization_name"
    )
    relationships: dict[str, dict[str, Any]] = {}
    yearly: dict[int, dict[str, Any]] = {}
    field_totals: dict[str, dict[str, Any]] = {}
    project_type_totals: dict[str, dict[str, Any]] = {}
    work_type_totals: dict[str, dict[str, Any]] = {}
    notice_dates: dict[str, date] = {}
    classified_notice_ids: set[str] = set()
    participant_event_keys: set[tuple[str, str]] = set()
    confirmed_participant_event_keys: set[tuple[str, str]] = set()
    successful_participant_event_keys: set[tuple[str, str]] = set()
    award_event_keys: set[str] = set()
    contract_event_keys: set[str] = set()
    project_keys: set[tuple[str, str]] = set()
    contract_version_count = 0
    companies = set()
    organizations = set()
    total_amount = Decimal("0")
    amount_statuses: list[str] = []

    def year_bucket(value: date) -> dict[str, Any]:
        return yearly.setdefault(
            value.year,
            {
                "year": value.year,
                "notice_ids": set(),
                "company_ids": set(),
                "participation_keys": set(),
                "confirmed_participation_keys": set(),
                "successful_participation_keys": set(),
                "award_event_keys": set(),
                "contract_event_keys": set(),
                "attributed_contract_amount": Decimal("0"),
                "amount_statuses": [],
            },
        )

    def register_notice(row: dict[str, Any]) -> None:
        notice_id = str(row.get("bid_notice_id") or "").strip()
        published = row.get("notice_published_date")
        if isinstance(published, datetime):
            published = published.date()
        if not notice_id or not isinstance(published, date):
            return
        if period_from is not None and published < period_from:
            return
        if period_to is not None and published >= period_to:
            return
        current = notice_dates.get(notice_id)
        notice_dates[notice_id] = min(current, published) if current else published
        if _procurement_field_identity(row):
            classified_notice_ids.add(notice_id)

    for notice_row in notice_rows or []:
        register_notice(notice_row)

    for row in rows:
        key = str(row.get(key_field) or "")
        if not key:
            continue
        activity_type = str(row["activity_type"])
        activity_date = row["activity_date"]
        amount = row.get("attributed_contract_amount")
        completeness = str(row.get("amount_completeness") or "unknown")
        work_type = str(row.get("work_type") or "unknown")
        relationship = relationships.setdefault(
            key,
            {
                key_field: key,
                name_field: row.get(name_field),
                "participation_count": 0,
                "award_event_count": 0,
                "result_confirmed_participation_count": 0,
                "successful_participation_count": 0,
                "contract_event_count": 0,
                "contract_version_count": 0,
                "project_keys": set(),
                "total_attributed_contract_amount": Decimal("0"),
                "amount_statuses": [],
                "dates": [],
                "contract_dates": [],
                "years": set(),
                "yearly": {},
                "fields": {},
                "project_types": {},
                "representative_notices": [],
            },
        )
        if row.get(name_field):
            relationship[name_field] = row[name_field]
        count_field = {
            "participation": "participation_count",
            "award": "award_event_count",
            "contract": "contract_event_count",
        }[activity_type]
        relationship[count_field] += 1
        relationship["project_keys"].add(str(row["bid_notice_id"]))
        project_keys.add((key, str(row["bid_notice_id"])))
        # Activity years describe the procurement cohort, not amendment dates.
        relationship_dates = [activity_date]
        relationship["dates"].extend(relationship_dates)
        relationship["years"].update(value.year for value in relationship_dates)
        if activity_type == "contract":
            relationship["contract_dates"].append(
                row.get("latest_contract_version_date") or activity_date
            )
        year_item = relationship["yearly"].setdefault(
            activity_date.year,
            {
                "year": activity_date.year,
                "participation_count": 0,
                "result_confirmed_participation_count": 0,
                "successful_participation_count": 0,
                "award_event_count": 0,
                "contract_event_count": 0,
                "attributed_contract_amount": Decimal("0"),
                "amount_statuses": [],
            },
        )
        year_item[count_field] += 1
        if activity_type == "contract":
            versions = int(row.get("contract_version_count") or 1)
            relationship["contract_version_count"] += versions
            contract_version_count += versions
            relationship["amount_statuses"].append(completeness)
            year_item["amount_statuses"].append(completeness)
            amount_statuses.append(completeness)
            contract_event_keys.add(str(row["event_key"]))
            if amount is not None:
                decimal_amount = Decimal(str(amount))
                relationship["total_attributed_contract_amount"] += decimal_amount
                year_item["attributed_contract_amount"] += decimal_amount
                total_amount += decimal_amount
        elif activity_type == "award":
            award_event_keys.add(str(row["event_key"]))
        else:
            participant_key = (key, str(row["event_key"]))
            participant_event_keys.add(participant_key)
            if row.get("result_confirmed"):
                confirmed_participant_event_keys.add(participant_key)
                relationship["result_confirmed_participation_count"] += 1
                year_item["result_confirmed_participation_count"] += 1
            if row.get("result_confirmed") and row.get("participation_successful"):
                successful_participant_event_keys.add(participant_key)
                relationship["successful_participation_count"] += 1
                year_item["successful_participation_count"] += 1
        register_notice(row)
        companies.add(str(row.get("company_number") or ""))
        organizations.add(str(row.get("organization_code") or ""))
        relationship["representative_notices"].append(
            {
                "bid_notice_id": row["bid_notice_id"],
                "notice_name": row.get("notice_name"),
                "activity_type": activity_type,
                "activity_date": activity_date,
                "amount": _number(
                    amount if activity_type == "contract" else row.get("event_amount")
                ),
                "attribution_date": activity_date,
                "attribution_date_basis": row.get("attribution_date_basis"),
                "first_contract_date": row.get("first_contract_date"),
                "latest_contract_version_date": row.get("latest_contract_version_date"),
            }
        )
        field_identity = _procurement_field_identity(row)
        if not field_identity:
            field_identity = {
                "code": None,
                "name": None,
                "large_category": "미분류",
                "middle_category": None,
                "detailed_items": [],
                "source": "unclassified",
            }
        field_key = field_identity["code"] or f"__unclassified__:{work_type}"
        relation_field = relationship["fields"].setdefault(
            field_key,
            {
                **field_identity,
                "event_keys": set(),
                "amount": Decimal("0"),
            },
        )
        for category in ("name", "large_category", "middle_category"):
            if field_identity[category] and not relation_field[category]:
                relation_field[category] = field_identity[category]
        if field_identity["detailed_items"] and not relation_field["detailed_items"]:
            relation_field["detailed_items"] = field_identity["detailed_items"]
        relation_field["event_keys"].add(str(row["bid_notice_id"]))
        if activity_type == "contract" and amount is not None:
            relation_field["amount"] += Decimal(str(amount))
        field = field_totals.setdefault(
            field_key,
            {
                "field_code": field_identity["code"],
                "field_name": field_identity["name"],
                "large_category": field_identity["large_category"],
                "middle_category": field_identity["middle_category"],
                "detailed_items": field_identity["detailed_items"],
                "classification_source": field_identity["source"],
                "work_types": set(),
                "event_keys": set(),
                "participation_keys": set(),
                "confirmed_participation_keys": set(),
                "successful_participation_keys": set(),
                "award_event_keys": set(),
                "contract_event_keys": set(),
                "attributed_contract_amount": Decimal("0"),
            },
        )
        for target, source in (
            ("field_name", "name"),
            ("large_category", "large_category"),
            ("middle_category", "middle_category"),
        ):
            if field_identity[source] and not field[target]:
                field[target] = field_identity[source]
        if field_identity["detailed_items"] and not field["detailed_items"]:
            field["detailed_items"] = field_identity["detailed_items"]
        event_key = str(row["event_key"])
        field["event_keys"].add((activity_type, event_key))
        field["work_types"].add(work_type)
        field[
            {
                "participation": "participation_keys",
                "award": "award_event_keys",
                "contract": "contract_event_keys",
            }[activity_type]
        ].add((key, event_key) if activity_type == "participation" else event_key)
        if activity_type == "participation" and row.get("result_confirmed"):
            field["confirmed_participation_keys"].add((key, event_key))
        if (
            activity_type == "participation"
            and row.get("result_confirmed")
            and row.get("participation_successful")
        ):
            field["successful_participation_keys"].add((key, event_key))
        if activity_type == "contract" and amount is not None:
            field["attributed_contract_amount"] += Decimal(str(amount))
        project_type = _primary_project_type(str(row.get("notice_name") or ""))
        relation_project = relationship["project_types"].setdefault(
            project_type,
            {
                "project_type": project_type,
                "project_type_name": _project_type_label(project_type),
                "event_keys": set(),
                "amount": Decimal("0"),
            },
        )
        relation_project["event_keys"].add(str(row["bid_notice_id"]))
        project = project_type_totals.setdefault(
            project_type,
            {
                "project_type": project_type,
                "project_type_name": _project_type_label(project_type),
                "event_keys": set(),
                "attributed_contract_amount": Decimal("0"),
            },
        )
        project["event_keys"].add((key, str(row["bid_notice_id"])))
        if activity_type == "contract" and amount is not None:
            decimal_amount = Decimal(str(amount))
            relation_project["amount"] += decimal_amount
            project["attributed_contract_amount"] += decimal_amount
        work = work_type_totals.setdefault(
            work_type,
            {
                "work_type": work_type,
                "work_type_name": _work_type_label(work_type),
                "event_keys": set(),
                "participation_keys": set(),
                "award_event_keys": set(),
                "contract_event_keys": set(),
                "attributed_contract_amount": Decimal("0"),
            },
        )
        work_event_key: Any = str(row["event_key"])
        if activity_type == "participation":
            work_event_key = (key, work_event_key)
        work["event_keys"].add((activity_type, work_event_key))
        work[
            {
                "participation": "participation_keys",
                "award": "award_event_keys",
                "contract": "contract_event_keys",
            }[activity_type]
        ].add(work_event_key)
        if activity_type == "contract" and amount is not None:
            work["attributed_contract_amount"] += Decimal(str(amount))

        global_year = year_bucket(activity_date)
        if activity_type == "award":
            global_year["award_event_keys"].add(str(row["event_key"]))
        elif activity_type == "contract":
            global_year["company_ids"].add(str(row.get("company_number") or ""))
            global_year["contract_event_keys"].add(str(row["event_key"]))
            global_year["amount_statuses"].append(completeness)
            if amount is not None:
                global_year["attributed_contract_amount"] += Decimal(str(amount))
        else:
            participant_key = (key, str(row["event_key"]))
            global_year["participation_keys"].add(participant_key)
            if row.get("result_confirmed"):
                global_year["confirmed_participation_keys"].add(participant_key)
            if row.get("result_confirmed") and row.get("participation_successful"):
                global_year["successful_participation_keys"].add(participant_key)

    for notice_id, published in notice_dates.items():
        year_bucket(published)["notice_ids"].add(notice_id)

    relationship_items = []
    for relationship in relationships.values():
        if require_contract_relationship and relationship["contract_event_count"] <= 0:
            continue
        relation_yearly = []
        for value in sorted(
            relationship.pop("yearly").values(), key=lambda x: x["year"]
        ):
            statuses = value.pop("amount_statuses")
            value["attributed_contract_amount"] = _number(
                value["attributed_contract_amount"]
            )
            value["amount_completeness"] = _amount_completeness(statuses)
            confirmed = value["result_confirmed_participation_count"]
            value["award_success_rate"] = (
                round(value["successful_participation_count"] / confirmed, 6)
                if confirmed
                else None
            )
            relation_yearly.append(value)
        statuses = relationship.pop("amount_statuses")
        dates = relationship.pop("dates")
        contract_dates = relationship.pop("contract_dates")
        years = sorted(relationship.pop("years"))
        major_fields = []
        for field in relationship.pop("fields").values():
            major_fields.append(
                {
                    "code": field["code"],
                    "name": field["name"],
                    "event_count": len(field["event_keys"]),
                    "amount": _number(field["amount"]),
                }
            )
        major_fields.sort(key=lambda item: item["event_count"], reverse=True)
        project_types = []
        for project in relationship.pop("project_types").values():
            project_types.append(
                {
                    "project_type": project["project_type"],
                    "project_type_name": project["project_type_name"],
                    "event_count": len(project["event_keys"]),
                    "amount": _number(project["amount"]),
                }
            )
        project_types.sort(key=lambda item: item["event_count"], reverse=True)
        relationship.update(
            {
                "total_attributed_contract_amount": _number(
                    relationship["total_attributed_contract_amount"]
                ),
                "amount_completeness": _amount_completeness(statuses),
                "first_activity_date": min(dates) if dates else None,
                "latest_activity_date": max(dates) if dates else None,
                "latest_contract_date": max(contract_dates) if contract_dates else None,
                "active_years": years,
                "active_year_count": len(years),
                "unique_project_count": len(relationship.pop("project_keys")),
                "yearly_activity": relation_yearly,
                "major_fields": major_fields,
                "major_field": (
                    {
                        "field_code": max(
                            major_fields,
                            key=lambda item: (item["amount"] or 0, item["event_count"]),
                        )["code"],
                        "field_name": max(
                            major_fields,
                            key=lambda item: (item["amount"] or 0, item["event_count"]),
                        )["name"],
                    }
                    if major_fields
                    else None
                ),
                "project_type_distribution": project_types,
                "representative_notices": sorted(
                    relationship["representative_notices"],
                    key=lambda item: item["activity_date"],
                    reverse=True,
                )[:3],
            }
        )
        confirmed = relationship["result_confirmed_participation_count"]
        relationship["award_success_rate"] = (
            round(relationship["successful_participation_count"] / confirmed, 6)
            if confirmed
            else None
        )
        relationship_items.append(relationship)
    yearly_items = []
    for year in sorted(yearly, reverse=True):
        value = yearly[year]
        yearly_items.append(
            {
                "year": year,
                "notice_count": len(value["notice_ids"]),
                "participation_count": len(value["participation_keys"]),
                "result_confirmed_participation_count": len(
                    value["confirmed_participation_keys"]
                ),
                "successful_participation_count": len(
                    value["successful_participation_keys"]
                ),
                "award_success_rate": (
                    round(
                        len(value["successful_participation_keys"])
                        / len(value["confirmed_participation_keys"]),
                        6,
                    )
                    if value["confirmed_participation_keys"]
                    else None
                ),
                "award_event_count": len(value["award_event_keys"]),
                "contract_event_count": len(value["contract_event_keys"]),
                "company_count": len(value["company_ids"] - {""}),
                "attributed_contract_amount": _number(
                    value["attributed_contract_amount"]
                ),
                "amount_completeness": _amount_completeness(value["amount_statuses"]),
            }
        )
    field_items = []
    for value in field_totals.values():
        amount = value.pop("attributed_contract_amount")
        value["work_types"] = sorted(value["work_types"])
        value["event_count"] = len(value.pop("event_keys"))
        value["participation_count"] = len(value.pop("participation_keys"))
        value["result_confirmed_participation_count"] = len(
            value.pop("confirmed_participation_keys")
        )
        successful = len(value.pop("successful_participation_keys"))
        value["successful_participation_count"] = successful
        value["award_success_rate"] = (
            round(successful / value["result_confirmed_participation_count"], 6)
            if value["result_confirmed_participation_count"]
            else None
        )
        value["award_event_count"] = len(value.pop("award_event_keys"))
        value["contract_event_count"] = len(value.pop("contract_event_keys"))
        value["attributed_contract_amount"] = _number(amount)
        value["amount_share"] = (
            round(float(amount / total_amount), 6) if total_amount else None
        )
        field_items.append(value)
    summary = {
        "notice_count": len(notice_dates),
        "participation_count": len(participant_event_keys),
        "result_confirmed_participation_count": len(confirmed_participant_event_keys),
        "successful_participation_count": len(successful_participant_event_keys),
        "award_event_count": len(award_event_keys),
        "contract_event_count": len(contract_event_keys),
        "contract_version_count": contract_version_count,
        "unique_project_count": len(project_keys),
        "company_count": (
            len(relationship_items)
            if require_contract_relationship
            else len(companies - {""})
        ),
        "organization_count": len(organizations - {""}),
        "total_attributed_contract_amount": _number(total_amount),
        "amount_completeness": _amount_completeness(amount_statuses),
        "classified_notice_count": len(classified_notice_ids),
        "field_classification_completeness": (
            "complete"
            if notice_dates and classified_notice_ids == set(notice_dates)
            else "partial"
            if classified_notice_ids
            else "unknown"
        ),
    }
    summary["award_success_rate"] = (
        round(
            len(successful_participant_event_keys)
            / len(confirmed_participant_event_keys),
            6,
        )
        if confirmed_participant_event_keys
        else None
    )
    project_type_items = []
    for value in project_type_totals.values():
        project_type_items.append(
            {
                "project_type": value["project_type"],
                "project_type_name": value["project_type_name"],
                "event_count": len(value["event_keys"]),
                "attributed_contract_amount": _number(
                    value["attributed_contract_amount"]
                ),
            }
        )
    work_type_items = []
    for value in work_type_totals.values():
        work_type_items.append(
            {
                "work_type": value["work_type"],
                "work_type_name": value["work_type_name"],
                "event_count": len(value["event_keys"]),
                "participation_count": len(value["participation_keys"]),
                "award_event_count": len(value["award_event_keys"]),
                "contract_event_count": len(value["contract_event_keys"]),
                "attributed_contract_amount": _number(
                    value["attributed_contract_amount"]
                ),
            }
        )
    return (
        summary,
        relationship_items,
        yearly_items,
        field_items,
        project_type_items,
        work_type_items,
    )
