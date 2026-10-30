"""Double borders denote one rule, while unrelated narrow partitions stay distinct."""

import pymupdf
import pytest

from kory_parser import ParseOptions, parse
from kory_parser.compare import block_text, normalized_text, tables_in_order


def paired_table(gap, rotation):
    document = pymupdf.open()
    page = document.new_page(width=300, height=220)
    for x in (40, 140, 240):
        for offset in (-gap / 2, gap / 2):
            page.draw_line((x + offset, 50 - gap / 2), (x + offset, 150 + gap / 2), width=0.25)
    for y in (50, 100, 150):
        for offset in (-gap / 2, gap / 2):
            page.draw_line((40 - gap / 2, y + offset), (240 + gap / 2, y + offset), width=0.25)
    for text, x, y in [("A", 60, 80), ("B", 160, 80), ("C", 60, 130), ("D", 160, 130)]:
        page.insert_text((x, y), text, fontsize=10)
    page.set_rotation(rotation)
    data = document.tobytes()
    document.close()
    return data


@pytest.mark.parametrize("gap", [1.2, 1.4])
@pytest.mark.parametrize("rotation", [0, 180])
def test_paired_rules_keep_four_cells_without_phantom_rows_or_columns(gap, rotation):
    result = parse(paired_table(gap, rotation), ParseOptions(ocr=False, images=False))
    assert result.success
    tables = tables_in_order(result.to_dict()["blocks"])
    assert [(t["rows"], t["cols"]) for t in tables] == [(2, 2)]
    assert sorted(c["text"] for row in tables[0]["cells"] for c in row) == ["A", "B", "C", "D"]
    text = normalized_text(block_text(result.to_dict()["blocks"]))
    assert all(text.count(letter) == 1 for letter in "ABCD")
    if rotation == 0:
        assert [[c["text"] for c in row] for row in tables[0]["cells"]] == [["A", "B"], ["C", "D"]]
        assert next(b.source.bbox for b in result.blocks if b.table) == pytest.approx(
            (40, 50, 240, 150), abs=0.001
        )


def rule(position, *, start=20, end=120, width=0.25, color=(0, 0, 0), kind="line"):
    return {
        "object_type": kind,
        "orientation": "h",
        "x0": start,
        "x1": end,
        "top": position,
        "bottom": position,
        "linewidth": width,
        "stroking_color": color,
    }


def test_duplicate_paint_operations_do_not_move_border_midpoint():
    from kory_parser.pdf_rules import paired_rule_groups

    groups = [[rule(20)] * 5, [rule(21.4)]]
    result = list(paired_rule_groups(groups, "top"))
    assert len(result) == 1 and result[0][1] == pytest.approx(20.7)


@pytest.mark.parametrize(
    "second",
    [
        rule(21.4, start=170, end=270),
        rule(21.4, end=100),
        rule(21.4, width=1),
        rule(21.4, color=(1, 0, 0)),
        rule(21.4, kind="rect"),
        rule(22),
    ],
)
def test_geometry_style_and_spacing_must_establish_a_pair(second):
    from kory_parser.pdf_rules import paired_rule_groups

    groups = [[rule(20)], [second]]
    result = list(paired_rule_groups(groups, "top"))
    assert len(result) == 2
    assert [p for _, p in result] == [20, second["top"]]


def test_three_close_partitions_do_not_chain_into_one_border():
    from kory_parser.pdf_rules import paired_rule_groups

    groups = [[rule(p)] for p in (20, 21.2, 22.4)]
    assert len(list(paired_rule_groups(groups, "top"))) == 3


def pair_evidence(*, rows=(50, 100), bounded=True, horizontal_span=(40, 240)):
    vertical = [dict(rule(0), x0=x, x1=x, top=20, bottom=120, orientation="v") for x in (139.3, 140.7)]
    groups = {"v": [((vertical[:1], vertical[1:]), 140)], "h": []}
    for y in rows:
        parents = (
            [rule(y - 0.7, start=horizontal_span[0], end=horizontal_span[1])],
            [rule(y + 0.7, start=horizontal_span[0], end=horizontal_span[1])],
        )
        groups["h"].append((parents, y))
    bounds = [dict(e, x0=x, x1=x) for e, x in zip(vertical, (40, 240))] if bounded else []
    return groups, vertical + bounds


def test_internal_double_divider_and_repeated_crossing_rows_establish_a_grid():
    from kory_parser.pdf_rules import corroborated_rule_pairs

    assert corroborated_rule_pairs(*pair_evidence()) == {"v": {0}, "h": {0, 1}}


@pytest.mark.parametrize(
    "options", [{"rows": (50,)}, {"bounded": False}, {"horizontal_span": (170, 270)}, {"rows": (50, 150)}]
)
def test_frames_lone_separators_and_remote_tables_do_not_establish_a_grid(options):
    from kory_parser.pdf_rules import corroborated_rule_pairs

    assert corroborated_rule_pairs(*pair_evidence(**options)) == {"v": set(), "h": set()}
