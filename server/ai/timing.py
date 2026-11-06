"""人類時間模型：閱讀、思考、打字、分段、猶豫。全部回傳秒數。"""
from __future__ import annotations

import random

from .persona import Persona


def reading_delay(unread_chars: int) -> float:
    # 每秒約 8 到 12 個中文字，上限 6 秒（真人會略讀）
    return min(6.0, unread_chars / random.uniform(8, 12))


def think_delay(urgent: bool) -> float:
    return random.uniform(0.4, 1.8) if urgent else random.uniform(1.0, 4.5)


def typing_delay(text: str, p: Persona) -> float:
    base = len(text) / p.chars_per_sec
    return base * random.uniform(0.8, 1.3) + random.uniform(0.3, 0.9)


def between_messages() -> float:
    return random.uniform(0.5, 2.0)


def hesitation() -> float | None:
    """小機率打到一半停一下。"""
    return random.uniform(1.5, 3.0) if random.random() < 0.12 else None


def typo_pair(text: str, p: Persona) -> tuple[str, str] | None:
    """小機率先送含錯字的版本，再補一則更正。只動一個常見同音字。"""
    if random.random() >= p.typo_rate or len(text) < 6:
        return None
    swaps = [("的", "得"), ("在", "再"), ("應該", "因該"), ("什麼", "什摸"), ("一樣", "一漾"), ("這樣", "醬")]
    random.shuffle(swaps)
    for right, wrong in swaps:
        if right in text:
            return text.replace(right, wrong, 1), f"*{right}"
    return None
