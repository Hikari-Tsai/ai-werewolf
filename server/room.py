"""房間、玩家、階段狀態機。

真人和 AI 都是 Player；差別只在 is_ai 與有沒有 WebSocket。
送給前端的任何資料都不含 is_ai，除非是揭曉或觀眾視角。
"""
from __future__ import annotations

import asyncio
import json
import os
import random
import secrets
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from . import config, topics

ALIASES = [
    "阿凱", "小蓁", "豆花", "Yuki", "阿翔", "小米", "大雄", "小花", "阿宏", "Ivy",
    "阿明", "小魚", "阿德", "妮妮", "小安", "阿俊", "佩佩", "小寶", "阿良", "Kevin",
    "小柔", "阿哲", "芋頭", "小傑", "阿豪", "Tina", "小嵐", "阿忠", "小葵", "阿強",
]

Listener = Callable[[dict], None]


@dataclass
class Player:
    pid: str                       # 私密 token，只有本人知道
    alias: str                     # 公開化名
    avatar: int                    # 頭像種子
    is_ai: bool
    nickname: str = ""             # 真人自己取的，只給本人看
    alive: bool = True
    ws: Any = None                 # 真人的 WebSocket
    brain: Any = None              # AI 的大腦
    model: str = ""                # AI 用的模型名，揭曉時顯示
    vote: Optional[str] = None     # 本輪投給誰（alias），"" 代表棄票
    typing: bool = False
    connected: bool = False

    def public(self) -> dict:
        return {"alias": self.alias, "avatar": self.avatar, "alive": self.alive, "typing": self.typing,
                "connected": self.connected or self.is_ai}


class Room:
    def __init__(self, code: str):
        self.code = code
        self.host_pid: Optional[str] = None
        self.players: dict[str, Player] = {}
        self.cfg = dict(config.DEFAULT_ROOM)
        self.phase = "lobby"       # lobby | discuss | vote | result | over
        self.round = 0
        self.phase_ends_at = 0.0
        self.topic = ""
        self.used_topics: set[str] = set()
        self.chat: list[dict] = []   # {"alias","text","ts","round"}
        self.listeners: list[Listener] = []   # AI brains 訂閱事件
        self.task: Optional[asyncio.Task] = None
        self.last_result: Optional[dict] = None
        self.winner: Optional[str] = None
        self.cost_usd = 0.0
        self.log_path = ""
        self.created_at = time.time()
        self._vote_event = asyncio.Event()

    # ---------- 查詢 ----------
    def by_alias(self, alias: str) -> Optional[Player]:
        return next((p for p in self.players.values() if p.alias == alias), None)

    def alive_players(self) -> list[Player]:
        return [p for p in self.players.values() if p.alive]

    def counts(self) -> tuple[int, int]:
        ai = sum(1 for p in self.alive_players() if p.is_ai)
        return len(self.alive_players()) - ai, ai

    def free_alias(self) -> str:
        used = {p.alias for p in self.players.values()}
        return random.choice([a for a in ALIASES if a not in used])

    def free_avatar(self) -> int:
        used = {p.avatar for p in self.players.values()}
        return random.choice([i for i in range(12) if i not in used] or list(range(12)))

    # ---------- 加入 ----------
    def add_human(self, nickname: str, ws) -> Player:
        p = Player(pid=secrets.token_urlsafe(12), alias=self.free_alias(), avatar=self.free_avatar(),
                   is_ai=False, nickname=nickname[:12] or "玩家", ws=ws, connected=True)
        self.players[p.pid] = p
        if self.host_pid is None:
            self.host_pid = p.pid
        return p

    def add_ai(self, brain_factory) -> Player:
        p = Player(pid=secrets.token_urlsafe(12), alias=self.free_alias(), avatar=self.free_avatar(), is_ai=True)
        self.players[p.pid] = p
        p.brain = brain_factory(self, p)
        p.model = p.brain.model_label
        return p

    def remove_player(self, p: Player):
        if self.phase == "lobby":
            self.players.pop(p.pid, None)
            if p.brain:
                p.brain.stop()
            if self.host_pid == p.pid:
                humans = [q for q in self.players.values() if not q.is_ai]
                self.host_pid = humans[0].pid if humans else None
        else:
            p.connected = False
            p.ws = None

    # ---------- 廣播 ----------
    def state_for(self, p: Optional[Player]) -> dict:
        return {
            "type": "room_state",
            "code": self.code,
            "phase": self.phase,
            "round": self.round,
            "ends_at": self.phase_ends_at,
            "server_time": time.time(),
            "topic": self.topic,
            "players": [q.public() for q in self.players.values()],
            "you": p.alias if p else None,
            "nickname": p.nickname if p else None,
            "is_host": bool(p and p.pid == self.host_pid),
            "alive": bool(p and p.alive),
            "voted": (p.vote is not None) if p else False,
            "cfg": self.cfg if p and p.pid == self.host_pid else {k: self.cfg[k] for k in ("ai_count", "discuss_seconds", "topics_on")},
            "last_result": self.last_result,
            "winner": self.winner,
            "cost_usd": round(self.cost_usd, 3) if p and p.pid == self.host_pid else None,
            "public_url": config.PUBLIC_URL,
        }

    async def send(self, p: Player, msg: dict):
        if p.ws is None:
            return
        try:
            await p.ws.send_text(json.dumps(msg, ensure_ascii=False))
        except Exception:
            p.connected = False
            p.ws = None

    async def broadcast(self, msg: dict, spectators_only: bool = False):
        for p in list(self.players.values()):
            if p.is_ai:
                continue
            if spectators_only and p.alive:
                continue
            await self.send(p, msg)

    async def push_state(self):
        for p in list(self.players.values()):
            if not p.is_ai:
                await self.send(p, self.state_for(p))

    def emit(self, event: dict):
        """給 AI 大腦的事件流。"""
        for fn in list(self.listeners):
            try:
                fn(event)
            except Exception:
                pass

    # ---------- 行為（真人與 AI 共用）----------
    async def set_typing(self, p: Player, on: bool):
        if self.phase != "discuss" or not p.alive or p.typing == on:
            return
        p.typing = on
        await self.broadcast({"type": "typing", "alias": p.alias, "on": on})
        self.emit({"type": "typing", "alias": p.alias, "on": on})

    async def post_chat(self, p: Player, text: str):
        text = text.strip()[: config.MAX_MSG_CHARS * 2]
        if self.phase != "discuss" or not p.alive or not text:
            return
        await self.set_typing(p, False)
        msg = {"alias": p.alias, "text": text, "ts": time.time(), "round": self.round}
        self.chat.append(msg)
        self.log({"ev": "chat", **msg, "is_ai": p.is_ai})
        await self.broadcast({"type": "chat", **msg})
        self.emit({"type": "chat", **msg})

    async def cast_vote(self, p: Player, target_alias: Optional[str], reason: str = ""):
        if self.phase != "vote" or not p.alive:
            return
        t = self.by_alias(target_alias) if target_alias else None
        if target_alias and (t is None or not t.alive or t.pid == p.pid):
            return
        p.vote = target_alias or ""
        self.log({"ev": "vote", "round": self.round, "alias": p.alias, "target": p.vote, "is_ai": p.is_ai,
                  "reason": (reason or "").strip()[:200]})
        await self.broadcast({"type": "vote_progress",
                              "voted": sum(1 for q in self.alive_players() if q.vote is not None),
                              "total": len(self.alive_players())})
        if all(q.vote is not None for q in self.alive_players()):
            self._vote_event.set()

    def vote_reason(self, p: Player, reason: str):
        """投完票之後補的理由，演化最需要的資料。"""
        if p.vote is None or not reason.strip():
            return
        self.log({"ev": "vote_reason", "round": self.round, "alias": p.alias, "target": p.vote,
                  "is_ai": p.is_ai, "reason": reason.strip()[:200]})

    async def ai_note(self, p: Player, note: str):
        """AI 的內心小抄，只給觀眾。"""
        self.log({"ev": "note", "round": self.round, "alias": p.alias, "note": note})
        await self.broadcast({"type": "spectate", "alias": p.alias, "model": p.model, "note": note}, spectators_only=True)

    # ---------- 遊戲主流程 ----------
    def start(self):
        if self.phase != "lobby" or self.task:
            return
        os.makedirs(config.LOG_DIR, exist_ok=True)
        self.log_path = os.path.join(config.LOG_DIR, f"{time.strftime('%Y%m%d_%H%M%S')}_{self.code}.jsonl")
        self.log({"ev": "start", "cfg": self.cfg,
                  "players": [{"alias": p.alias, "is_ai": p.is_ai, "model": p.model} for p in self.players.values()]})
        self.task = asyncio.create_task(self._run())

    async def _run(self):
        try:
            for p in self.players.values():
                if p.brain:
                    p.brain.start()
            while True:
                self.round += 1
                await self._discuss_phase()
                await self._vote_phase()
                await self._result_phase()
                if self._check_over():
                    break
            await self._game_over()
        except asyncio.CancelledError:
            pass
        except Exception as e:  # 不讓單一錯誤卡死整局
            self.log({"ev": "error", "err": repr(e)})
            await self.broadcast({"type": "error", "text": f"伺服器錯誤：{e}"})

    async def _set_phase(self, phase: str, seconds: float):
        self.phase = phase
        self.phase_ends_at = time.time() + seconds
        self.log({"ev": "phase", "phase": phase, "round": self.round})
        await self.push_state()
        self.emit({"type": "phase", "phase": phase, "round": self.round, "topic": self.topic,
                   "seconds": seconds, "alive": [p.alias for p in self.alive_players()]})

    async def _discuss_phase(self):
        for p in self.players.values():
            p.vote = None
            p.typing = False
        if self.cfg["topics_on"]:
            self.topic = topics.pick(self.used_topics)
            self.used_topics.add(self.topic)
        else:
            self.topic = ""
        await self._set_phase("discuss", self.cfg["discuss_seconds"])
        await asyncio.sleep(self.cfg["discuss_seconds"])

    async def _vote_phase(self):
        self._vote_event.clear()
        await self._set_phase("vote", self.cfg["vote_seconds"])
        try:
            await asyncio.wait_for(self._vote_event.wait(), timeout=self.cfg["vote_seconds"])
        except asyncio.TimeoutError:
            pass

    async def _result_phase(self):
        tally: dict[str, int] = {}
        for p in self.alive_players():
            if p.vote:
                tally[p.vote] = tally.get(p.vote, 0) + 1
        eliminated = None
        if tally:
            top = max(tally.values())
            tops = [a for a, n in tally.items() if n == top]
            if len(tops) == 1:
                eliminated = self.by_alias(tops[0])
        if eliminated:
            eliminated.alive = False
            if eliminated.brain:
                eliminated.brain.stop()
        self.last_result = {
            "round": self.round,
            "tally": tally,
            "votes": {p.alias: p.vote for p in self.players.values() if p.vote is not None},
            "eliminated": eliminated.alias if eliminated else None,
            "was_ai": eliminated.is_ai if eliminated else None,
            "model": eliminated.model if eliminated else None,
            "nickname": (eliminated.nickname if eliminated and not eliminated.is_ai else ""),
            "tie": bool(tally) and eliminated is None,
        }
        self.log({"ev": "result", **self.last_result})
        await self._set_phase("result", 12)
        # 剛被放逐的真人立刻拿到觀眾視角
        if eliminated and not eliminated.is_ai:
            await self.send(eliminated, {"type": "spectate_init", "players": self.reveal_all()})
        await asyncio.sleep(12)

    def _check_over(self) -> bool:
        humans, ais = self.counts()
        if ais == 0:
            self.winner = "humans"
        elif ais >= humans:
            self.winner = "ai"
        elif self.round >= self.cfg["max_rounds"]:
            self.winner = "humans"
        return self.winner is not None

    def reveal_all(self) -> list[dict]:
        return [{"alias": p.alias, "is_ai": p.is_ai, "model": p.model, "alive": p.alive,
                 "nickname": "" if p.is_ai else p.nickname} for p in self.players.values()]

    async def _game_over(self):
        self.phase = "over"
        for p in self.players.values():
            if p.brain:
                p.brain.stop()
        self.log({"ev": "over", "winner": self.winner, "cost_usd": self.cost_usd, "rounds": self.round})
        await self.push_state()
        await self.broadcast({"type": "game_over", "winner": self.winner, "players": self.reveal_all(),
                              "cost_usd": round(self.cost_usd, 3),
                              "log_id": os.path.basename(self.log_path),
                              "github_repo": config.GITHUB_REPO})

    def stop(self):
        if self.task:
            self.task.cancel()
        for p in self.players.values():
            if p.brain:
                p.brain.stop()

    # ---------- 紀錄 ----------
    def log(self, rec: dict):
        if not self.log_path:
            return
        rec = {"t": round(time.time(), 3), **rec}
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
