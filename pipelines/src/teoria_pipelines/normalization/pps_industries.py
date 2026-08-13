from datetime import datetime, timezone


def normalize_industries(batch):
    now = datetime.now(timezone.utc)
    rows = []
    for record in batch.records:
        value = record.payload
        rows.append({
            "industry_code": str(value["indstrytyCd"]),
            "industry_name": str(value["indstrytyNm"]),
            "classification_code": str(value["indstrytyClsfcCd"]),
            "classification_name": str(value["indstrytyClsfcNm"]),
            "base_law_name": value.get("baseLawordNm"),
            "base_law_article": value.get("baseLawordArtclClauseNm"),
            "base_law_url": value.get("baseLawordUrl"),
            "related_regulation_contents": value.get("rltnRgltCntnts"),
            "included_license_text": value.get("inclsnLcns"),
            "source_use_yn": value.get("indstrytyUseYn"),
            "source_registered_at": value["indstrytyRgstDt"],
            "source_changed_at": value.get("indstrytyChgDt"),
            "first_seen_at": now, "last_seen_at": now,
            "is_active": value.get("indstrytyUseYn") == "Y",
            "source_record_hash": record.source_record_hash,
        })
    return rows
