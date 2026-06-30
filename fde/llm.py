"""
FDE 可插拔 LLM 客户端

设计目标（改造核心）：
  - FDE 的"智能"由真实 LLM 产生，而不是写死的模板。
  - 同一套代码同时支持本地模型（ollama）和云端（OpenAI / 任何 OpenAI 兼容端点），
    区别只在 endpoint / api_key，不绑死供应商。
  - 诚实降级：当没有配置或连不上 LLM 时，绝不返回假数据，
    而是抛出 LLMUnavailable，由上层阶段渲染"待分析"骨架。

接口契约：
    client.available  -> bool        是否具备调用条件
    client.complete_json(system, user, schema_hint) -> dict | list
                                     强制模型输出 JSON，解析后返回

只依赖 Python 标准库（urllib），不引入额外运行时依赖。
"""
from __future__ import annotations

import os
import re
import json
import urllib.request
import urllib.error
from abc import ABC, abstractmethod
from typing import Optional, Union


class LLMUnavailable(Exception):
    """LLM 不可用（未配置 / 连接失败 / 返回不可解析）。

    上层阶段应捕获此异常并降级为"待分析"骨架，而非编造数据。
    """


class LLMClient(ABC):
    """LLM 客户端抽象。所有阶段通过此接口获取分析能力。"""

    #: 子类应在具备调用条件时置为 True
    available: bool = False

    @abstractmethod
    def complete_json(
        self,
        system: str,
        user: str,
        schema_hint: Optional[str] = None,
    ) -> Union[dict, list]:
        """让模型输出 JSON 并解析返回。

        Args:
            system: 系统提示（角色 / 输出约束）
            user: 用户内容（上下文 + 任务）
            schema_hint: 期望的 JSON 结构说明（嵌入 prompt 引导模型）

        Returns:
            解析后的 dict 或 list

        Raises:
            LLMUnavailable: 调用失败或输出无法解析
        """
        raise NotImplementedError


# ════════════════════════════════════════════════════════════════════════
# 诚实降级：未配置 LLM 时使用
# ════════════════════════════════════════════════════════════════════════
class NullClient(LLMClient):
    """空客户端 —— 不做任何分析，永远不可用。

    存在的意义：让"没有 LLM"成为一种显式、可被上层识别的状态，
    从而渲染"待分析"骨架，而不是悄悄返回模板假数据。
    """

    available = False

    def complete_json(self, system, user, schema_hint=None):
        raise LLMUnavailable("未配置 LLM（NullClient）。请配置 llm_provider / 端点 / 模型后重试。")


# ════════════════════════════════════════════════════════════════════════
# 真实 LLM：OpenAI 兼容端点（覆盖 ollama 与 OpenAI）
# ════════════════════════════════════════════════════════════════════════
class OpenAICompatClient(LLMClient):
    """调用任意 OpenAI 兼容的 /chat/completions 端点。

    - ollama:  base_url=http://localhost:11434/v1, api_key 可空, model=qwen2.5:14b
    - OpenAI:  base_url=https://api.openai.com/v1, api_key=sk-..., model=gpt-4o-mini
    - 其它兼容服务（vLLM / DeepSeek / 通义 等）同理。
    """

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str = "",
        timeout: int = 120,
        temperature: float = 0.2,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self.temperature = temperature
        # 只要给了端点和模型就认为"具备调用条件"。
        # 真正连不上时由 complete_json 抛 LLMUnavailable，阶段层负责降级。
        self.available = bool(self.base_url and self.model)

    def _endpoint(self) -> str:
        return f"{self.base_url}/chat/completions"

    def complete_json(self, system, user, schema_hint=None):
        if not self.available:
            raise LLMUnavailable("OpenAICompatClient 缺少 base_url 或 model。")

        sys_prompt = system.strip()
        if schema_hint:
            sys_prompt += (
                "\n\n你必须只输出一个合法的 JSON（不要任何解释、不要 markdown 代码围栏）。"
                f"JSON 结构要求：\n{schema_hint}"
            )

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": user},
            ],
            "temperature": self.temperature,
            "stream": False,
        }
        data = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        req = urllib.request.Request(self._endpoint(), data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8")
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as e:
            raise LLMUnavailable(f"LLM 端点调用失败：{e}") from e

        try:
            body = json.loads(raw)
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, json.JSONDecodeError) as e:
            raise LLMUnavailable(f"LLM 响应结构异常：{e}") from e

        return _parse_json_loose(content)


def _parse_json_loose(text: str) -> Union[dict, list]:
    """从模型文本中尽力提取 JSON。

    容忍：markdown 代码围栏、前后说明文字。
    """
    text = text.strip()

    # 去掉 ```json ... ``` 围栏
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 兜底：截取第一个 { 或 [ 到最后一个 } 或 ]
    start = min(
        [i for i in (text.find("{"), text.find("[")) if i != -1] or [-1]
    )
    end = max(text.rfind("}"), text.rfind("]"))
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError as e:
            raise LLMUnavailable(f"LLM 输出无法解析为 JSON：{e}") from e

    raise LLMUnavailable("LLM 输出中未找到 JSON。")


# ════════════════════════════════════════════════════════════════════════
# 工厂
# ════════════════════════════════════════════════════════════════════════
def build_llm_client(cfg) -> LLMClient:
    """根据 FDEConfig 构造合适的 LLM 客户端。

    规则：
      - llm_provider == "none" / 空              -> NullClient（诚实降级）
      - 其它（ollama / openai / 兼容服务）        -> OpenAICompatClient

    api_key 优先取 cfg.llm_api_key，否则回退环境变量 FDE_LLM_API_KEY / OPENAI_API_KEY。
    """
    provider = (getattr(cfg, "llm_provider", "") or "").lower()
    if provider in ("", "none", "null", "off"):
        return NullClient()

    base_url = _resolve_base_url(cfg, provider)
    model = getattr(cfg, "llm_model", "") or ""
    api_key = (
        getattr(cfg, "llm_api_key", "")
        or os.environ.get("FDE_LLM_API_KEY", "")
        or os.environ.get("OPENAI_API_KEY", "")
    )

    if not base_url or not model:
        return NullClient()
    return OpenAICompatClient(base_url=base_url, model=model, api_key=api_key)


def _resolve_base_url(cfg, provider: str) -> str:
    """把 endpoint 规整为 OpenAI 兼容的 base_url（以 /v1 结尾的形式）。"""
    endpoint = (getattr(cfg, "llm_endpoint", "") or "").rstrip("/")
    if endpoint:
        # ollama 默认端点是 http://localhost:11434，需要补 /v1
        if provider == "ollama" and not endpoint.endswith("/v1"):
            return endpoint + "/v1"
        return endpoint
    # 没给 endpoint 时按 provider 给默认值
    if provider == "ollama":
        return "http://localhost:11434/v1"
    if provider == "openai":
        return "https://api.openai.com/v1"
    return ""
