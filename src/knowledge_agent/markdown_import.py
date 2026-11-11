"""Import Markdown sections and simple pipe tables into the same evidence format."""

import re


HEADING = re.compile(r"^#{1,6}\s+(.+)$")
SEPARATOR = re.compile(r":?-{3,}:?")


def parse_markdown(source, topic, title):
    blocks, paragraph = [], []

    def add(kind, **data):
        blocks.append({"id": f"block-{len(blocks) + 1:04d}", "kind": kind,
                       "title": title, "topic": topic, **data})

    def flush():
        if paragraph:
            add("text", text="\n".join(paragraph))
            paragraph.clear()

    lines = source.read_text(encoding="utf-8-sig").splitlines()
    index, fence = 0, ""
    while index < len(lines):
        line = lines[index]
        marker = re.match(r"^\s*(`{3,}|~{3,})", line)
        if marker:
            token = marker[1]
            if not fence:
                fence = token
            elif token.startswith(fence) and not line.strip()[len(token):].strip():
                fence = ""
            paragraph.append(line)
        elif fence:
            paragraph.append(line)
        elif heading := HEADING.match(line):
            flush()
            title = heading[1]
        elif index + 1 < len(lines) and is_table_start(line, lines[index + 1]):
            flush()
            headers = cells(line)
            rows = []
            index += 2
            while index < len(lines) and "|" in lines[index]:
                row = cells(lines[index])
                if len(row) != len(headers):
                    break
                rows.append(row)
                index += 1
            add("table", headers=headers, rows=rows)
            continue
        elif line.strip():
            paragraph.append(line)
        else:
            flush()
        index += 1
    flush()
    return blocks


def cells(line):
    line = line.strip().removeprefix("|")
    if line.endswith("|") and not line.endswith(r"\|"):
        line = line[:-1]
    return [cell.strip().replace(r"\|", "|") for cell in re.split(r"(?<!\\)\|", line)]


def is_table_start(line, separator):
    if "|" not in line or "|" not in separator:
        return False
    dividers = cells(separator)
    return len(cells(line)) == len(dividers) and all(SEPARATOR.fullmatch(cell) for cell in dividers)
