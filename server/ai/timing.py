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


# 注音輸入最常選錯的同音字：台灣人打字幾乎都用注音，這種錯字很日常
ZHUYIN_SWAPS = [
    ("的", "得"), ("得", "的"), ("在", "再"), ("再", "在"), ("應該", "因該"), ("什麼", "什摸"), ("怎麼", "怎摸"),
    ("一樣", "一漾"), ("知道", "之道"), ("時候", "時後"), ("已經", "以經"), ("真的", "真得"), ("覺得", "決得"),
    ("可以", "可已"), ("其實", "奇實"), ("有沒有", "有美有"), ("沒有", "美有"), ("那個", "那各"), ("認真", "任真"),
    ("好像", "好象"), ("感覺", "感絕"), ("還是", "還事"), ("以為", "已為"), ("因為", "因位"), ("所以", "所已"),
    ("可疑", "可移"), ("懷疑", "懷移"), ("投票", "投漂"), ("真人", "針人"), ("明明", "名明"), ("馬上", "馬尚"),
    ("剛剛", "港港"), ("超", "抄"), ("這樣", "醬"), ("不會", "不惠"), ("是不是", "是部是"),
]


def typo_pair(text: str, p: Persona) -> tuple[str, str | None] | None:
    """小機率先送含錯字的版本，之後可能補一則更正、也可能懶得改。只動一個同音字。"""
    if random.random() >= p.typo_rate or len(text) < 6:
        return None
    swaps = ZHUYIN_SWAPS[:]
    random.shuffle(swaps)
    for right, wrong in swaps:
        if right in text:
            fix = random.choice([f"*{right}", right, f"{right}啦", None, None])
            return text.replace(right, wrong, 1), fix
    return None
