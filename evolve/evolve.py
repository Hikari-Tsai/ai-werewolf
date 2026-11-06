"""提示詞演化：錦標賽 → 排名 → 改寫 → 下一代。

用法：
  python evolve/evolve.py --generations 4 --games 6 --budget 5
  python evolve/evolve.py --check-new      # 有新對局資料就回 0，沒有回 1

產出：
  genomes/best.json          遊戲會讀的：前幾名的策略
  genomes/population.json    整個族群，下次接著演化
  genomes/history/gen_N.json 每一代的快照
  genomes/REPORT.md          這次跑的報告（PR 內文）
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server.ai.llm import router, parse_json  # noqa: E402
from server import config  # noqa: E402
from evolve.data import Bank, data_hash  # noqa: E402
from evolve.sim import Genome, SimGame  # noqa: E402

GEN_DIR = ROOT / "genomes"
SEEDS = [
    "少講多問。別人問才回，回很短，常反問對方，偶爾只回「蛤」「真假」。",
    "愛講自己瑣碎的事：幾點下班、吃了什麼、花多少錢，具體但無聊。別人分析時裝沒看到。",
    "帶風向型：每輪主動點名一個人說他回太快或太客氣，自己少講。",
    "自嘲型：常拿自己糗事開玩笑，被懷疑就說「我就廢啊」，不解釋。",
    "慢半拍型：常常回到上一個話題，像是剛看到，偶爾跟錯人講話。",
    "愛嗆型：直接吐槽別人的用詞，被點名就反嗆回去，不認真分析。",
]
MUTATE_SYS = "你在幫一個偽裝成台灣真人的聊天機器人改寫它的「個人策略」。只輸出 JSON。"


def load_population() -> list[Genome]:
    f = GEN_DIR / "population.json"
    if f.exists():
        return [Genome(**g) for g in json.loads(f.read_text(encoding="utf-8"))]
    return [Genome(id=f"seed{i}", strategy=s) for i, s in enumerate(SEEDS)]


def save_population(pop: list[Genome], gen: int):
    GEN_DIR.mkdir(exist_ok=True)
    (GEN_DIR / "history").mkdir(exist_ok=True)
    dump = [{"id": g.id, "strategy": g.strategy, "gen": g.gen, "parent": g.parent, "fitness": round(g.fitness, 3),
             "games": g.games, "reasons": g.reasons[-10:], "samples": g.samples[-10:]} for g in pop]
    (GEN_DIR / "population.json").write_text(json.dumps(dump, ensure_ascii=False, indent=1), encoding="utf-8")
    (GEN_DIR / "history" / f"gen_{gen}.json").write_text(json.dumps(dump, ensure_ascii=False, indent=1), encoding="utf-8")


def save_best(pop: list[Genome], meta: dict):
    top = sorted(pop, key=lambda g: g.fitness, reverse=True)[:3]
    data = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "data_hash": data_hash(),
            "strategies": [{"id": g.id, "strategy": g.strategy, "fitness": round(g.fitness, 3)} for g in top], **meta}
    (GEN_DIR / "best.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


async def mutate(g: Genome, bank: Bank, provider: str, gen: int, idx: int) -> Genome:
    model = config.MODELS[provider]["judge"]
    user = f"""目前的策略：{g.strategy}

它在模擬對局裡被真人投票的理由：
{chr(10).join('- ' + r for r in g.reasons[-8:]) or '- （沒被投過）'}

它講過的話：
{chr(10).join('- ' + s for s in g.samples[-8:]) or '- （無）'}

真人玩家通常這樣抓 AI：
{bank.reasons_text(10)}

請改寫策略，讓它更不容易被抓到。要求：台灣繁體口語、不超過 80 字、具體可執行（講話頻率、長度、遇到質疑怎麼辦、要講什麼樣的事），保留原本有效的部分。
只輸出 JSON：{{"strategy": "..."}}"""
    try:
        r = await router.complete(provider, model, MUTATE_SYS, user, max_tokens=200)
        s = str(parse_json(r.text).get("strategy", "")).strip()
        cost = r.cost_usd
    except Exception:
        s, cost = "", 0.0
    if not s or len(s) > 160:
        s = g.strategy
    child = Genome(id=f"g{gen}_{idx}", strategy=s, gen=gen, parent=g.id)
    child.fitness = 0.0
    child._cost = cost  # type: ignore[attr-defined]
    return child


async def run(args) -> int:
    provs = router.available()
    if not provs:
        print("沒有 API key")
        return 1
    bank = Bank()
    pop = load_population()
    for g in pop:
        g.fitness, g.games = 0.0, 0
    spent = 0.0
    report = [f"# 演化報告 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC", "",
              f"- 真人局資料：{bank.n_games} 局，{len(bank.human_msgs)} 則真人發言，{len(bank.human_reasons)} 條投票理由，{len(bank.tells)} 條回饋",
              f"- 設定：{args.generations} 代 × 每代 {args.games} 局 × {args.rounds} 輪，每局 {args.ais} 個 AI + {args.humans} 個模擬真人",
              f"- 模型：{'、'.join(config.MODELS[p]['judge'] for p in provs)}", ""]
    start_gen = max((g.gen for g in pop), default=0) + 1
    gen = start_gen
    for gen in range(start_gen, start_gen + args.generations):
        t0 = time.time()
        # 每局抽 args.ais 個基因，盡量讓每個基因都上場差不多次數
        games = []
        for i in range(args.games):
            picks = sorted(pop, key=lambda g: (g.games, random.random()))[:args.ais]
            for g in picks:
                g.games += 1
            games.append(SimGame(picks, bank, n_humans=args.humans, rounds=args.rounds,
                                 provider=provs[i % len(provs)]))
        results = await asyncio.gather(*(sg.run() for sg in games), return_exceptions=True)
        scores: dict[str, list[float]] = {g.id: [] for g in pop}
        for res in results:
            if isinstance(res, Exception):
                report.append(f"- 第 {gen} 代有一局失敗：{res!r}")
                continue
            spent += res["cost"]
            for gid, r in res["genomes"].items():
                survive = r["survived"] / max(1, r["rounds"])
                penalty = min(1.0, r["votes"] / max(1, r["rounds"] * 2))
                scores[gid].append(survive + 0.5 * (1 - penalty) + (0.3 if r["alive"] else 0))
        for g in pop:
            g.fitness = sum(scores[g.id]) / len(scores[g.id]) if scores[g.id] else 0.0
        pop.sort(key=lambda g: g.fitness, reverse=True)
        keep = pop[: max(2, len(pop) // 2)]
        report.append(f"## 第 {gen} 代（{time.time() - t0:.0f} 秒，累計 ${spent:.2f}）")
        for g in pop:
            report.append(f"- {g.fitness:.2f}  `{g.id}`  {g.strategy}")
        if spent > args.budget:
            report.append(f"\n超過預算 ${args.budget}，停在第 {gen} 代。")
            save_population(pop, gen)
            break
        # 變異：前半名各生一個孩子補滿族群
        children = await asyncio.gather(*(mutate(keep[i % len(keep)], bank, provs[i % len(provs)], gen + 1, i)
                                          for i in range(len(pop) - len(keep))))
        spent += sum(getattr(c, "_cost", 0.0) for c in children)
        for g in keep:
            g.reasons, g.samples = g.reasons[-10:], g.samples[-10:]
        pop = keep + list(children)
        save_population(pop, gen)
    best = max(pop, key=lambda g: g.fitness)
    report += ["", f"## 最佳策略（{best.fitness:.2f}）", "", best.strategy, "",
               f"總費用約 ${spent:.2f}。合併這個 PR 之後，遊戲開局時會從 best.json 的前三名抽策略給 AI。"]
    save_best(pop, {"spent_usd": round(spent, 3), "generations": args.generations, "games_per_gen": args.games})
    (GEN_DIR / "REPORT.md").write_text("\n".join(report), encoding="utf-8")
    print("\n".join(report))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--generations", type=int, default=4)
    ap.add_argument("--games", type=int, default=6)
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--ais", type=int, default=2)
    ap.add_argument("--humans", type=int, default=3)
    ap.add_argument("--budget", type=float, default=5.0)
    ap.add_argument("--check-new", action="store_true")
    args = ap.parse_args()
    if args.check_new:
        best = GEN_DIR / "best.json"
        old = json.loads(best.read_text(encoding="utf-8")).get("data_hash") if best.exists() else None
        sys.exit(0 if old != data_hash() else 1)
    sys.exit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
