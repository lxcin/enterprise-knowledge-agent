import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from knowledge_agent.documents import load_documents
from knowledge_agent.embeddings import APIEmbedder, LocalEmbedder, normalized_vectors
from knowledge_agent.retrieval import DocumentTools


class EmbeddingTests(unittest.TestCase):
    def setUp(self):
        self.documents = load_documents(Path(__file__).resolve().parents[1] / "data")

    def test_keyword_mode_requires_no_embedding_configuration(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertTrue(DocumentTools(self.documents).search_docs("报销"))

    def test_semantic_mode_requires_explicit_provider(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(ValueError, "EMBEDDING_PROVIDER"):
                DocumentTools(self.documents, semantic=True)

    def test_model_name_is_not_treated_as_a_local_cache_lookup(self):
        with self.assertRaisesRegex(ValueError, "模型目录"):
            LocalEmbedder("nonexistent-vendor/nonexistent-model")

    def test_api_reorders_and_normalizes_vectors(self):
        body = {"data": [{"index": 1, "embedding": [0, 2]},
                         {"index": 0, "embedding": [3, 0]}]}
        with patch("knowledge_agent.embeddings.urlopen",
                   return_value=io.BytesIO(json.dumps(body).encode())) as request:
            rows = APIEmbedder("https://example.invalid/v1", "test").embed(["one", "two"])
        self.assertEqual(rows, [[1, 0], [0, 1]])
        self.assertEqual(request.call_args.args[0].full_url, "https://example.invalid/v1/embeddings")

    def test_invalid_vectors_fail_explicitly(self):
        for rows in ([[0, 0]], [[float("nan"), 1]], [[1], [1, 2]]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                normalized_vectors(rows, len(rows))

    def test_injected_provider_builds_index_without_model_libraries(self):
        class Provider:
            query_prefix = ""
            def embed(self, texts):
                return [[1.0, 0.0] for text in texts]

        tools = DocumentTools(self.documents, embedder=Provider())
        self.assertTrue(tools.search_docs("different wording"))
