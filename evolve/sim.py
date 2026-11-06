"""無前端、無延遲的模擬對局：幾個帶基因的 AI + 幾個模擬真人 + 投票。

回傳每個基因在這局的表現：撐了幾輪、被投幾票、被投的理由。
"""
from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass, field

from server import topics
from server.ai import prompts, style
from server.ai.llm import router, parse_json
from server.ai.persona import make_persona
from server.room import ALIASES
from . import fake_human, judge
from .data import Bank


@dataclass
class Genome:
    id: str
    strategy: str
    gen: int = 0
    parent: str = ""
    fitness: float = 0.0
    games: int = 0
    reasons: list[str] = field(default_factory=list)   # 被投的理由，給變異用
    samples: list[str] = field(default_factory=list)   # 它講過的話


@dataclass
class Seat:
    alias: str
    is_ai: bool
    genome: Genome | None = None
    persona: object = None
    alive: bool = True
    votes_received: int = 0
    rounds_survived: int = 0


class SimGame:
    def __init__(self, genomes: list[Genome], bank: Bank, n_humans: int = 3, rounds: int = 3,
                 turns: int = 3, provider: str | None = None):
        self.bank = bank
        self.rounds = rounds
        self.turns = turns
        self.cost = 0.0
        provs = router.available()
        self.provider = provider or random.choice(provs)
        self.model = __import__("server.config", fromlist=["MODELS"]).MODELS[self.provider]["judge"]
        aliases = random.sample(ALIASES, len(genomes) + n_humans)
        self.seats = [Seat(aliases[i], True, g, make_persona()) for i, g in enumerate(genomes)]
        self.seats += [Seat(a, False) for a in aliases[len(genomes):]]
        random.shuffle(self.seats)
        self.chat: list[tuple[str, str]] = []

    async def llm(self, system: str, user: str, max_tokens: int = 300) -> dict:
        r = await router.complete(self.provider, self.model, system, user, max_tokens=max_tokens)
        self.cost += r.cost_usd
        return parse_json(r.text)

    def history(self, me: str, n: int = 40) -> list[str]:
        return [f"{a}（你）：{t}" if a == me else f"{a}：{t}" for a, t in self.chat[-n:]]

    def alive(self) -> list[Seat]:
        return [s for s in self.seats if s.alive]

    async def speak(self, s: Seat, rnd: int, topic: str):
        alive = [x.alias for x in self.alive()]
        try:
            if s.is_ai:
                sys_ = prompts.system_prompt(s.persona, s.alias, [], s.genome.strategy)
                ctx = {"alias": s.alias, "round": rnd, "topic": topic, "seconds_left": 90, "alive": "、".join(alive),
                       "history": self.history(s.alias), "note": "", "mentioned": any(s.alias in t for _, t in self.chat[-5:]),
                       "quiet": False}
                data = await self.llm(sys_, prompts.discuss_prompt(ctx))
            else:
                data = await self.llm(fake_human.system_prompt(s.alias, self.bank),
                                      fake_human.discuss_prompt(s.alias, rnd, topic, self.history(s.alias), alive))
        except Exception:
            return
        for m in (data.get("say") or [])[:2]:
            t, bad = style.check(str(m))
            if s.is_ai and bad:
                continue  # 遊戲裡也會被擋掉，模擬時直接不送
            if t:
                self.chat.append((s.alias, t))
                if s.is_ai:
                    s.genome.samples.append(t)

    async def vote(self, s: Seat, rnd: int) -> tuple[str | None, str]:
        cands = [x.alias for x in self.alive() if x is not s]
        try:
            if s.is_ai:
                ctx = {"alias": s.alias, "round": rnd, "note": "", "candidates": "、".join(cands),
                       "history": self.history(s.alias, 60), "ally_hint": ""}
                data = await self.llm(prompts.system_prompt(s.persona, s.alias, [], s.genome.strategy),
                                      prompts.vote_prompt(ctx), 120)
            else:
                data = await self.llm("你是真人玩家。只輸出 JSON。",
                                      judge.vote_prompt(s.alias, rnd, self.history(s.alias, 60), cands, self.bank), 150)
        except Exception:
            return None, ""
        v = data.get("vote")
        return (v if v in cands else None), str(data.get("why", ""))

    async def run(self) -> dict:
        used: set[str] = set()
        for rnd in range(1, self.rounds + 1):
            topic = topics.pick(used)
            used.add(topic)
            for _ in range(self.turns):
                order = self.alive()
                random.shuffle(order)
                for s in order:
                    await self.speak(s, rnd, topic)
            # 投票（同時）
            alive = self.alive()
            results = await asyncio.gather(*(self.vote(s, rnd) for s in alive))
            tally: dict[str, int] = {}
            for s, (v, why) in zip(alive, results):
                if not v:
                    continue
                tally[v] = tally.get(v, 0) + 1
                target = next(x for x in self.seats if x.alias == v)
                target.votes_received += 1
                if target.is_ai and not s.is_ai and why:
                    target.genome.reasons.append(why)
            for s in alive:
                s.rounds_survived = rnd
            if tally:
                top = max(tally.values())
                tops = [a for a, n in tally.items() if n == top]
                if len(tops) == 1:
                    next(x for x in self.seats if x.alias == tops[0]).alive = False
            ais = [s for s in self.alive() if s.is_ai]
            hum = [s for s in self.alive() if not s.is_ai]
            if not ais or len(ais) >= len(hum):
                break
        out = {}
        for s in self.seats:
            if s.is_ai:
                out[s.genome.id] = {"survived": s.rounds_survived, "rounds": rnd, "alive": s.alive,
                                    "votes": s.votes_received}
        return {"genomes": out, "cost": self.cost, "chat_len": len(self.chat)}
