"""從 data/games/ 與 logs/ 讀真人局的資料：真人發言、真人投票理由、上傳者回饋。"""
from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCES = [ROOT / "data" / "games", ROOT / "logs"]


def game_files() -> list[Path]:
    files: list[Path] = []
    for d in SOURCES:
        if d.exists():
            files += sorted(d.glob("*.jsonl"))
    return files


def data_hash() -> str:
    h = hashlib.sha1()
    for f in game_files():
        h.update(f.name.encode())
        h.update(str(f.stat().st_size).encode())
    return h.hexdigest()[:12]


def load_games() -> list[list[dict]]:
    games = []
    for f in game_files():
        recs = []
        for ln in f.read_text(encoding="utf-8").splitlines():
            try:
                recs.append(json.loads(ln))
            except json.JSONDecodeError:
                pass
        if any(r.get("ev") == "over" for r in recs):
            games.append(recs)
    return games


class Bank:
    """演化要用的真人資料。"""

    def __init__(self):
        games = load_games()
        self.n_games = len(games)
        self.human_msgs: list[str] = []
        self.human_reasons: list[str] = []
        self.tells: list[str] = []
        for g in games:
            for r in g:
                ev = r.get("ev")
                if ev == "chat" and not r.get("is_ai") and r.get("text"):
                    self.human_msgs.append(r["text"])
                elif ev in ("vote", "vote_reason") and not r.get("is_ai") and r.get("reason"):
                    self.human_reasons.append(r["reason"])
                elif ev == "feedback":
                    for k, v in r.items():
                        if "露餡" in k and v:
                            self.tells.append(v)
        # 去重
        self.human_msgs = list(dict.fromkeys(self.human_msgs))
        self.human_reasons = list(dict.fromkeys(self.human_reasons))

    def sample_msgs(self, n: int) -> list[str]:
        return random.sample(self.human_msgs, min(n, len(self.human_msgs)))

    def reasons_text(self, n: int = 20) -> str:
        pool = self.human_reasons + self.tells
        if not pool:
            return "（還沒有真人局的投票理由，先用一般常識：回太快、太客氣、太有條理、不講自己的事、每句都接。）"
        return "\n".join(f"- {r}" for r in random.sample(pool, min(n, len(pool))))
