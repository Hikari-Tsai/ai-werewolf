"""FastAPI 入口：靜態頁、WebSocket、房間管理。"""
from __future__ import annotations

import json
import os
import random
import re
import string

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from . import config
from .room import Room, Player
from .ai.brain import AIBrain
from .ai.llm import router

WEB = os.path.join(os.path.dirname(os.path.dirname(__file__)), "web")
app = FastAPI()
app.mount("/static", StaticFiles(directory=WEB), name="static")
rooms: dict[str, Room] = {}


@app.middleware("http")
async def no_cache_static(request, call_next):
    """前端是靜態檔、沒有版本號，改完要重新整理就生效，所以叫瀏覽器每次都回來問。"""
    resp = await call_next(request)
    if request.url.path.startswith("/static/") or request.url.path == "/":
        resp.headers["Cache-Control"] = "no-cache"
    return resp


@app.get("/")
async def index():
    return FileResponse(os.path.join(WEB, "index.html"))


@app.get("/api/health")
async def health():
    return {"ok": True, "providers": router.available(), "rooms": len(rooms)}


@app.get("/api/qr")
async def qr(text: str):
    """把邀請連結畫成 QR code（SVG），給房間畫面用。"""
    if not re.fullmatch(r"https?://[^\s]{1,300}", text):
        return PlainTextResponse("bad text", status_code=400)
    import qrcode
    from qrcode.image.svg import SvgPathFillImage  # 自帶白底，深色主題上才掃得到
    img = qrcode.make(text, image_factory=SvgPathFillImage, box_size=10, border=1)
    return PlainTextResponse(img.to_string(encoding="unicode"), media_type="image/svg+xml",
                             headers={"Cache-Control": "public, max-age=3600"})


@app.get("/api/log/{log_id}")
async def get_log(log_id: str):
    """只提供已經結束的對局紀錄，給下載／上傳用。"""
    if not re.fullmatch(r"\d{8}_\d{6}_[A-Z0-9]{2,8}\.jsonl", log_id):
        return PlainTextResponse("bad id", status_code=400)
    path = os.path.join(config.LOG_DIR, log_id)
    if not os.path.exists(path):
        return PlainTextResponse("not found", status_code=404)
    with open(path, encoding="utf-8") as f:
        text = f.read()
    if '"ev": "over"' not in text:
        return PlainTextResponse("game not over", status_code=403)
    return PlainTextResponse(text, media_type="application/x-ndjson",
                             headers={"Content-Disposition": f'attachment; filename="{log_id}"'})


def new_code() -> str:
    while True:
        code = "".join(random.choices(string.ascii_uppercase.replace("O", "").replace("I", "") + "23456789", k=4))
        if code not in rooms:
            return code


CODE_RE = re.compile(r"[A-Z0-9]{2,8}")


def evict_if_over(code: str):
    """已經結束的房間不佔房號：有人要用同一個房號就把舊房收掉，還留在結局畫面的人不受影響。"""
    r = rooms.get(code)
    if r and r.phase == "over":
        r.stop()
        rooms.pop(code, None)


def check_code(raw: str) -> tuple[str, str]:
    """自訂房號：2 到 8 個英數字。回傳 (正規化後的房號, 錯誤訊息)。"""
    code = (raw or "").strip().upper()
    if not CODE_RE.fullmatch(code):
        return code, "房號要 2 到 8 個英文或數字"
    evict_if_over(code)
    if code in rooms:
        return code, "這個房號已經有人用了，換一個"
    return code, ""


async def err(ws: WebSocket, text: str):
    await ws.send_text(json.dumps({"type": "error", "text": text}, ensure_ascii=False))


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    room: Room | None = None
    me: Player | None = None
    try:
        while True:
            raw = await ws.receive_text()
            try:
                m = json.loads(raw)
            except json.JSONDecodeError:
                continue
            t = m.get("type")

            # ----- 進房前 -----
            if t == "create":
                if (m.get("code") or "").strip():
                    code, why = check_code(m["code"])
                    if why:
                        await err(ws, why)
                        continue
                else:
                    code = new_code()
                room = rooms[code] = Room(code)
                me = room.add_human(m.get("nickname", ""), ws)
                await ws.send_text(json.dumps({"type": "joined", "pid": me.pid, "code": room.code}))
                await room.push_state()
                continue
            if t == "join":
                code = (m.get("code") or "").upper().strip()
                r = rooms.get(code)
                if r and r.phase == "over" and not (m.get("pid") in r.players):
                    await err(ws, "這間房已經結束了，可以用同一個房號開新房")
                    continue
                if not r:
                    await err(ws, "找不到這個房號")
                    continue
                pid = m.get("pid")
                if pid and pid in r.players and not r.players[pid].is_ai and not r.players[pid].connected:
                    # 重連（同一個瀏覽器開第二個分頁時，原本的人還在線，就當新玩家）
                    me = r.players[pid]
                    me.ws, me.connected = ws, True
                    room = r
                else:
                    if r.phase != "lobby":
                        await err(ws, "這局已經開始了，等下一局")
                        continue
                    if r.cfg["password"] and m.get("password", "") != r.cfg["password"]:
                        await err(ws, "密碼錯誤")
                        continue
                    room = r
                    me = room.add_human(m.get("nickname", ""), ws)
                await ws.send_text(json.dumps({"type": "joined", "pid": me.pid, "code": room.code}))
                await room.push_state()
                if room.phase != "lobby":
                    await ws.send_text(json.dumps({"type": "history", "chat": room.chat[-200:]}, ensure_ascii=False))
                    if not me.alive and (room.cfg["reveal_on_exit"] or room.phase == "over"):
                        await ws.send_text(json.dumps({"type": "spectate_init", "players": room.reveal_all()}, ensure_ascii=False))
                continue
            if room is None or me is None:
                await err(ws, "請先建立或加入房間")
                continue

            # ----- 進房後 -----
            if t == "host_config" and me.pid == room.host_pid and room.phase == "lobby":
                c = m.get("cfg", {})
                for k, v in c.items():
                    if k in room.cfg:
                        room.cfg[k] = type(room.cfg[k])(v) if not isinstance(room.cfg[k], bool) else bool(v)
                room.cfg["ai_count"] = max(0, min(8, room.cfg["ai_count"]))
                room.cfg["discuss_seconds"] = max(30, min(600, room.cfg["discuss_seconds"]))
                room.cfg["vote_seconds"] = max(10, min(120, room.cfg["vote_seconds"]))
                room.cfg["max_rounds"] = max(1, min(20, room.cfg["max_rounds"]))
                await room.push_state()
            elif t == "rename" and me.pid == room.host_pid and room.phase == "lobby":
                code, why = check_code(m.get("code", ""))
                if code == room.code:
                    continue
                if why:
                    await err(ws, why)
                    continue
                rooms.pop(room.code, None)
                rooms[code] = room
                room.code = code
                await room.push_state()
            elif t == "start" and me.pid == room.host_pid and room.phase == "lobby":
                humans = [p for p in room.players.values() if not p.is_ai]
                if len(humans) < 2 and room.cfg["ai_count"] < 1:
                    await err(ws, "至少要兩個真人或一個 AI")
                    continue
                if room.cfg["ai_count"] > 0 and not router.available():
                    await err(ws, "沒有可用的 API key，無法加入 AI")
                    continue
                # 清掉舊 AI、依設定重新加
                for p in [p for p in room.players.values() if p.is_ai]:
                    room.remove_player(p)
                for i in range(room.cfg["ai_count"]):
                    room.add_ai(lambda r, p, i=i: AIBrain(r, p, i))
                # 座位洗牌：不然 AI 永遠排在最後加入的位置，一看就知道
                room.shuffle_seats()
                room.start()
                await room.push_state()
            elif t == "typing":
                await room.set_typing(me, bool(m.get("on")))
            elif t == "chat":
                await room.post_chat(me, str(m.get("text", "")))
            elif t == "vote":
                await room.cast_vote(me, m.get("target"), str(m.get("reason", "")))
            elif t == "vote_reason":
                room.vote_reason(me, str(m.get("reason", "")))
            elif t == "end" and me.pid == room.host_pid:
                if room.phase == "lobby":
                    # 大廳：解散房間，大家回首頁
                    await room.broadcast({"type": "room_closed", "text": "房主解散了房間"})
                    room.stop()
                    if rooms.get(room.code) is room:
                        rooms.pop(room.code, None)
                else:
                    await room.abort()
            elif t == "leave":
                break
    except WebSocketDisconnect:
        pass
    finally:
        if room and me:
            room.remove_player(me)
            if not any(p.connected for p in room.players.values() if not p.is_ai):
                room.stop()
                if rooms.get(room.code) is room:   # 房號可能已經被新房拿走
                    rooms.pop(room.code, None)
            else:
                await room.push_state()
