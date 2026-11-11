"""Bounded decision loop, source coverage checks and failure reporting."""

from .citations import validate_citations
from .documents import normalize
from .model import DecisionModel, ModelError
from .prompts import DECIDE, REVIEW
from .retrieval import DocumentTools, ToolError


STATUSES = {"answered", "conflict", "needs_clarification", "insufficient_evidence"}


class KnowledgeAgent:
    def __init__(self, tools: DocumentTools, model: DecisionModel, max_steps: int = 18):
        if not isinstance(max_steps, int) or max_steps < 1:
            raise ValueError("max_steps 必须为正整数")
        self.tools = tools
        self.model = model
        self.max_steps = max_steps

    def ask(self, question: str, history: list[dict] | None = None) -> dict:
        history = [{key: turn[key] for key in ("role", "content")}
                   for turn in (history or [])[-8:]]
        state = {"question": question, "history": history, "observations": []}
        trace = []
        candidates, sources, checked, failures = {}, {}, {}, {}
        searches = set()
        step, decision = 0, {}

        def observe(action, **fields):
            event = {"step": step, "decision": decision, "action": action, **fields}
            state["observations"].append(event)
            trace.append(event)

        def result(status, answer, gaps, citations=()):
            return dict(status=status, answer=answer, gaps=gaps,
                        citations=list(citations), trace=trace)

        def blocked():
            observe("stopped", status="tool_error")
            return result("tool_error", "有资料或查证操作无法完成，暂时无法核实结论。",
                          list(failures.values()))

        for step in range(1, self.max_steps + 1):
            decision = {}
            try:
                action = self.model.decide(DECIDE, state, list(sources.values()))
                name = action.get("action")
                decision = {
                    "action": name,
                    "parameters": {key: action[key] for key in ("query", "queries", "doc_id", "topic", "id")
                                   if key in action},
                    "reason": action.get("reason", "未提供简要决策依据"),
                }
                reason = action.get("reason")
                if not isinstance(reason, str) or not reason.strip() or len(reason) > 300:
                    raise ValueError("每个动作必须提供 1 到 300 字符的 reason 操作依据摘要")
                if name == "finish":
                    answer, status, gaps = action.get("answer"), action.get("status"), action.get("gaps")
                    if (not isinstance(status, str) or status not in STATUSES
                            or not isinstance(answer, str) or not answer.strip()
                            or not isinstance(gaps, list)
                            or not all(isinstance(gap, str) for gap in gaps)):
                        raise ValueError("请使用有效状态、答复和资料缺口字段")
                    if failures:
                        return blocked()
                    citations = validate_citations(action.get("citations"), sources)
                    basis = action.get("basis", "evidence")
                    if basis not in ("evidence", "conversation"):
                        raise ValueError("basis 必须是 evidence 或 conversation")
                    if basis == "conversation" and (citations or status not in {"answered", "needs_clarification"}):
                        raise ValueError("直接回复仅用于无引文的寒暄、能力说明或纯澄清")
                    if basis == "evidence" and not searches:
                        raise ValueError("制度和产品事实必须先在本轮检索")
                    if status == "insufficient_evidence" and not citations and len(searches) < 2:
                        raise ValueError("资料不足时请改写并补搜")
                    if basis == "evidence" and status == "answered" and not citations:
                        raise ValueError("确定性答案必须有已读引用")
                    if status == "conflict" and len({item["id"] for item in citations}) < 2:
                        raise ValueError("冲突必须引用至少两处不同的证据")
                    pending = self._pending(citations, sources, checked)
                    if pending:
                        raise ValueError("仍需查证：" + "、".join(pending))
                    review = self.model.decide(
                        REVIEW, {"question": question, "history": history,
                                 "draft": {**action, "basis": basis}, "citations": citations,
                                 "observations": state["observations"],
                                 "sources": [self._read_record(source) for source in sources.values()]},
                        list(sources.values()),
                    )
                    if review.get("ok") is not True:
                        feedback = review.get("feedback")
                        raise ValueError(feedback if isinstance(feedback, str) else "证据审核未通过")
                    observe("review", ok=True)
                    return result(status, answer, gaps, citations)

                args = self._tool_args(name, action, candidates, sources)
                if args in failures:
                    observe(name, error=failures[args], retry_exhausted=True)
                    continue
                for attempt in (1, 2):
                    try:
                        if name == "read":
                            source = self.tools.read_chunk(args[1])
                            sources[args[1]] = source
                            observe(name, **self._read_record(source))
                        else:
                            if name == "topic":
                                items = self.tools.search_topic(args[1])
                                checked[args[1]] = {item.id for item in items}
                            else:
                                options = {"queries": action["queries"]} if action.get("queries") else {}
                                bundle = self.tools.search_evidence(args[1], args[2], **options)
                                candidates.update(bundle["candidates"])
                                sources.update(bundle["sources"])
                                checked.update(bundle["checked"])
                                for key, error in bundle["errors"].items():
                                    failures[("read", key, None)] = error
                                for event in bundle["attempts"]:
                                    observe(event["action"], **{key: value for key, value in event.items()
                                                               if key != "action"})
                                items = bundle["hits"]
                                searches.update(normalize(query) for query in bundle["queries"])
                                observe("evidence", sources=[self._read_record(source)
                                        for source in bundle["sources"].values()],
                                        pending=bundle["pending"],
                                        errors=bundle["errors"],
                                        checked_topics=list(bundle["checked"]),
                                        queries=bundle["queries"])
                            candidates.update((item.id, item) for item in items)
                            observe(name, query=args[1], doc_id=args[2],
                                    hits=[item.candidate() for item in items])
                        break
                    except (ToolError, OSError) as error:
                        observe(name, target=args[1], error=str(error), attempt=attempt)
                        if attempt == 2:
                            failures[args] = str(error)
            except ValueError as error:
                observe("feedback", message=str(error))
            except ModelError as error:
                observe("model_error", code=error.code, error=str(error))
                return result("tool_error", "模型调用失败，暂时无法核实结论。", [str(error)])

        if failures:
            return blocked()
        observe("budget_exhausted", max_steps=self.max_steps)
        return result("incomplete", "已达到执行步数上限，任务尚未完成。",
                      ["查证次数已达上限，请缩小问题范围或补充材料。"])

    @staticmethod
    def _tool_args(name, action, candidates, sources):
        if name == "search":
            query, doc_id = action.get("query"), action.get("doc_id")
            queries = action.get("queries", [])
            if (not isinstance(queries, list) or len(queries) > 3
                    or any(not isinstance(value, str) or not normalize(value) or len(value) > 500
                           for value in queries)):
                raise ValueError("queries 必须是最多三个非空字符串，每项最多 500 字符")
            if isinstance(query, str) and normalize(query) and (doc_id is None or isinstance(doc_id, str)):
                return name, " ".join(query.split()), doc_id
        if name == "topic":
            topic = action.get("topic")
            if isinstance(topic, str) and (
                    any(item.topic == topic for item in candidates.values()) or
                    any(source.evidence.topic == topic for source in sources.values())):
                return name, topic, None
        if name == "read":
            key = action.get("id")
            if isinstance(key, str) and (key in candidates or
                    any(key in source.evidence.links for source in sources.values())):
                return name, key, None
        raise ValueError("无效动作或参数。读取对象须来自检索结果或已读片段的链接。")

    @staticmethod
    def _read_record(source):
        item = source.evidence
        record = {**item.candidate(), "links": item.links}
        if source.image is None:
            record["text"] = item.text
        else:
            record["has_original_image"] = True
        return record

    @staticmethod
    def _pending(citations, sources, checked):
        keys = {item["id"] for item in citations}
        for candidates in checked.values():
            keys.update(candidates)
        pending = set()
        inspected = set()
        while keys:
            key = keys.pop()
            if key in inspected:
                continue
            inspected.add(key)
            if key not in sources:
                pending.add(key)
                continue
            item = sources[key].evidence
            if item.topic not in checked:
                pending.add(f"主题 {item.topic}")
            else:
                keys.update(checked[item.topic] - inspected)
            keys.update(set(item.links) - inspected)
        return sorted(pending)
