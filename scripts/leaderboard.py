"""從 data/games/ 算天梯，輸出 LEADERBOARD.md。

兩張榜：
- 偽裝榜：哪個模型最難被抓。每個 AI 座位一筆資料，分數 = 撐過的輪數比例 + 活到最後加分 - 被投票的比例。
- 獵人榜：上傳者（GitHub 帳號）帶的局，真人贏得多快、投錯真人幾次。

用法：python scripts/leaderboard.py [--data data/games] [--out LEADERBOARD.md] [--min-games 1]
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


def load(data_dir: Path) -> list[list[dict]]:
    games = []
    for f in sorted(data_dir.glob("*.jsonl")):
        recs = []
        for ln in f.read_text(encoding="utf-8").splitlines():
            try:
                recs.append(json.loads(ln))
            except json.JSONDecodeError:
                pass
        if any(r.get("ev") == "start" for r in recs) and any(r.get("ev") == "over" for r in recs):
            games.append(recs)
    return games


def analyze(games: list[list[dict]]):
    model = defaultdict(lambda: {"seats": 0, "survived": 0.0, "alive_end": 0, "votes": 0, "rounds": 0, "games": 0})
    hunter = defaultdict(lambda: {"games": 0, "wins": 0, "rounds": 0, "wrong_votes": 0, "votes": 0, "ai_caught": 0, "ai_total": 0})
    for g in games:
        start = next(r for r in g if r["ev"] == "start")
        over = next(r for r in g if r["ev"] == "over")
        rounds = over.get("rounds") or max((r.get("round", 0) for r in g), default=1) or 1
        players = {p["alias"]: p for p in start.get("players", [])}
        ais = {a for a, p in players.items() if p.get("is_ai")}
        eliminated: dict[str, int] = {}          # alias -> 第幾輪被放逐
        votes_on: dict[str, int] = defaultdict(int)
        for r in g:
            if r["ev"] == "result" and r.get("eliminated"):
                eliminated[r["eliminated"]] = r["round"]
            if r["ev"] == "vote" and r.get("target"):
                votes_on[r["target"]] += 1
        for a in ais:
            m = model[players[a].get("model") or "unknown"]
            m["seats"] += 1
            m["rounds"] += rounds
            surv = eliminated.get(a, rounds)
            m["survived"] += surv / rounds
            m["alive_end"] += 0 if a in eliminated else 1
            m["votes"] += votes_on[a]
        for mname in {players[a].get("model") or "unknown" for a in ais}:
            model[mname]["games"] += 1

        who = start.get("uploader") or ""
        if not who:
            continue
        h = hunter[who]
        h["games"] += 1
        h["wins"] += 1 if over.get("winner") == "humans" else 0
        h["rounds"] += rounds
        h["ai_total"] += len(ais)
        h["ai_caught"] += sum(1 for a in eliminated if a in ais)
        for r in g:
            if r["ev"] == "vote" and not r.get("is_ai") and r.get("target"):
                h["votes"] += 1
                if r["target"] not in ais:
                    h["wrong_votes"] += 1
    return model, hunter


def model_score(m: dict) -> float:
    if not m["seats"]:
        return 0.0
    surv = m["survived"] / m["seats"]
    alive = m["alive_end"] / m["seats"]
    heat = m["votes"] / max(1, m["rounds"])     # 平均每輪被投幾票
    return round(100 * (0.5 * surv + 0.4 * alive - 0.1 * min(1.0, heat)), 1)


def hunter_score(h: dict) -> float:
    if not h["games"]:
        return 0.0
    win = h["wins"] / h["games"]
    caught = h["ai_caught"] / max(1, h["ai_total"])
    speed = 1 / max(1.0, h["rounds"] / h["games"])      # 平均幾輪結束，越少越高
    acc = 1 - h["wrong_votes"] / max(1, h["votes"])
    return round(100 * (0.4 * win + 0.3 * caught + 0.15 * speed + 0.15 * acc), 1)


def render(model, hunter, n_games: int, min_games: int) -> str:
    out = [f"# 天梯", "", f"根據 `data/games/` 的 {n_games} 局社群對局計算，更新於 "
           f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC。想上榜就玩一局然後用 Issue 表單分享。", ""]
    out += ["## 偽裝榜：哪個模型最難被抓", "",
            "分數 = 50 × 平均撐過的輪數比例 + 40 × 活到最後的比例 − 10 × 每輪被投票數（上限 1）。", "",
            "| 名次 | 模型 | 分數 | 座位數 | 活到最後 | 平均撐過 | 每輪被投 |", "|---|---|---|---|---|---|---|"]
    rows = [(model_score(m), k, m) for k, m in model.items() if m["seats"] >= min_games]
    for i, (s, k, m) in enumerate(sorted(rows, reverse=True), 1):
        out.append(f"| {i} | `{k}` | {s} | {m['seats']} | {m['alive_end']}/{m['seats']} | "
                   f"{100 * m['survived'] / m['seats']:.0f}% | {m['votes'] / max(1, m['rounds']):.2f} |")
    if not rows:
        out.append("| – | 還沒有資料 | | | | | |")
    out += ["", "## 獵人榜：誰抓 AI 抓得最準", "",
            "以上傳者的 GitHub 帳號計。分數 = 40 × 真人勝率 + 30 × AI 抓到比例 + 15 × 速度（平均輪數越少越高）+ 15 × 投票準確率。", "",
            "| 名次 | 玩家 | 分數 | 局數 | 真人勝 | 抓到 AI | 平均輪數 | 投錯真人 |", "|---|---|---|---|---|---|---|---|"]
    rows = [(hunter_score(h), k, h) for k, h in hunter.items() if h["games"] >= min_games]
    for i, (s, k, h) in enumerate(sorted(rows, reverse=True), 1):
        out.append(f"| {i} | @{k} | {s} | {h['games']} | {h['wins']} | {h['ai_caught']}/{h['ai_total']} | "
                   f"{h['rounds'] / h['games']:.1f} | {h['wrong_votes']}/{h['votes']} |")
    if not rows:
        out.append("| – | 還沒有資料 | | | | | | |")
    out += ["", "分數只是好玩，局數少的時候波動很大。"]
    return "\n".join(out) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/games")
    ap.add_argument("--out", default="LEADERBOARD.md")
    ap.add_argument("--min-games", type=int, default=1)
    a = ap.parse_args()
    games = load(Path(a.data))
    model, hunter = analyze(games)
    Path(a.out).write_text(render(model, hunter, len(games), a.min_games), encoding="utf-8")
    print(f"{len(games)} 局，{len(model)} 個模型，{len(hunter)} 位上傳者 → {a.out}")


if __name__ == "__main__":
    main()
