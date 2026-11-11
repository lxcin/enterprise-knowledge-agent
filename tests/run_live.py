"""Replay the published live cases and keep actual results with full traces."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import sys

from knowledge_agent.agent import KnowledgeAgent
from knowledge_agent.documents import load_documents
from knowledge_agent.model import ChatModel
from knowledge_agent.retrieval import DocumentTools, ToolError


ROOT = Path(__file__).resolve().parents[1]


class SimulatedReadFailure(DocumentTools):
    def __init__(self, evidence, failed_id):
        super().__init__(evidence)
        self.failed_id = failed_id

    def read_chunk(self, key):
        if key == self.failed_id:
            raise ToolError(f"验收模拟：原文持续读取失败 {key}")
        return super().read_chunk(key)


def run_case(case, model):
    evidence = load_documents(ROOT / "data")
    for directory in case.get("overlays", []):
        overlay = load_documents(ROOT / directory)
        replaced_ids = {item.doc_id for item in overlay.values()}
        evidence = {key: item for key, item in evidence.items() if item.doc_id not in replaced_ids}
        evidence.update(overlay)
    evidence = {key: item for key, item in evidence.items() if item.doc_id in case["doc_ids"]}
    fault = case.get("fail_read")
    tools = SimulatedReadFailure(evidence, fault) if fault else DocumentTools(evidence)
    actual = KnowledgeAgent(tools, model).ask(case["question"], case.get("history"))
    citations = actual["citations"]
    checks = {
        "status": actual["status"] in case["expected_status"],
        "required_quotes": all(any(quote in item["quote"] for item in citations)
                               for quote in case.get("required_quotes", [])),
        "no_citations_when_expected": not citations if case.get("no_citations") else True,
    }
    if fault:
        attempts = [item["attempt"] for item in actual["trace"]
                    if item.get("target") == fault and "attempt" in item]
        checks["read_retried"] = attempts == [1, 2]
    return {"id": case["id"], "model": model.model, "checks": checks, "actual": actual}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", action="append", help="Run only the specified case ID")
    parser.add_argument("--workers", type=int, default=3, choices=(1, 2, 3))
    args = parser.parse_args()
    endpoint, model_id = os.environ.get("KNOWLEDGE_BASE_URL"), os.environ.get("KNOWLEDGE_MODEL")
    key = os.environ.get("KNOWLEDGE_API_KEY")
    if endpoint and endpoint.rstrip("/") in {"https://api.deepseek.com", "https://api.deepseek.com/v1"}:
        key = key or os.environ.get("DEEPSEEK_API_KEY")
    if not endpoint or not model_id or not key:
        parser.error("配置 KNOWLEDGE_BASE_URL、KNOWLEDGE_MODEL 和 API 密钥")
    cases = json.loads((ROOT / "examples" / "live-inputs.json").read_text(encoding="utf-8"))
    if args.case:
        requested = set(args.case)
        if unknown := requested - {case["id"] for case in cases}:
            parser.error("未知用例：" + ", ".join(sorted(unknown)))
        cases = [case for case in cases if case["id"] in requested]
    model = ChatModel(endpoint, model_id, key)
    passed = True
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        for result in executor.map(lambda case: run_case(case, model), cases):
            print(json.dumps(result, ensure_ascii=False), flush=True)
            passed &= all(result["checks"].values())
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
