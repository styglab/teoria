"""Render the structured tree without discarding merged or nested cells."""

from html import escape

from .character_maps import map_display_text
from .models import Block


def blocks_to_markdown(blocks: list[Block]) -> str:
    output = []
    for block in blocks:
        if block.table:
            lines = ["<table>"]
            for row in block.table.cells:
                lines.append("  <tr>")
                for cell in row:
                    if cell.covered:
                        continue
                    attrs = ""
                    if cell.row_span > 1:
                        attrs += f' rowspan="{cell.row_span}"'
                    if cell.col_span > 1:
                        attrs += f' colspan="{cell.col_span}"'
                    content = (
                        blocks_to_markdown(cell.blocks)
                        if cell.blocks
                        else escape(map_display_text(cell.text)).replace("\n", "<br>")
                    )
                    lines.append(f"    <td{attrs}>{content}</td>")
                lines.append("  </tr>")
            lines.append("</table>")
            output.append("\n".join(lines))
        elif block.type == "image":
            output.append(f"[image: {block.source.anchor if block.source else 'unresolved'}]")
        elif block.type == "heading":
            output.append("#" * min(6, max(1, block.level or 1)) + " " + map_display_text(block.text))
        elif block.type == "separator":
            output.append("---")
        elif block.type == "list":
            output.append("  " * max(0, (block.level or 1) - 1) + map_display_text(block.text))
        else:
            output.append(map_display_text(block.text))
        if block.children:
            output.append(blocks_to_markdown(block.children))
    return "\n\n".join(output)
