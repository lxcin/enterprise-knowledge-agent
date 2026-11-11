"""Small in-memory index with an explicitly supplied embedding provider."""

import re


def split_text(text, limit=300):
    parts = re.split(r"(?<=[。！？；\n])", text)
    chunk = ""
    for part in parts:
        if chunk and len(chunk) + len(part) > limit:
            yield chunk
            chunk = ""
        while len(part) > limit:
            if chunk:
                yield chunk
                chunk = ""
            yield part[:limit]
            part = part[limit:]
        chunk += part
    if chunk.strip():
        yield chunk


class SemanticIndex:
    def __init__(self, evidence, embedder=None):
        from .embeddings import configured_embedder
        self.model = embedder if embedder is not None else configured_embedder()
        self.keys, texts = [], []
        for key, item in evidence.items():
            heading = " / ".join((item.document_title, item.title, item.topic))
            sections = item.table_parts or tuple(split_text(item.text)) or ("",)
            for section in sections:
                self.keys.append(key)
                texts.append(heading + "\n" + section)
        self.vectors = []
        for offset in range(0, len(texts), 32):
            self.vectors.extend(self.model.embed(texts[offset:offset + 32]))
        dimensions = {len(vector) for vector in self.vectors}
        if len(dimensions) > 1:
            raise ValueError("不同批次的 Embedding 维度不一致")

    def search(self, query, allowed_ids, limit=5, minimum_score=0.5):
        vector = self.model.embed([self.model.query_prefix + query])[0]
        if self.vectors and len(vector) != len(self.vectors[0]):
            raise ValueError("查询与索引的 Embedding 维度不一致")
        scores = {}
        for key, stored in zip(self.keys, self.vectors):
            value = sum(left * right for left, right in zip(stored, vector))
            if key in allowed_ids and value >= minimum_score:
                scores[key] = max(scores.get(key, 0), float(value))
        return sorted(scores, key=lambda key: (-scores[key], key))[:limit]
