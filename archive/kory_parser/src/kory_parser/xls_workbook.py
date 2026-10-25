"""Narrow BIFF8 value recovery without changing xlrd's global parser state."""

import xlrd
from xlrd.biffh import XL_WORKBOOK_GLOBALS
from xlrd.book import SUPBOOK_EXTERNAL


class _CachedValueBook(xlrd.book.Book):
    def __init__(self):
        super().__init__()
        self.skipped_defined_names = 0
        self.skipped_external_names = 0

    def handle_name(self, data):
        # Cell formula caches are independent of defined-name evaluation.
        self.skipped_defined_names += 1

    def handle_supbook(self, data):
        try:
            super().handle_supbook(data)
        except UnicodeDecodeError:
            # xlrd already recorded this external book's type and count. Only
            # its sheet labels failed; local worksheet caches do not use them.
            if not self._supbook_types or self._supbook_types[-1] != SUPBOOK_EXTERNAL:
                raise
            self.skipped_external_names += 1


def open_value_workbook(data):
    """Keep the normal path; recover specific BIFF8 ancillary-name failures only."""
    try:
        return xlrd.open_workbook(file_contents=data, formatting_info=True, on_demand=True), False
    except (IndexError, UnicodeDecodeError) as error:
        book = _CachedValueBook()
        ready = False
        try:
            book.biff2_8_load(file_contents=data, formatting_info=True, on_demand=True)
            version = book.getbof(XL_WORKBOOK_GLOBALS)
            if version != 80:
                raise
            book.biff_version = version
            book.parse_globals()
            if isinstance(error, UnicodeDecodeError):
                if not book.skipped_external_names:
                    raise
            elif not book.skipped_defined_names:
                raise
            # Match xlrd's BIFF8 on-demand sheet initialization. Neither source
            # bytes nor Book/evaluate_name_formula globals are modified.
            book._sheet_list = [None] * len(book._sheet_names)
            book.nsheets = len(book._sheet_list)
            ready = True
            return book, True
        finally:
            if not ready:
                book.release_resources()
