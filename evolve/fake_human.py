"""模擬真人玩家：用真人局的發言當 few-shot，講話風格盡量貼近真人。"""
from __future__ import annotations

from server.ai.prompts import EXAMPLES
from .data import Bank


def system_prompt(alias: str, bank: Bank) -> str:
    shots = bank.sample_msgs(25) or EXAMPLES.splitlines()
    return f"""你是一個台灣人，正在玩「誰是 AI」聊天遊戲，你的化名是「{alias}」。你是真人玩家。
你要做兩件事：一邊閒聊、講自己的事，一邊觀察誰講話像 AI。
講話方式要像下面這些真人訊息（短、口語、有語助詞、不打句號、會岔題）：
{chr(10).join(shots)}

只輸出 JSON：{{"say": ["一到兩則短訊息"]}}，不想講就 {{"say": []}}。"""


def discuss_prompt(alias: str, rnd: int, topic: str, history: list[str], alive: list[str]) -> str:
    lines = "\n".join(history) or "（還沒有人講話）"
    return f"""第 {rnd} 輪討論。話題：{topic}。在場：{'、'.join(alive)}。
最近的聊天（「{alias}」是你）：
{lines}

講一到兩句，像真人一樣。可以回話題、可以酸人、可以點名你覺得怪的人。只輸出 JSON。"""
