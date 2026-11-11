"""Optional model adapter. The agent itself only depends on the decision protocol."""

import base64
import json
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .retrieval import Source


class ModelError(Exception):
    def __init__(self, message, code="model_error"):
        super().__init__(message)
        self.code = code


class DecisionModel(Protocol):
    def decide(self, instructions: str, state: dict, sources: list[Source]) -> dict: ...


class ChatModel:
    def __init__(self, endpoint: str, model: str, api_key: str = ""):
        self.endpoint = endpoint.rstrip("/") + "/chat/completions"
        self.model = model
        self.api_key = api_key

    def decide(self, instructions: str, state: dict, sources: list[Source]) -> dict:
        content = [{"type": "text", "text": json.dumps(state, ensure_ascii=False)}]
        for source in sources:
            if source.image is None:
                continue
            mime = "image/png" if source.evidence.asset.suffix.lower() == ".png" else "image/jpeg"
            encoded = base64.b64encode(source.image).decode("ascii")
            content += [
                {"type": "text", "text": f"原图对应片段 ID：{source.evidence.id}"},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}},
            ]
        payload = {"model": self.model, "response_format": {"type": "json_object"},
                   "messages": [{"role": "system", "content": instructions},
                                {"role": "user", "content": content}]}
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = Request(self.endpoint, json.dumps(payload).encode("utf-8"), headers)
        try:
            with urlopen(request, timeout=60) as response:
                result = json.load(response)
        except HTTPError as error:
            raise ModelError(f"模型接口 HTTP {error.code}", "http_error") from error
        except TimeoutError as error:
            raise ModelError("模型接口请求超时", "timeout") from error
        except URLError as error:
            if isinstance(error.reason, TimeoutError):
                raise ModelError("模型接口请求超时", "timeout") from error
            raise ModelError("无法连接模型接口", "network_error") from error
        except OSError as error:
            raise ModelError("模型连接中断", "network_error") from error
        except (ValueError, UnicodeError) as error:
            raise ModelError("模型接口响应不是有效 JSON", "invalid_response") from error

        try:
            choice = result["choices"][0]
            content = choice["message"]["content"]
            reason = choice.get("finish_reason")
        except (KeyError, IndexError, TypeError, AttributeError) as error:
            raise ModelError("模型接口响应结构无效", "invalid_response") from error
        if reason == "length":
            raise ModelError("模型输出因长度限制被截断", "truncated_response")
        if content is None or isinstance(content, str) and not content.strip():
            raise ModelError("模型返回空内容", "empty_response")
        if not isinstance(content, str):
            raise ModelError("模型输出内容类型无效", "invalid_response")
        try:
            decision = json.loads(content)
        except ValueError as error:
            raise ModelError("模型输出不是有效动作 JSON", "invalid_json") from error
        if not isinstance(decision, dict):
            raise ModelError("模型未返回 JSON 对象", "invalid_action")
        return decision
