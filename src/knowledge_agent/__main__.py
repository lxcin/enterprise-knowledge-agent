"""Command line entry point with optional conversation history."""

import argparse
import json
import os
from pathlib import Path

from .agent import KnowledgeAgent
from .documents import load_documents
from .model import ChatModel
from .retrieval import DocumentTools


def main():
    parser = argparse.ArgumentParser(description="企业知识问答 Agent")
    parser.add_argument("question", help="本轮问题")
    parser.add_argument("--docs", type=Path, default=Path("data"))
    parser.add_argument("--history", type=Path, help="role/content 格式的 JSON 对话历史")
    parser.add_argument("--trace", action="store_true", help="输出查证动作和读取结果")
    parser.add_argument("--semantic", action="store_true", help="启用已配置的向量后端与关键词混合召回")
    parser.add_argument("--max-steps", type=int, default=18, help="决策步数上限，至少为 1")
    args = parser.parse_args()
    if args.max_steps < 1:
        parser.error("--max-steps 至少为 1")
    endpoint, model = os.environ.get("KNOWLEDGE_BASE_URL"), os.environ.get("KNOWLEDGE_MODEL")
    if not endpoint or not model:
        parser.error("请设置 KNOWLEDGE_BASE_URL 和 KNOWLEDGE_MODEL")
    try:
        documents = load_documents(args.docs)
        history = json.loads(args.history.read_text(encoding="utf-8-sig")) if args.history else []
        if not isinstance(history, list) or not all(
            isinstance(turn, dict) and turn.get("role") in ("user", "assistant")
            and isinstance(turn.get("content"), str) for turn in history
        ):
            raise ValueError("对话历史应为包含 role 和 content 的数组")
        tools = DocumentTools(documents, semantic=args.semantic)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.error(str(error))
    agent = KnowledgeAgent(tools,
                           ChatModel(endpoint, model, os.environ.get("KNOWLEDGE_API_KEY", "")),
                           max_steps=args.max_steps)
    result = agent.ask(args.question, history)
    if not args.trace:
        result.pop("trace")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
