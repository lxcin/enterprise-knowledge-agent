from dataclasses import replace
from pathlib import Path
import unittest

from knowledge_agent.documents import load_documents
from knowledge_agent.retrieval import DocumentTools


class RetrievalTests(unittest.TestCase):
    def setUp(self):
        self.index = load_documents(Path(__file__).resolve().parents[1] / "data")
        self.tools = DocumentTools(self.index)

    def test_lookup_by_full_width_document_id(self):
        hits = self.tools.search_docs("Ｄ０２")
        self.assertEqual([item.doc_id for item in hits], ["D02"])

    def test_reference_id_is_prioritized_even_with_other_keywords(self):
        hits = self.tools.search_docs("D02 费用报销")
        self.assertEqual(hits[0].doc_id, "D02")
        self.assertTrue(any(item.doc_id == "D01" for item in hits))

    def test_exact_source_lookup_respects_document_scope(self):
        key = "D02@2025-01-01/table-1"
        self.assertEqual([item.id for item in self.tools.search_docs(key, "ｄ０２")], [key])
        self.assertEqual(self.tools.search_docs(key, "D01"), [])

    def test_table_ranking_prefers_terms_in_the_same_row(self):
        source = self.index["D02@2025-01-01/table-1"]
        unrelated_rows = ("类别：差旅 | 条件：主管审批", "类别：采购 | 条件：财务复核")
        related_rows = ("类别：差旅 | 条件：财务复核",)
        scattered = replace(source, id="A", text="\n".join(unrelated_rows),
                            table_parts=unrelated_rows)
        matching = replace(source, id="B", text="\n".join(related_rows),
                           table_parts=related_rows)
        tools = DocumentTools({"A": scattered, "B": matching})
        self.assertEqual([item.id for item in tools.search_docs("差旅 财务复核")], ["B", "A"])
        self.assertEqual(tools.read_chunk("A").evidence.text, "\n".join(unrelated_rows))

    def test_english_question_expands_to_chinese_evidence(self):
        self.assertFalse(self.tools.search_docs("expense submission deadline"))
        bundle = self.tools.search_evidence(
            "expense submission deadline", queries=["报销提交期限", "费用报销制度说明起算日期"])
        self.assertIn("D01@2025-01-01/section-4", bundle["sources"])
        self.assertIn("D02@2025-01-01/table-1", bundle["sources"])
        self.assertEqual(bundle["queries"][0], "expense submission deadline")

    def test_chinese_question_finds_english_policy(self):
        original = next(iter(self.index.values()))
        english = replace(original, id="EN/retention", doc_id="EN", title="Archive policy",
                          document_title="Records policy", topic="Retention",
                          text="Archived records are retained for seven years.")
        tools = DocumentTools({english.id: english})
        self.assertFalse(tools.search_docs("档案保存多久"))
        bundle = tools.search_evidence("档案保存多久", queries=["archive records retention"])
        self.assertIn(english.id, bundle["sources"])

    def test_hypothetical_description_cannot_be_cited(self):
        from knowledge_agent.citations import validate_citations
        hypothetical = "费用报销制度说明提交期限、起算日期和逾期申请流程"
        bundle = self.tools.search_evidence("费用报销", queries=[hypothetical])
        key = "D01@2025-01-01/section-4"
        with self.assertRaises(ValueError):
            validate_citations([{"id": key, "quote": hypothetical}], bundle["sources"])

    def test_original_results_survive_unhelpful_expansion(self):
        bundle = self.tools.search_evidence("报销期限", queries=["unrelated ocean weather"])
        self.assertIn("D01@2025-01-01/section-4", bundle["sources"])
        self.assertIn("D02@2025-01-01/table-1", bundle["sources"])

    def test_semantic_chunking_preserves_text_and_size(self):
        from knowledge_agent.semantic import split_text
        text = "条款一。" + "长" * 650 + "。条款二。"
        chunks = list(split_text(text))
        self.assertEqual("".join(chunks), text)
        self.assertTrue(all(len(chunk) <= 300 for chunk in chunks))
