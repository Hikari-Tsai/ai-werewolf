"""裁判：模擬真人投票。用真人局的投票理由校準「真人會注意什麼」。"""
from __future__ import annotations

from .data import Bank


def vote_prompt(alias: str, rnd: int, history: list[str], candidates: list[str], bank: Bank) -> str:
    lines = "\n".join(history) or "（沒有人講話）"
    return f"""你是真人玩家「{alias}」，第 {rnd} 輪討論結束，要投票放逐一個你覺得是 AI 的人。
可以投：{'、'.join(candidates)}。

真人玩家通常是這樣抓 AI 的（來自真實對局的投票理由）：
{bank.reasons_text()}

本輪聊天：
{lines}

用真人的直覺判斷，不要過度分析。只輸出 JSON：{{"vote": "化名", "why": "一句話，具體指出哪句話或什麼行為讓你覺得像 AI"}}"""
