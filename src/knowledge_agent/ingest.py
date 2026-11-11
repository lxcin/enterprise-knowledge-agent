"""Convert attachments into source-preserving evidence bundles."""

import argparse
from datetime import date
import json
from pathlib import Path
import re
import shutil
from tempfile import TemporaryDirectory

from .markdown_import import parse_markdown
from .pdf_import import parse_pdf


def import_attachment(source: Path, folder: Path, doc_id: str, version_date: str,
                      topic: str, title=None, visual_pages=(), ocr_language=None):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", doc_id):
        raise ValueError("文档 ID 仅支持字母、数字、下划线和连字符")
    version = date.fromisoformat(version_date).isoformat()
    if not topic.strip():
        raise ValueError("主题不能为空")
    suffix = source.suffix.lower()
    if suffix not in {".pdf", ".md", ".markdown"}:
        raise ValueError("当前支持 PDF 和 Markdown")
    if suffix != ".pdf" and (visual_pages or ocr_language):
        raise ValueError("视觉页和 OCR 参数仅用于 PDF")

    folder.mkdir(parents=True, exist_ok=True)
    destination = folder / f"{doc_id}@{version}"
    if destination.exists():
        raise ValueError(f"同一文档版本已导入：{destination}")

    with TemporaryDirectory(prefix=".import-", dir=folder) as temporary:
        stage = Path(temporary) / "bundle"
        stage.mkdir()
        original = stage / f"source{suffix}"
        shutil.copyfile(source, original)
        blocks = (parse_pdf(original, stage, topic, visual_pages, ocr_language)
                  if suffix == ".pdf" else parse_markdown(original, topic, title or source.stem))
        if not blocks:
            raise ValueError("未提取到可入库的内容")
        document = {"doc_id": doc_id, "version_date": version, "title": title or source.stem,
                    "source_file": original.name, "blocks": blocks}
        (stage / "document.json").write_text(json.dumps(document, ensure_ascii=False, indent=2),
                                             encoding="utf-8")
        stage.rename(destination)
    return destination


def main():
    parser = argparse.ArgumentParser(description="导入 PDF 或 Markdown 附件")
    parser.add_argument("source", type=Path)
    parser.add_argument("--docs", type=Path, default=Path("data"))
    parser.add_argument("--doc-id", required=True)
    parser.add_argument("--version-date", required=True)
    parser.add_argument("--topic", required=True, help="同一事项的候选制度使用相同主题")
    parser.add_argument("--title")
    parser.add_argument("--visual-page", action="append", type=int, default=[],
                        help="直接按原图导入指定 PDF 页，可重复指定")
    parser.add_argument("--ocr-language", help="Tesseract 语言代码，例如 chi_sim+eng")
    args = parser.parse_args()
    try:
        output = import_attachment(args.source, args.docs, args.doc_id, args.version_date,
                                   args.topic, args.title, args.visual_page, args.ocr_language)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(output.resolve())


if __name__ == "__main__":
    main()
