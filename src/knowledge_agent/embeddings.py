"""Optional embedding providers selected explicitly by deployment configuration."""

import json
import math
import os
from pathlib import Path
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class Embedder(Protocol):
    query_prefix: str

    def embed(self, texts: list[str]) -> list[list[float]]: ...


def normalized_vectors(rows, count):
    if not isinstance(rows, list) or len(rows) != count:
        raise ValueError("Embedding 返回数量与输入不一致")
    result, dimension = [], None
    for row in rows:
        if not isinstance(row, list) or not row:
            raise ValueError("Embedding 必须是非空向量")
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
               for value in row):
            raise ValueError("Embedding 包含无效数值")
        dimension = dimension or len(row)
        norm = math.sqrt(sum(value * value for value in row))
        if len(row) != dimension or not math.isfinite(norm) or norm == 0:
            raise ValueError("Embedding 维度或模长无效")
        result.append([value / norm for value in row])
    return result


class APIEmbedder:
    def __init__(self, base_url, model, api_key="", query_prefix=""):
        self.url = base_url.rstrip("/") + "/embeddings"
        self.model, self.api_key, self.query_prefix = model, api_key, query_prefix

    def embed(self, texts):
        payload = {"model": self.model, "input": texts, "encoding_format": "float"}
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = "Bearer " + self.api_key
        request = Request(self.url, json.dumps(payload).encode("utf-8"), headers)
        try:
            with urlopen(request, timeout=60) as response:
                data = json.load(response)["data"]
            if not isinstance(data, list):
                raise ValueError("Embedding data 必须是数组")
            indices = [item["index"] for item in data]
            if sorted(indices) != list(range(len(texts))):
                raise ValueError("Embedding 返回索引缺失或重复")
            rows = [item["embedding"] for item in sorted(data, key=lambda item: item["index"])]
            return normalized_vectors(rows, len(texts))
        except HTTPError as error:
            raise ValueError(f"Embedding 接口 HTTP {error.code}") from error
        except (URLError, TimeoutError, KeyError, TypeError) as error:
            raise ValueError("Embedding 调用失败或返回格式无效") from error


class LocalEmbedder:
    def __init__(self, model_path, query_prefix=""):
        path = Path(model_path).expanduser()
        if not path.is_dir():
            raise ValueError("EMBEDDING_MODEL_PATH 必须是明确提供的本地模型目录")
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as error:
            raise ValueError("本地模型后端需要安装项目的 local-vector 可选依赖") from error
        self.model = SentenceTransformer(str(path.resolve()), local_files_only=True, device="cpu")
        self.query_prefix = query_prefix

    def embed(self, texts):
        rows = self.model.encode(texts, show_progress_bar=False).tolist()
        return normalized_vectors(rows, len(texts))


def configured_embedder():
    provider = os.environ.get("EMBEDDING_PROVIDER", "")
    prefix = os.environ.get("EMBEDDING_QUERY_PREFIX", "")
    if provider == "api":
        base, model = os.environ.get("EMBEDDING_BASE_URL"), os.environ.get("EMBEDDING_MODEL")
        if not base or not model:
            raise ValueError("API 向量后端需要 EMBEDDING_BASE_URL 和 EMBEDDING_MODEL")
        return APIEmbedder(base, model, os.environ.get("EMBEDDING_API_KEY", ""), prefix)
    if provider == "local":
        path = os.environ.get("EMBEDDING_MODEL_PATH")
        if not path:
            raise ValueError("本地向量后端需要 EMBEDDING_MODEL_PATH")
        return LocalEmbedder(path, prefix)
    raise ValueError("启用向量检索前，请显式设置 EMBEDDING_PROVIDER=api 或 local")
