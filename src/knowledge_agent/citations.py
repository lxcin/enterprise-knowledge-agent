"""Validate that citations point to material actually read during this turn."""

from .retrieval import Source


def validate_citations(citations, sources: dict[str, Source]):
    if not isinstance(citations, list):
        raise ValueError("citations 必须是列表")
    result = []
    for citation in citations:
        if not isinstance(citation, dict):
            raise ValueError("引用必须是对象")
        key, quote = citation.get("id"), citation.get("quote")
        if not isinstance(key, str) or key not in sources or not isinstance(quote, str):
            raise ValueError("引用必须提供已读取的片段 ID 和字符串 quote")
        source = sources[key]
        item = source.evidence
        record = item.location()
        if source.image is not None:
            if quote:
                raise ValueError("图像引用请使用空 quote，由程序附上原图位置")
            record["asset"] = item.asset_path or item.asset.name
        elif not quote.strip() or quote not in item.text:
            raise ValueError(f"引文与片段不匹配：{key}")
        result.append({**record, "quote": quote})
    return result
