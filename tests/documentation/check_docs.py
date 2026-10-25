"""Check local Markdown targets, ATX heading fragments, and docs/index.md navigation."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit

INLINE_LINK = re.compile(r'!?\[[^\]\n]*\]\(\s*(<[^>]+>|[^\s)]+)(?:\s+"[^"]*")?\s*\)')
REFERENCE_DEFINITION = re.compile(r'^ {0,3}\[([^\]]+)\]:\s*(<[^>]+>|\S+)', re.MULTILINE)
REFERENCE_LINK = re.compile(r'!?\[([^\]\n]+)\]\[([^\]\n]*)\]')


def prose(text: str) -> str:
    """Exclude fenced examples while preserving diagnostic line numbers."""
    lines = []
    fence = None
    for line in text.splitlines(keepends=True):
        marker = re.match(r'^ {0,3}(`{3,}|~{3,})', line)
        if fence:
            if marker and marker[1][0] == fence[0] and len(marker[1]) >= len(fence):
                fence = None
            lines.append('\n' if line.endswith('\n') else '')
        elif marker:
            fence = marker[1]
            lines.append('\n' if line.endswith('\n') else '')
        else:
            lines.append(line)
    return ''.join(lines)


def heading_ids(text: str) -> set[str]:
    ids = set(re.findall(r'\bid=["\']([^"\']+)["\']', prose(text)))
    counts: Counter[str] = Counter()
    for line in prose(text).splitlines():
        match = re.match(r'^ {0,3}#{1,6}\s+(.+?)(?:\s+#+)?\s*$', line)
        if not match:
            continue
        title = re.sub(r'<[^>]+>', '', match[1]).lower().replace('`', '')
        title = re.sub(r'[^\w\-\s]', '', title)
        slug = re.sub(r'\s', '-', title)
        number = counts[slug]
        counts[slug] += 1
        ids.add(f'{slug}-{number}' if number else slug)
    return ids


def markdown_links(text: str) -> list[tuple[int, str]]:
    body = re.sub(r'(`+).*?\1', lambda m: ' ' * len(m[0]), prose(text))
    definitions = {m[1].casefold(): m[2].strip('<>') for m in REFERENCE_DEFINITION.finditer(body)}
    links = [(m.start(), m[1].strip('<>')) for m in INLINE_LINK.finditer(body)]
    for match in REFERENCE_LINK.finditer(body):
        label = (match[2] or match[1]).casefold()
        links.append((match.start(), definitions.get(label, f'missing-reference:{label}')))
    return [(body.count('\n', 0, offset) + 1, target) for offset, target in links]


def validate(root: Path) -> tuple[list[str], int, int]:
    root = root.resolve()
    docs = sorted((root / 'docs').rglob('*.md'))
    sources = [p for p in [root / 'README.md', root / 'AGENTS.md'] if p.exists()]
    sources += docs + sorted((root / '.agents/skills').rglob('*.md'))
    graph: dict[Path, set[Path]] = defaultdict(set)
    errors = []
    checked = 0
    anchors: dict[Path, set[str]] = {}
    for source in sources:
        for line, target in markdown_links(source.read_text(encoding='utf-8')):
            location = f'{source.relative_to(root)}:{line}'
            if target.startswith('missing-reference:'):
                errors.append(f'{location}: undefined link reference {target.partition(":")[2]}')
                continue
            url = urlsplit(target)
            if url.scheme or url.netloc:
                continue
            checked += 1
            path = unquote(url.path)
            destination = (source.parent / path).resolve() if path else source.resolve()
            if not destination.is_relative_to(root):
                errors.append(f'{location}: link leaves repository: {target}')
                continue
            if not destination.exists():
                errors.append(f'{location}: missing target: {target}')
                continue
            graph[source.resolve()].add(destination)
            if url.fragment and destination.suffix == '.md':
                if destination not in anchors:
                    anchors[destination] = heading_ids(destination.read_text(encoding='utf-8'))
                if unquote(url.fragment) not in anchors[destination]:
                    errors.append(f'{location}: missing heading: {target}')
    index = root / 'docs/index.md'
    if not index.exists():
        errors.append('docs/index.md: document entry point is missing')
    visited = set()
    pending = [index]
    while pending:
        source = pending.pop()
        if source in visited:
            continue
        visited.add(source)
        pending.extend(graph[source] - visited)
    for document in docs:
        if document not in visited:
            errors.append(f'{document.relative_to(root)}: unreachable from docs/index.md')
    return errors, checked, len(docs)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=(Path(__file__).resolve().parents[2]))
    args = parser.parse_args()
    errors, links, documents = validate(args.root)
    for error in errors:
        print(error)
    print(f'Checked {links} local links and {documents} documents; {len(errors)} errors.')
    return int(bool(errors))


if __name__ == '__main__':
    raise SystemExit(main())
