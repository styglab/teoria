from teoria_pipelines.models import ExtractedBatch


def select_participants(
    awards: ExtractedBatch, openings: ExtractedBatch, maximum_rank: int = 10
) -> ExtractedBatch:
    if maximum_rank < 1:
        raise ValueError("maximum_rank must be positive")

    def key(payload: dict) -> tuple[str, str, str, str]:
        return tuple(
            str(payload.get(name) or "").strip()
            for name in ("bidNtceNo", "bidNtceOrd", "bidClsfcNo", "rbidNo")
        )  # type: ignore[return-value]

    def business_number(value: object) -> str:
        return "".join(
            character for character in str(value or "") if character.isdigit()
        )

    winners = {
        key(record.payload): business_number(record.payload.get("bidwinnrBizno"))
        for record in awards.records
    }
    selected = []
    for record in openings.records:
        rank_text = str(record.payload.get("opengRank") or "").strip().replace(",", "")
        try:
            rank = int(rank_text) if rank_text else None
        except ValueError:
            rank = None
        participant = business_number(record.payload.get("prcbdrBizno"))
        is_winner = bool(
            participant and participant == winners.get(key(record.payload))
        )
        if is_winner or (rank is not None and 1 <= rank <= maximum_rank):
            selected.append(record)
    return ExtractedBatch(
        execution_id=openings.execution_id,
        window=openings.window,
        records=selected,
        pages=openings.pages,
    )
