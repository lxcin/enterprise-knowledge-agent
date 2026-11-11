"""Load versioned, layout-aware attachments from the normalized JSON format."""

from dataclasses import dataclass
from datetime import date
import json
from pathlib import Path
import re
from unicodedata import normalize as unicode_normalize


@dataclass(frozen=True)
class Evidence:
    id: str
    doc_id: str
    version_date: str
    kind: str
    title: str
    document_title: str
    topic: str
    text: str
    page: int | None
    links: tuple[str, ...]
    asset: Path | None = None
    table_parts: tuple[str, ...] = ()
    source_file: str | None = None
    bbox: tuple[float, ...] | None = None
    asset_path: str | None = None

    def location(self):
        location = dict(id=self.id, doc_id=self.doc_id, version_date=self.version_date,
                        kind=self.kind, title=self.title, page=self.page)
        if self.source_file is not None:
            location["source_file"] = self.source_file
        if self.bbox is not None:
            location["bbox"] = self.bbox
        return location

    def candidate(self):
        return {**self.location(), "topic": self.topic, "document_title": self.document_title}


def load_documents(folder: Path) -> dict[str, Evidence]:
    index = {}
    root = folder.resolve()
    manifests = [*root.glob("*.json"), *root.glob("*/document.json")]
    for path in sorted(manifests):
        doc = json.loads(path.read_text(encoding="utf-8-sig"))
        doc_id, version = doc["doc_id"], doc["version_date"]
        date.fromisoformat(version)
        source_file = None
        if "source_file" in doc:
            source_file = bundle_file(path.parent, doc["source_file"]).relative_to(root).as_posix()
        for block in doc["blocks"]:
            key = f"{doc_id}@{version}/{block['id']}"
            if key in index:
                raise ValueError(f"重复片段 ID：{key}")
            kind = block["kind"]
            asset = None
            table_parts = ()
            if kind in {"figure", "scan"}:
                asset = bundle_file(path.parent, block["asset"])
                if asset.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
                    raise ValueError(f"无效图片路径：{key}")
            if kind == "table":
                table_parts = table_sections(block)
                text = "\n".join(table_parts)
            elif kind in {"text", "figure", "scan"}:
                text = block.get("text", "")
            else:
                raise ValueError(f"未知片段类型：{kind}")
            index[key] = Evidence(key, doc_id, version, kind, block["title"], doc["title"],
                                  block["topic"], text, block.get("page"),
                                  tuple(block.get("links", ())), asset, table_parts,
                                  source_file=source_file, bbox=tuple(block["bbox"]) if "bbox" in block else None,
                                  asset_path=asset.relative_to(root).as_posix() if asset else None)
    if not index:
        raise ValueError(f"没有文档片段：{folder}")
    return index


def bundle_file(folder, filename):
    path = (folder / filename).resolve()
    if not path.is_relative_to(folder.resolve()):
        raise ValueError(f"附件文件超出文档目录：{filename}")
    return path


def table_sections(block):
    headers = block["headers"]
    lines = []
    for number, row in enumerate(block["rows"], 1):
        if len(row) != len(headers):
            raise ValueError(f"表格 {block['id']} 第 {number} 行与表头不匹配")
        lines.append(" | ".join(f"{header}：{value}" for header, value in zip(headers, row)))
    return (*lines, *block.get("footnotes", []))


def normalize(text: str) -> str:
    return re.sub(r"[^\w]+", "", unicode_normalize("NFKC", text).casefold())
