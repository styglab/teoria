from __future__ import annotations


def resolve_operating_status(value: str | None) -> str | None:
    return {"01": "active", "02": "suspended", "03": "closed"}.get(value or "")


def resolve_taxation_type(value: str | None) -> str | None:
    return {
        "01": "general_taxpayer",
        "02": "simplified_taxpayer",
        "03": "special_taxpayer",
        "04": "tax_exempt_business",
        "05": "non_profit_or_public_entity",
        "06": "organization_with_identifier",
        "07": "simplified_taxpayer_invoice_issuer",
        "99": "not_applicable",
    }.get(value or "")


def resolve_verification_result(value: str | None) -> str | None:
    return {"01": "verified", "02": "not_verified"}.get(value or "")
