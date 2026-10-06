from __future__ import annotations

from html.parser import HTMLParser
from typing import Any


class _TableParser(HTMLParser):
    def __init__(self, table_class: str) -> None:
        super().__init__(convert_charrefs=True)
        self.table_class = table_class
        self.table_depth = 0
        self.in_target = False
        self.in_cell = False
        self.cell_parts: list[str] = []
        self.row: list[str] | None = None
        self.rows: list[list[str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "table":
            classes = (attributes.get("class") or "").split()
            if not self.in_target and self.table_class in classes:
                self.in_target = True
                self.table_depth = 1
            elif self.in_target:
                self.table_depth += 1
        elif self.in_target and tag == "tr":
            self.row = []
        elif self.in_target and tag == "td" and self.row is not None:
            self.in_cell = True
            self.cell_parts = []
        elif self.in_cell and tag == "br":
            self.cell_parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if not self.in_target:
            return
        if tag == "td" and self.in_cell and self.row is not None:
            self.row.append(" ".join("".join(self.cell_parts).split()))
            self.in_cell = False
        elif tag == "tr" and self.row is not None:
            if self.row:
                self.rows.append(self.row)
            self.row = None
        elif tag == "table":
            self.table_depth -= 1
            if self.table_depth == 0:
                self.in_target = False

    def handle_data(self, data: str) -> None:
        if self.in_cell:
            self.cell_parts.append(data)


def extract_html_table(html: str, *, table_class: str, columns: list[dict[str, Any]]) -> list[dict[str, str]]:
    parser = _TableParser(table_class)
    parser.feed(html)
    records: list[dict[str, str]] = []
    for row in parser.rows:
        record = {
            column["field"]: row[column["index"]]
            for column in columns
            if column["index"] < len(row)
        }
        if record:
            records.append(record)
    return records
