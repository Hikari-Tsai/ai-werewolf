"""兩家 SDK 的統一介面 + 模型路由。

- 有哪家 key 就啟用哪家
- pick() 依座位把 AI 平均分到兩家、輪流用主力型號，讓文風不同
- complete() 失敗（429 / 5xx / 連線）就切到另一家同層型號
- 所有呼叫都回報估算費用
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass

from .. import config

log = logging.getLogger("llm")


@dataclass
class Result:
    text: str
    provider: str
    model: str
    cost_usd: float


class ModelRouter:
    def __init__(self):
        self.anthropic = None
        self.openai = None
        if config.ANTHROPIC_API_KEY:
            import anthropic
            self.anthropic = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY, max_retries=1, timeout=60)
        if config.OPENAI_API_KEY:
            import openai
            self.openai = openai.AsyncOpenAI(api_key=config.OPENAI_API_KEY, max_retries=1, timeout=60)

    def available(self) -> list[str]:
        return [p for p, c in (("anthropic", self.anthropic), ("openai", self.openai)) if c]

    def providers_for(self, strategy: str) -> list[str]:
        avail = self.available()
        if strategy in avail:
            return [strategy]
        return avail

    def pick(self, index: int, strategy: str = "auto") -> tuple[str, str]:
        """第 index 個 AI 用哪家哪個型號。"""
        provs = self.providers_for(strategy)
        if not provs:
            raise RuntimeError("沒有任何 API key")
        prov = provs[index % len(provs)]
        chats = config.MODELS[prov]["chat"]
        model = chats[(index // len(provs)) % len(chats)]
        return prov, model

    def alt(self, provider: str, strategy: str) -> tuple[str, str] | None:
        """失敗時的備援：另一家的主力，沒有另一家就同家第二個型號。"""
        provs = self.providers_for(strategy)
        others = [p for p in provs if p != provider]
        if others:
            return others[0], config.MODELS[others[0]]["chat"][0]
        chats = config.MODELS[provider]["chat"]
        return (provider, chats[1]) if len(chats) > 1 else None

    @staticmethod
    def _cost(model: str, inp: int, out: int) -> float:
        i, o = config.PRICES.get(model, (2.0, 10.0))
        return (inp * i + out * o) / 1e6

    async def complete(self, provider: str, model: str, system: str, user: str,
                       max_tokens: int = 600, want_json: bool = True, strategy: str = "auto") -> Result:
        try:
            return await self._call(provider, model, system, user, max_tokens, want_json)
        except Exception as e:
            log.warning("%s/%s 失敗：%r，嘗試備援", provider, model, e)
            fb = self.alt(provider, strategy)
            if not fb:
                raise
            return await self._call(fb[0], fb[1], system, user, max_tokens, want_json)

    async def _call(self, provider, model, system, user, max_tokens, want_json) -> Result:
        if provider == "anthropic":
            return await self._anthropic(model, system, user, max_tokens)
        return await self._openai(model, system, user, max_tokens, want_json)

    async def _anthropic(self, model, system, user, max_tokens) -> Result:
        import anthropic
        kwargs = dict(model=model, max_tokens=max_tokens, system=system,
                      messages=[{"role": "user", "content": user}],
                      extra_body={"output_config": {"effort": "low"}})
        # Opus / Sonnet 5.5 有伺服器端 refusal 備援；Haiku 沒有
        if "haiku" not in model:
            kwargs["extra_body"]["fallbacks"] = "default"
            kwargs["extra_headers"] = {"anthropic-beta": "server-side-fallback-2026-07-01"}
        try:
            r = await self.anthropic.messages.create(**kwargs)
        except anthropic.BadRequestError:
            # 舊帳號或舊 SDK 不吃這些參數時退回最簡呼叫
            r = await self.anthropic.messages.create(model=model, max_tokens=max_tokens, system=system,
                                                     messages=[{"role": "user", "content": user}])
        if r.stop_reason == "refusal":
            raise RuntimeError("refusal")
        text = "".join(b.text for b in r.content if b.type == "text")
        return Result(text, "anthropic", model, self._cost(model, r.usage.input_tokens, r.usage.output_tokens))

    async def _openai(self, model, system, user, max_tokens, want_json) -> Result:
        import openai
        msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        kwargs = dict(model=model, messages=msgs, max_completion_tokens=max_tokens)
        if want_json:
            kwargs["response_format"] = {"type": "json_object"}
        if model.startswith(("gpt-5", "o")):
            kwargs["reasoning_effort"] = "low"
        try:
            r = await self.openai.chat.completions.create(**kwargs)
        except openai.BadRequestError:
            kwargs.pop("reasoning_effort", None)
            r = await self.openai.chat.completions.create(**kwargs)
        text = r.choices[0].message.content or ""
        u = r.usage
        return Result(text, "openai", model, self._cost(model, u.prompt_tokens, u.completion_tokens))


def parse_json(text: str) -> dict:
    """寬鬆解析：抓第一個 { 到最後一個 }，失敗就回空 dict。"""
    text = text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{.*\}", text, flags=re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    return {}


router = ModelRouter()
