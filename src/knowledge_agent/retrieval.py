"""Local keyword search and precise source reads."""

from dataclasses import dataclass
import re
from unicodedata import normalize as unicode_normalize

from .documents import Evidence, normalize


class ToolError(Exception):
    pass


@dataclass(frozen=True)
class Source:
    evidence: Evidence
    image: bytes | None = None


class DocumentTools:
    def __init__(self, evidence: dict[str, Evidence], semantic=False, embedder=None):
        self.evidence = evidence
        self.semantic = None
        if semantic or embedder is not None:
            from .semantic import SemanticIndex
            self.semantic = SemanticIndex(evidence, embedder)
        self.source_ids = {unicode_normalize("NFKC", key).casefold(): item
                           for key, item in evidence.items()}
        self.document_ids = {key: unicode_normalize("NFKC", item.doc_id).casefold()
                             for key, item in evidence.items()}
        self.fields = {
            key: (
                tuple(normalize(field) for field in (item.document_title, item.title, item.topic)),
                tuple(normalize(part) for part in (item.table_parts or (item.text,))),
            )
            for key, item in evidence.items()
        }

    def search_docs(self, query: str, doc_id: str | None = None):
        query = unicode_normalize("NFKC", query).casefold().strip()
        doc_id = unicode_normalize("NFKC", doc_id).casefold().strip() if doc_id else None
        exact = self.source_ids.get(query)
        if exact is not None:
            return [exact] if doc_id is None or self.document_ids[exact.id] == doc_id else []
        words = re.findall(r"[\u3400-\u9fff]+|[a-z0-9]+", query)
        terms = {word for word in words if len(word) >= 2 or word.isascii()}
        bigrams = {word[i:i+2] for word in words if not word.isascii()
                   for i in range(len(word) - 1)}
        ranked = []
        for key, (headings, sections) in self.fields.items():
            item_doc_id = self.document_ids[key]
            if doc_id and item_doc_id != doc_id:
                continue

            heading_terms = {term for term in terms if any(term in field for field in headings)}
            heading_bigrams = {term for term in bigrams if any(term in field for field in headings)}
            score = 12 * len(heading_terms) + 2 * len(heading_bigrams)
            # A table matches on its best row or footnote, with headings shared.
            body_score = max((8 * sum(term in section for term in terms - heading_terms)
                              + sum(term in section for term in bigrams - heading_bigrams)
                              for section in sections), default=0)
            identifier_match = query == item_doc_id or item_doc_id in terms
            if score or body_score or identifier_match:
                ranked.append((not identifier_match, -(score + body_score), key))
        lexical = [key for _, _, key in sorted(ranked)[:10]]
        if self.semantic is None:
            return [self.evidence[key] for key in lexical]
        allowed = {key for key in self.evidence if doc_id is None or self.document_ids[key] == doc_id}
        try:
            semantic = self.semantic.search(query, allowed)
        except (ValueError, OSError) as error:
            raise ToolError(str(error)) from error
        scores = {}
        for route in (lexical, semantic):
            for rank, key in enumerate(route, 1):
                scores[key] = scores.get(key, 0) + 1 / (60 + rank)
        ranked_keys = sorted(scores, key=lambda key: (-scores[key], key))
        return [self.evidence[key] for key in ranked_keys[:10]]

    def search_evidence(self, query, doc_id=None, max_sources=24, max_characters=24000, *, queries=()):
        """Return an auditable evidence bundle, including competing rules and links."""
        if not isinstance(queries, (list, tuple)) or len(queries) > 3:
            raise ValueError("queries 最多包含三个扩展查询")
        if any(not isinstance(value, str) or not normalize(value) or len(value) > 500
               for value in queries):
            raise ValueError("扩展查询必须是 1 到 500 字符的非空文本")
        actual_queries, seen = [], set()
        for value in (query, *queries):
            key = normalize(value)
            if key not in seen:
                seen.add(key)
                actual_queries.append(value)
        scores, retrieved = {}, {}
        for route, value in enumerate(actual_queries):
            weight = 1.0 if route == 0 else 0.7
            for rank, item in enumerate(self.search_docs(value, doc_id), 1):
                retrieved[item.id] = item
                scores[item.id] = scores.get(item.id, 0) + weight / (60 + rank)
        hits = [retrieved[key] for key in sorted(scores, key=lambda key: (-scores[key], key))]
        candidates = {item.id: item for item in hits}
        queue = list(candidates)
        checked, sources, errors, attempts = {}, {}, {}, []
        visited, characters = set(), 0
        while queue:
            key = queue.pop(0)
            if key in visited:
                continue
            visited.add(key)
            item = self.evidence.get(key)
            if item is not None:
                candidates[key] = item
                if item.topic not in checked:
                    siblings = self.search_topic(item.topic)
                    checked[item.topic] = {sibling.id for sibling in siblings}
                    candidates.update((sibling.id, sibling) for sibling in siblings)
                    queue.extend(sibling.id for sibling in siblings)
                queue.extend(item.links)
                if len(sources) >= max_sources or characters + len(item.text) > max_characters:
                    continue
            for attempt in (1, 2):
                try:
                    source = self.read_chunk(key)
                    sources[key] = source
                    characters += len(source.evidence.text)
                    break
                except (ToolError, OSError) as error:
                    attempts.append({"action": "read", "target": key,
                                     "error": str(error), "attempt": attempt})
                    if attempt == 2:
                        errors[key] = str(error)
        pending = sorted(visited - sources.keys() - errors.keys())
        return {"hits": hits, "candidates": candidates, "sources": sources,
                "checked": checked, "errors": errors, "attempts": attempts,
                "pending": pending, "queries": actual_queries}

    def search_topic(self, topic: str):
        # Intentionally exhaustive for the small, explicitly tagged corpus.
        return [item for item in self.evidence.values() if item.topic == topic]

    def read_chunk(self, key: str):
        item = self.evidence.get(key)
        if item is None:
            raise ToolError(f"未找到所引用的版本或片段：{key}")
        if item.asset is None:
            return Source(item)
        try:
            with item.asset.open("rb") as file:
                image = file.read(5 * 1024 * 1024 + 1)
        except OSError as error:
            raise ToolError(f"无法读取原图：{key}") from error
        if not image or len(image) > 5 * 1024 * 1024:
            raise ToolError(f"原图为空或超过 5 MiB：{key}")
        return Source(item, image)
