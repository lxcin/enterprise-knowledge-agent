"""Parse layout-aware PDF evidence and retain rendered pages for visual checks."""

from pathlib import Path
import re
import shutil
import subprocess


FOOTNOTE = re.compile(r"^(?:注(?:释)?[：:]|备注[：:]|note\s*[:：])", re.I)
CLAUSE = re.compile(r"^(?:第[一二三四五六七八九十百零\d]+条|\d+[.、]\s+)")


def parse_pdf(source: Path, output: Path, topic: str, visual_pages=(), ocr_language=None):
    try:
        import pdfplumber
    except ImportError as error:
        raise ValueError("PDF 导入需要安装 pdfplumber：py -3.12 -m pip install pdfplumber") from error

    blocks = []
    with pdfplumber.open(source) as pdf:
        if set(visual_pages) - set(range(1, len(pdf.pages) + 1)):
            raise ValueError("--visual-page 超出 PDF 页码范围")
        for page in pdf.pages:
            blocks.extend(parse_page(page, source, output, topic,
                                     page.page_number in visual_pages, ocr_language))
    return blocks


def parse_page(page, source, output, topic, force_visual, ocr_language):
    number = page.page_number
    text = (page.extract_text() or "").strip()
    prefix = f"p{number:04d}"
    base = {"topic": topic, "page": number}
    if force_visual or not text:
        return [visual_block(source, output, base, prefix, text, ocr_language,
                             "figure" if force_visual else "scan")]

    tables = page.find_tables()
    image_boxes = [tuple(image[key] for key in ("x0", "top", "x1", "bottom"))
                   for image in page.images
                   if image["width"] >= 60 and image["height"] >= 45]
    excluded = [table.bbox for table in tables] + image_boxes

    def outside(obj):
        if obj["object_type"] != "char":
            return True
        x = (obj["x0"] + obj["x1"]) / 2
        y = (obj["top"] + obj["bottom"]) / 2
        return not any(left <= x <= right and top <= y <= bottom
                       for left, top, right, bottom in excluded)

    lines = page.filter(outside).extract_text_lines(return_chars=False)
    blocks = []
    needs_visual = bool(image_boxes)
    for index, table in enumerate(tables, 1):
        rows = table.extract()
        if not simple_table(rows):
            needs_visual = True
            continue
        nearby = [line for line in lines
                  if table.bbox[3] <= line["top"] <= table.bbox[3] + 32
                  and table.bbox[0] - 4 <= line["x0"] < table.bbox[2]]
        footnotes = [line["text"] for line in nearby if FOOTNOTE.match(line["text"])]
        blocks.append({**base, "id": f"{prefix}-table-{index}", "kind": "table",
                       "title": f"第 {number} 页表格 {index}", "headers": rows[0],
                       "rows": rows[1:], "footnotes": footnotes,
                       "bbox": list(table.bbox)})
    for index, group in enumerate(group_lines(lines), 1):
        title = group[0]["text"] if CLAUSE.match(group[0]["text"]) else f"第 {number} 页正文 {index}"
        blocks.append({**base, "id": f"{prefix}-text-{index}", "kind": "text",
                       "title": title, "text": "\n".join(line["text"] for line in group),
                       "bbox": [min(line["x0"] for line in group), group[0]["top"],
                                max(line["x1"] for line in group), group[-1]["bottom"]]})
    if needs_visual or not blocks:
        blocks.append(visual_block(source, output, base, prefix, text, ocr_language, "figure"))
    return blocks


def simple_table(rows):
    if not rows or len(rows) < 2:
        return False
    headers = rows[0]
    return (len(headers) >= 2 and all(header and header.strip() for header in headers)
            and len(set(headers)) == len(headers)
            and all(len(row) == len(headers) and all(cell is not None for cell in row)
                    for row in rows))


def group_lines(lines):
    group, size = [], 0
    for line in lines:
        previous = group[-1] if group else None
        if previous and (line["top"] - previous["bottom"] > 14
                         or CLAUSE.match(line["text"]) or size >= 1000):
            yield group
            group, size = [], 0
        group.append(line)
        size += len(line["text"])
    if group:
        yield group


def visual_block(source, output, base, prefix, text, ocr_language, kind):
    renderer = shutil.which("pdftoppm")
    if not renderer:
        raise ValueError("视觉 PDF 页面需要 Poppler 的 pdftoppm，请加入 PATH")
    number = str(base["page"])
    target = output / f"{prefix}-original"
    run_tool([renderer, "-f", number, "-l", number, "-singlefile", "-scale-to", "1800",
              "-png", str(source), str(target)], "PDF 页面渲染")
    image = target.with_suffix(".png")
    if not image.is_file():
        raise ValueError(f"PDF 渲染没有生成第 {number} 页原图")
    if ocr_language and not text:
        ocr = shutil.which("tesseract")
        if not ocr:
            raise ValueError("已指定 OCR 语言，但 PATH 中找不到 tesseract")
        text = run_tool([ocr, str(image), "stdout", "-l", ocr_language], "PDF OCR").strip()
    return {**base, "id": f"{prefix}-visual", "kind": kind, "title": f"第 {number} 页原图",
            "asset": image.name, "text": text}


def run_tool(args, operation):
    try:
        return subprocess.run(args, capture_output=True, check=True, encoding="utf-8",
                              errors="replace", timeout=90).stdout
    except subprocess.CalledProcessError as error:
        raise ValueError(f"{operation}失败：{error.stderr.strip()}") from error
    except subprocess.TimeoutExpired as error:
        raise ValueError(f"{operation}超时") from error
