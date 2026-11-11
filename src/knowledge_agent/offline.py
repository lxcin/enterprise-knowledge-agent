"""Deterministic demonstration of the harness. No real model reasoning."""

import argparse
import json
from pathlib import Path

from .agent import KnowledgeAgent
from .documents import load_documents
from .prompts import REVIEW
from .retrieval import DocumentTools, ToolError


class DemoModel:
    def __init__(self, scenario):
        self.scenario = scenario

    def decide(self, instructions, state, sources):
        if instructions == REVIEW:
            return {"ok": True}
        searches = [event for event in state["observations"] if event["action"] == "search"]
        if not searches:
            return {"action": "search", "query": state["question"],
                    "reason": "离线固定流程：先查询样例资料"}
        if self.scenario == "missing" and len(searches) == 1:
            return {"action": "search", "query": "子女照护假",
                    "reason": "离线固定流程：换词检索缺失的政策"}
        by_id = {source.evidence.doc_id: source.evidence for source in sources
                 if source.evidence.topic == "报销提交期限"}
        citations = [{"id": item.id, "quote": item.text} for item in by_id.values()]
        if self.scenario == "normal":
            status, answer, gaps = "answered", by_id["D01"].text, []
        elif self.scenario == "conflict":
            status = "conflict"
            answer = "D01 为 30 天，D02 为 15 天，请确认适用制度。"
            gaps = ["适用范围与优先级"]
        else:
            status, answer, gaps = "insufficient_evidence", "无法核实该问题。", ["可用原文依据"]
            citations = []
        return {"action": "finish", "status": status, "answer": answer,
                "citations": citations, "gaps": gaps,
                "reason": "离线固定流程：按样例场景输出，模型审核同样为 Mock"}


class FailureTools(DocumentTools):
    def read_chunk(self, key):
        if self.evidence.get(key) and self.evidence[key].doc_id == "D02":
            raise ToolError("离线演示：D02 原文不可读")
        return super().read_chunk(key)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=("normal", "conflict", "missing", "tool-failure"),
                        default="normal")
    parser.add_argument("--docs", type=Path, default=Path("data"))
    args = parser.parse_args()
    evidence = load_documents(args.docs)
    allowed = {"D01"} if args.case == "normal" else {"D01", "D02"}
    evidence = {key: value for key, value in evidence.items() if value.doc_id in allowed}
    tools = FailureTools(evidence) if args.case == "tool-failure" else DocumentTools(evidence)
    question = "育儿假几天？" if args.case == "missing" else "报销期限多久？"
    result = KnowledgeAgent(tools, DemoModel(args.case)).ask(question)
    print(json.dumps({"execution_mode": "offline_mock",
                      "limitation": "预设动作和审核，仅验证流程；不代表真实模型决策能力。",
                      "case": args.case, "question": question, "actual": result},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
