from dataclasses import replace
from pathlib import Path
import unittest

from knowledge_agent.agent import KnowledgeAgent
from knowledge_agent.documents import load_documents
from knowledge_agent.model import ModelError
from knowledge_agent.prompts import REVIEW
from knowledge_agent.retrieval import DocumentTools, ToolError


TERM = "D01@2025-01-01/section-4"
LATE = "D01@2025-01-01/section-5"
TABLE = "D02@2025-01-01/table-1"
FIGURE = "D03@2025-01-01/figure-1"
SCOPE = "D04@2025-01-01/scope"
QUOTE = "员工应在费用发生后 30 天内提交报销申请。"
TABLE_QUOTE = "事项：费用报销 | 起算点：费用发生日 | 提交期限：15 天"
LATE_QUOTE = "逾期报销申请需提交书面说明，由财务负责人审核。"
SCOPE_QUOTE = "自 2025 年 1 月 1 日起，D02 的期限替代 D01 第四条，适用于全部费用报销。"
QUESTION = "报销期限多久？"


def search(query):
    return {"action": "search", "query": query}


def topic(value):
    return {"action": "topic", "topic": value}


def read(key):
    return {"action": "read", "id": key}


def finish(status, answer, *citations, gaps=()):
    return {"action": "finish", "status": status, "answer": answer, "gaps": list(gaps),
            "citations": [{"id": key, "quote": quote} for key, quote in citations]}


class ScriptedModel:
    def __init__(self, actions, reviews=()):
        self.actions = iter(actions)
        self.reviews = iter(reviews)
        self.states = []
        self.images = []

    def decide(self, instructions, state, sources):
        if instructions == REVIEW:
            return next(self.reviews, {"ok": True})
        self.states.append(state)
        self.images = [source.image for source in sources if source.image]
        return {"reason": "离线预设动作，仅验证流程", **next(self.actions)}


class FailingReadTools(DocumentTools):
    def read_chunk(self, key):
        if key == TABLE:
            raise ToolError("D02 原表读取失败")
        return super().read_chunk(key)


class BudgetTools(DocumentTools):
    def search_evidence(self, query, doc_id=None):
        return super().search_evidence(query, doc_id, max_sources=0)


class AcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.index = load_documents(Path(__file__).resolve().parents[1] / "data")

    def single(self):
        return {TERM: self.index[TERM], LATE: self.index[LATE]}

    def execute(self, *actions, index=None, tools_class=DocumentTools,
                question=QUESTION, history=None, reviews=()):
        model = ScriptedModel(actions, reviews)
        tools = tools_class(self.index if index is None else index)
        return KnowledgeAgent(tools, model).ask(question, history), model

    def test_clear_answer_changes_when_source_changes(self):
        for value in ("30 天", "45 天"):
            with self.subTest(value=value):
                quote = QUOTE.replace("30 天", value)
                index = {**self.single(), TERM: replace(self.index[TERM], text=quote)}
                result, _ = self.execute(
                    search("费用报销 提交期限"), topic("报销提交期限"), read(TERM),
                    finish("answered", quote, (TERM, quote)), index=index,
                )
                self.assertEqual(result["status"], "answered")
                self.assertIn(value, result["answer"])
                self.assertEqual(result["citations"][0]["quote"], quote)

    def test_conflict_blocks_answer_before_both_sources_are_read(self):
        result, _ = self.execute(
            search("费用报销 提交期限"), topic("报销提交期限"), read(TERM),
            finish("answered", QUOTE, (TERM, QUOTE)), read(TABLE),
            finish("conflict", "D01 是 30 天，D02 是 15 天。请确认适用制度。",
                   (TERM, QUOTE), (TABLE, TABLE_QUOTE), gaps=("适用制度",)),
            index={TERM: self.index[TERM], TABLE: self.index[TABLE]}, tools_class=BudgetTools,
        )
        self.assertEqual(result["status"], "conflict")
        self.assertEqual({x["doc_id"] for x in result["citations"]}, {"D01", "D02"})
        self.assertTrue(any(TABLE in x.get("message", "") for x in result["trace"]))

    def test_cross_document_footnote_resolves_conflict(self):
        index = dict(self.index)
        index[TABLE] = replace(index[TABLE], text=TABLE_QUOTE + "\n适用范围见 D04。",
                               links=(SCOPE,))
        index[SCOPE] = replace(index[TERM], id=SCOPE, doc_id="D04", topic="制度适用范围",
                               text=SCOPE_QUOTE)
        result, _ = self.execute(
            search("费用报销 提交期限"), topic("报销提交期限"), read(TERM), read(TABLE),
            read(SCOPE), topic("制度适用范围"),
            finish("answered", "费用发生后 15 天内提交。", (TABLE, TABLE_QUOTE), (SCOPE, SCOPE_QUOTE)),
            index=index,
        )
        self.assertEqual(result["status"], "answered")
        self.assertEqual([x["id"] for x in result["citations"]], [TABLE, SCOPE])

    def test_outside_corpus(self):
        result, _ = self.execute(
            search("育儿假"), search("子女照护假期"),
            finish("insufficient_evidence", "附件缺少育儿假规定。", gaps=("育儿假制度",)),
            question="有多少天育儿假？",
        )
        self.assertEqual(result["status"], "insufficient_evidence")
        self.assertFalse(result["citations"])
        self.assertTrue(all(not action["hits"] for action in result["trace"]
                            if action["action"] == "search"))

    def test_paraphrase_search(self):
        question = "发票拿到手以后最晚何时能交？"
        result, _ = self.execute(
            search(question), search("费用报销 提交期限"), topic("报销提交期限"), read(TERM),
            finish("answered", QUOTE, (TERM, QUOTE)), index=self.single(), question=question,
        )
        self.assertEqual(result["status"], "answered")
        self.assertTrue(any(TERM == hit["id"] for event in result["trace"] if event["action"] == "search" for hit in event["hits"]))

    def test_follow_up_uses_current_source(self):
        history = [{"role": "user", "content": QUESTION},
                   {"role": "assistant", "content": QUOTE}]
        result, model = self.execute(
            search("逾期报销"), topic("逾期报销"), read(LATE),
            finish("answered", LATE_QUOTE, (LATE, LATE_QUOTE)),
            question="那超过了还能报吗？", history=history,
        )
        self.assertEqual(model.states[0]["history"], history)
        self.assertEqual(result["citations"][0]["id"], LATE)

    def test_failed_read_has_two_attempts_and_never_returns_answer(self):
        result, _ = self.execute(
            search("报销提交期限"), topic("报销提交期限"), read(TERM), read(TABLE),
            finish("insufficient_evidence", "无法回答。"), tools_class=FailingReadTools,
        )
        self.assertEqual(result["status"], "tool_error")
        self.assertEqual([x["attempt"] for x in result["trace"] if "attempt" in x], [1, 2])
        self.assertIn("D02", result["gaps"][0])

    def test_transient_read_failure_recovers(self):
        class OnceFailingTools(DocumentTools):
            failed = False

            def read_chunk(self, key):
                if not self.failed:
                    self.failed = True
                    raise ToolError("暂时无法读取")
                return super().read_chunk(key)

        result, _ = self.execute(
            search("费用报销 提交期限"), topic("报销提交期限"), read(TERM),
            finish("answered", QUOTE, (TERM, QUOTE)),
            index=self.single(), tools_class=OnceFailingTools,
        )
        self.assertEqual(result["status"], "answered")
        self.assertEqual([x["attempt"] for x in result["trace"] if "attempt" in x], [1])

    def test_bad_quote_and_semantic_review_feedback(self):
        result, _ = self.execute(
            search("费用报销 提交期限"), topic("报销提交期限"), read(TERM),
            finish("answered", "15 天", (TERM, "15 天")),
            finish("answered", "收到发票后 30 天。", (TERM, QUOTE)),
            finish("answered", QUOTE, (TERM, QUOTE)),
            index=self.single(), reviews=({"ok": False, "feedback": "起算点错误"},),
        )
        self.assertEqual(result["answer"], QUOTE)
        self.assertEqual(len([x for x in result["trace"] if x["action"] == "feedback"]), 2)

    def test_flow_chart_uses_original_image(self):
        result, model = self.execute(
            search("费用审批流程"), topic("费用审批流程"), read(FIGURE),
            finish("answered", "部门主管审批后进入财务复核。", (FIGURE, "")),
            question="部门主管审批后去哪一步？",
        )
        self.assertEqual(result["status"], "answered")
        self.assertTrue(model.images[0].startswith(b"\x89PNG"))
        self.assertEqual(result["citations"][0]["asset"], "approval-flow.png")
        self.assertEqual(result["citations"][0]["page"], 1)

    def test_unfinished_topic_blocks_no_citation_draft(self):
        result, _ = self.execute(
            search("费用报销 提交期限"), search("最晚提交时间"), topic("报销提交期限"),
            read(TERM),
            finish("insufficient_evidence", "附件里找不到报销期限。"),
            read(TABLE),
            finish("conflict", "D01 是 30 天，D02 是 15 天。请确认适用制度。",
                   (TERM, QUOTE), (TABLE, TABLE_QUOTE), gaps=("适用制度",)),
            index={TERM: self.index[TERM], TABLE: self.index[TABLE]}, tools_class=BudgetTools,
        )
        self.assertEqual(result["status"], "conflict")
        self.assertTrue(any(TABLE in event.get("message", "") for event in result["trace"]))

    def test_cosmetic_query_changes_do_not_count_as_a_new_search(self):
        result, _ = self.execute(
            search("育儿假"), search("育儿假？"),
            finish("insufficient_evidence", "暂未找到制度。"),
            search("子女照护假期"),
            finish("insufficient_evidence", "附件缺少育儿假规定。"),
            question="有多少天育儿假？",
        )
        self.assertEqual(result["status"], "insufficient_evidence")
        self.assertTrue(any("补搜" in event.get("message", "") for event in result["trace"]))

    def test_model_failure_is_structured(self):
        class UnavailableModel:
            def decide(self, instructions, state, sources):
                raise ModelError("模型接口不可用")

        result = KnowledgeAgent(DocumentTools(self.index), UnavailableModel()).ask(QUESTION)
        self.assertEqual(result["status"], "tool_error")
        self.assertFalse(result["citations"])


if __name__ == "__main__":
    unittest.main()

class EvidenceBundleTests(unittest.TestCase):
    def test_one_search_supports_conflict_answer(self):
        index = load_documents(Path(__file__).resolve().parents[1] / "data")
        model = ScriptedModel([
            search("报销期限"),
            finish("conflict", "D01 是 30 天，D02 是 15 天，请确认适用制度。",
                   (TERM, QUOTE), (TABLE, TABLE_QUOTE)),
        ])
        result = KnowledgeAgent(DocumentTools(index), model).ask(QUESTION)
        self.assertEqual(result["status"], "conflict")
        self.assertEqual([event["action"] for event in result["trace"]],
                         ["evidence", "search", "review"])

    def test_search_expands_replacement_links(self):
        root = Path(__file__).resolve().parents[1] / "data"
        index = load_documents(root)
        index.update(load_documents(root / "variants" / "replacement"))
        bundle = DocumentTools(index).search_evidence("报销期限")
        self.assertIn("D04@2025-01-01/scope", bundle["sources"])
        self.assertFalse(bundle["pending"])
        self.assertFalse(bundle["errors"])

class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.tools = DocumentTools(load_documents(Path(__file__).resolve().parents[1] / "data"))

    def test_greeting_can_finish_without_search(self):
        action = {**finish("answered", "你好，可以告诉我你想查什么制度或产品问题。"),
                  "basis": "conversation"}
        result = KnowledgeAgent(self.tools, ScriptedModel([action])).ask("你好")
        self.assertEqual(result["status"], "answered")
        self.assertEqual([step["action"] for step in result["trace"]], ["review"])

    def test_policy_claim_without_search_is_blocked(self):
        model = ScriptedModel([
            finish("answered", "期限是30天"),
            search("报销期限"),
            finish("conflict", "30天与15天冲突，请确认适用制度。",
                   (TERM, QUOTE), (TABLE, TABLE_QUOTE)),
        ])
        result = KnowledgeAgent(self.tools, model).ask(QUESTION)
        self.assertEqual(result["status"], "conflict")
        self.assertIn("本轮检索", result["trace"][0]["message"])

    def test_direct_mode_does_not_skip_semantic_review(self):
        model = ScriptedModel([
            {**finish("answered", "报销期限30天"), "basis": "conversation"},
            search("报销期限"),
            finish("conflict", "30天与15天冲突，请确认适用制度。",
                   (TERM, QUOTE), (TABLE, TABLE_QUOTE)),
        ], reviews=[{"ok": False, "feedback": "制度事实需先检索并引用"}])
        result = KnowledgeAgent(self.tools, model).ask(QUESTION)
        self.assertEqual(result["status"], "conflict")
        self.assertEqual(result["trace"][0]["message"], "制度事实需先检索并引用")

class QueryBudgetTests(unittest.TestCase):
    def test_distinct_expansions_satisfy_supplementary_search(self):
        index = load_documents(Path(__file__).resolve().parents[1] / "data")
        model = ScriptedModel([
            {"action": "search", "query": "育儿假", "queries": ["子女照护假"]},
            finish("insufficient_evidence", "本轮未找到育儿假规定。"),
        ])
        result = KnowledgeAgent(DocumentTools(index), model).ask("育儿假几天？")
        self.assertEqual(result["status"], "insufficient_evidence")
        self.assertEqual(sum(step["action"] == "search" for step in result["trace"]), 1)

class BudgetLimitTests(unittest.TestCase):
    def test_step_limit_reports_incomplete(self):
        index = load_documents(Path(__file__).resolve().parents[1] / "data")
        action = {**search("报销期限"), "reason": "需要读取期限原文"}
        result = KnowledgeAgent(DocumentTools(index), ScriptedModel([action]), max_steps=1).ask(QUESTION)
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(result["trace"][-1]["action"], "budget_exhausted")
        self.assertEqual(result["trace"][0]["decision"]["reason"], "需要读取期限原文")
        self.assertEqual(result["trace"][0]["step"], 1)
