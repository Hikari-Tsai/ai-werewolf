"""一個 AI 玩家的主迴圈：觀察 → 要不要講 → 生成 → 過濾 → 照人類節奏送出。

事件驅動：Room 的 chat / typing / phase 事件丟進 queue，
沒事件時每幾秒醒來一次評估「衝動值」，過門檻才呼叫模型。
"""
from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import Optional

from .. import config
from . import prompts, style, timing
from .llm import router, parse_json
from .persona import make_persona, load_strategy

log = logging.getLogger("brain")


class AIBrain:
    def __init__(self, room, player, index: int):
        self.room = room
        self.p = player
        self.index = index
        self.persona = make_persona()
        self.strategy = load_strategy()   # 演化出來的策略，沒有就空
        self.provider, self.model = router.pick(index, room.cfg["model_strategy"])
        self.model_label = self.model
        self.queue: asyncio.Queue = asyncio.Queue()
        self.task: Optional[asyncio.Task] = None
        self.note = ""
        self.last_spoke = 0.0
        self.last_seen_idx = 0          # 看到第幾則聊天
        self.spoke_this_round = 0
        self.phase = "lobby"
        self.phase_started = 0.0
        self.first_delay = 0.0
        self.busy = False
        self.pending_mention = False
        self.cancel_typing = False
        room.listeners.append(self.on_event)

    # ---------- 生命週期 ----------
    def start(self):
        if not self.task:
            self.task = asyncio.create_task(self._run(), name=f"ai-{self.p.alias}")

    def stop(self):
        if self.on_event in self.room.listeners:
            self.room.listeners.remove(self.on_event)
        if self.task:
            self.task.cancel()
            self.task = None

    def on_event(self, ev: dict):
        self.queue.put_nowait(ev)

    @property
    def allies(self) -> list[str]:
        if not self.room.cfg["ai_know_each_other"]:
            return []
        return [q.alias for q in self.room.players.values() if q.is_ai and q.pid != self.p.pid]

    # ---------- 主迴圈 ----------
    async def _run(self):
        try:
            while True:
                try:
                    ev = await asyncio.wait_for(self.queue.get(), timeout=random.uniform(3, 7))
                    await self._handle(ev)
                except asyncio.TimeoutError:
                    pass
                if self.phase == "discuss" and self.p.alive and not self.busy:
                    await self._maybe_speak()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            log.exception("AI %s 掛了：%r", self.p.alias, e)

    async def _handle(self, ev: dict):
        t = ev["type"]
        if t == "phase":
            self.phase = ev["phase"]
            self.phase_started = time.time()
            if self.phase == "discuss":
                self.spoke_this_round = 0
                self.pending_mention = False
                # 開場不要秒回：每個人進入狀況的時間不同
                self.first_delay = min(20.0, random.uniform(4, 22) / max(0.6, self.persona.talkativeness))
            elif self.phase == "vote" and self.p.alive:
                asyncio.create_task(self._vote(ev.get("seconds", 30)))
        elif t == "chat" and ev["alias"] != self.p.alias:
            if self.p.alias in ev["text"]:
                self.pending_mention = True
                if self.busy:
                    self.cancel_typing = random.random() < 0.35

    # ---------- 要不要講話 ----------
    def _urge(self) -> float:
        now = time.time()
        if now - self.phase_started < self.first_delay:
            return 0.0
        left = self.room.phase_ends_at - now
        if left < 8:
            return 0.0  # 來不及打完了
        chat = self.room.chat
        new_msgs = [m for m in chat[self.last_seen_idx:] if m["alias"] != self.p.alias]
        since_me = now - self.last_spoke
        last_any = chat[-1]["ts"] if chat else self.phase_started
        silence = now - last_any
        u = 0.0
        if self.pending_mention:
            u += 0.85
        u += min(0.45, 0.12 * len(new_msgs))
        if since_me > 45:
            u += 0.25
        if silence > 25 and self.spoke_this_round < 6:
            u += 0.3
        if self.spoke_this_round == 0 and left < 40:
            u += 0.5  # 整輪沒講話最可疑，快結束前至少講一句
        if since_me < 10:
            u *= 0.2
        if self.spoke_this_round >= 8:
            u *= 0.4
        u *= self.persona.talkativeness
        # 超過預算就只回點名
        if self.room.cost_usd > self.room.cfg["budget_usd"] and not self.pending_mention:
            u = 0.0
        return u

    async def _maybe_speak(self):
        u = self._urge()
        if u < 0.55 or random.random() > min(1.0, u):
            return
        self.busy = True
        try:
            await self._speak()
        finally:
            self.busy = False

    # ---------- 生成與送出 ----------
    def _history(self, n: int = 40) -> list[str]:
        out = []
        for m in self.room.chat[-n:]:
            who = f"{m['alias']}（你）" if m["alias"] == self.p.alias else m["alias"]
            out.append(f"{who}：{m['text']}")
        return out

    def _ctx(self) -> dict:
        now = time.time()
        return {
            "alias": self.p.alias,
            "round": self.room.round,
            "topic": self.room.topic,
            "seconds_left": max(0, int(self.room.phase_ends_at - now)),
            "alive": "、".join(p.alias for p in self.room.alive_players()),
            "history": self._history(),
            "note": self.note,
            "mentioned": self.pending_mention,
            "quiet": bool(self.room.chat) and now - self.room.chat[-1]["ts"] > 25,
        }

    async def _llm(self, user: str, max_tokens: int = 400) -> dict:
        res = await router.complete(self.provider, self.model,
                                    prompts.system_prompt(self.persona, self.p.alias, self.allies, self.strategy),
                                    user, max_tokens=max_tokens, strategy=self.room.cfg["model_strategy"])
        self.room.cost_usd += res.cost_usd
        if res.model != self.model:
            self.model_label = self.p.model = res.model  # 備援後揭曉顯示實際用的
        return parse_json(res.text)

    async def _speak(self):
        unread = sum(len(m["text"]) for m in self.room.chat[self.last_seen_idx:])
        self.last_seen_idx = len(self.room.chat)
        mentioned = self.pending_mention
        self.pending_mention = False
        await asyncio.sleep(timing.reading_delay(unread) + timing.think_delay(mentioned))

        ctx = self._ctx()
        ctx["mentioned"] = mentioned
        data = await self._llm(prompts.discuss_prompt(ctx))
        if data.get("note"):
            self.note = str(data["note"])[:120]
            await self.room.ai_note(self.p, self.note)
        msgs = [str(s) for s in (data.get("say") or []) if str(s).strip()][:3]

        # 風格關卡，不過就帶著原因重生成一次
        passed = []
        for m in msgs:
            t, reasons = style.check(m)
            if reasons:
                fix = await self._llm(prompts.discuss_prompt(ctx) +
                                      f"\n\n你剛才寫的「{m}」不行：{'；'.join(reasons)}。重寫得更短、更口語、更像台灣人。", 200)
                cand = [str(s) for s in (fix.get("say") or [])][:1]
                if cand:
                    t, reasons = style.check(cand[0])
            if not reasons:
                passed.append(t)
        if not passed:
            return

        for i, t in enumerate(passed):
            if i:
                await asyncio.sleep(timing.between_messages())
            if self.phase != "discuss" or not self.p.alive:
                return
            await self._type_and_send(t)

    async def _type_and_send(self, text: str):
        pair = timing.typo_pair(text, self.persona)
        to_send = [pair[0], pair[1]] if pair else [text]
        for k, t in enumerate(to_send):
            self.cancel_typing = False
            await self.room.set_typing(self.p, True)
            total = timing.typing_delay(t, self.persona) if k == 0 else random.uniform(0.8, 1.5)
            h = timing.hesitation()
            if h and total > 3:
                await asyncio.sleep(total * 0.5)
                await self.room.set_typing(self.p, False)
                await asyncio.sleep(h)
                await self.room.set_typing(self.p, True)
                await asyncio.sleep(total * 0.5)
            else:
                await asyncio.sleep(total)
            if self.cancel_typing and k == 0:
                # 被點名了，放棄原本要講的，下個迴圈會重新生成
                await self.room.set_typing(self.p, False)
                self.pending_mention = True
                return
            if self.phase != "discuss" or not self.p.alive:
                await self.room.set_typing(self.p, False)
                return
            await self.room.post_chat(self.p, t)
            self.last_spoke = time.time()
            self.spoke_this_round += 1
            self.last_seen_idx = len(self.room.chat)

    # ---------- 投票 ----------
    async def _vote(self, seconds: float):
        await asyncio.sleep(random.uniform(3, max(4, seconds - 8)))
        if self.phase != "vote" or not self.p.alive:
            return
        cands = [p.alias for p in self.room.alive_players() if p.pid != self.p.pid]
        allies = self.allies
        ctx = {
            "alias": self.p.alias, "round": self.room.round, "note": self.note,
            "candidates": "、".join(cands), "history": self._history(60),
            "ally_hint": f"（{'、'.join(allies)} 是你的同伴，不要投他們）" if allies else "",
        }
        target, why = None, ""
        try:
            data = await self._llm(prompts.vote_prompt(ctx), 150)
            v = data.get("vote")
            if v in cands and v not in allies:
                target = v
            why = str(data.get("why") or "")
            if why:
                await self.room.ai_note(self.p, f"投票：{target or '棄票'}，{why}")
        except Exception as e:
            log.warning("AI %s 投票失敗：%r", self.p.alias, e)
        if target is None and cands:
            # 沒有明確目標就跟風：投目前被提到最多的人
            mentions = {c: sum(m["text"].count(c) for m in self.room.chat if m["round"] == self.room.round) for c in cands}
            best = max(mentions.values())
            pool = [c for c, n in mentions.items() if n == best and c not in allies] or [c for c in cands if c not in allies] or cands
            target = random.choice(pool) if random.random() < 0.8 else None
        await self.room.cast_vote(self.p, target, why)
