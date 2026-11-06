"""驗證、去識別化一份對局紀錄，放進 data/games/。

用法：
  python scripts/ingest.py --input logs/xxx.jsonl --out data/games/xxx.jsonl
  python scripts/ingest.py --issue-body body.md --issue 12 --out-dir data/games

從 Issue 來的話會先把表單裡「對局紀錄」那格的內容抽出來，
並把「AI 哪裡露餡」等回答以 feedback 事件附在檔尾。
回傳碼 0 = 通過，1 = 不合格（原因印在 stdout，Action 會貼回 Issue）。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

REQUIRED_EVENTS = {"start", "result", "over"}
MAX_LINES = 5000
MAX_CHARS = 1_000_000

PII_PATTERNS = [
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "[email]"),
    (re.compile(r"(?<!\d)09\d{2}[- ]?\d{3}[- ]?\d{3}(?!\d)"), "[phone]"),
    (re.compile(r"(?<!\d)0\d[- ]?\d{3,4}[- ]?\d{4}(?!\d)"), "[phone]"),
    (re.compile(r"(?<![A-Z])[A-Z][12]\d{8}(?!\d)"), "[id]"),
    (re.compile(r"https?://\S+"), "[url]"),
    (re.compile(r"(?i)(line|ig|instagram|fb|discord|threads)\s*(id|帳號|是)?\s*[:：]?\s*[A-Za-z0-9_.@-]{3,}"), "[handle]"),
    (re.compile(r"\d{1,4}\s*(?:巷|弄|號)\s*(?:\d+\s*樓)?(?:之\s*\d+)?"), "[address]"),
]
TEXT_FIELDS = ("text", "note", "reason")


def redact(s: str) -> str:
    for pat, rep in PII_PATTERNS:
        s = pat.sub(rep, s)
    return s


def extract_from_issue_body(body: str) -> tuple[str, dict]:
    """Issue Form 的 body 是 Markdown：### 欄位標題\\n\\n內容。抽出紀錄與回饋。"""
    sections: dict[str, str] = {}
    cur = None
    for line in body.splitlines():
        m = re.match(r"^###\s+(.+?)\s*$", line)
        if m:
            cur = m.group(1).strip()
            sections[cur] = ""
        elif cur is not None:
            sections[cur] += line + "\n"
    log = sections.get("對局紀錄", "")
    log = re.sub(r"^\s*```[a-zA-Z]*\s*$", "", log, flags=re.M)
    fb = {k: sections.get(k, "").strip() for k in ("這局有幾個真人", "你覺得 AI 哪裡露餡（選填）", "有沒有 AI 騙過你們？為什麼（選填）")}
    fb = {k: v for k, v in fb.items() if v and v != "_No response_"}
    return log.strip(), fb


def validate(lines: list[str]) -> tuple[list[dict], list[str]]:
    errs: list[str] = []
    recs: list[dict] = []
    if len(lines) > MAX_LINES:
        errs.append(f"行數太多（{len(lines)} > {MAX_LINES}）")
    for i, ln in enumerate(lines, 1):
        ln = ln.strip()
        if not ln:
            continue
        try:
            r = json.loads(ln)
        except json.JSONDecodeError:
            errs.append(f"第 {i} 行不是合法 JSON")
            if len(errs) > 5:
                break
            continue
        if not isinstance(r, dict) or "ev" not in r:
            errs.append(f"第 {i} 行缺少 ev 欄位")
            continue
        recs.append(r)
    evs = {r["ev"] for r in recs}
    missing = REQUIRED_EVENTS - evs
    if missing:
        errs.append(f"缺少事件：{'、'.join(sorted(missing))}（要完整打完一局才能上傳）")
    start = next((r for r in recs if r["ev"] == "start"), None)
    if start:
        players = start.get("players", [])
        humans = [p for p in players if not p.get("is_ai")]
        ais = [p for p in players if p.get("is_ai")]
        if len(humans) < 2:
            errs.append("真人少於 2 個，這種局對演化沒有參考價值")
        if not ais:
            errs.append("沒有 AI 玩家")
    chats = [r for r in recs if r["ev"] == "chat"]
    if len(chats) < 10:
        errs.append(f"聊天太少（{len(chats)} 則）")
    return recs, errs


def sanitize(recs: list[dict]) -> list[dict]:
    out = []
    for r in recs:
        r = dict(r)
        for k in TEXT_FIELDS:
            if isinstance(r.get(k), str):
                r[k] = redact(r[k])
        if r["ev"] == "start" and isinstance(r.get("cfg"), dict):
            r["cfg"] = {k: v for k, v in r["cfg"].items() if k != "password"}
        out.append(r)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input")
    ap.add_argument("--issue-body")
    ap.add_argument("--issue", type=int, default=0)
    ap.add_argument("--uploader", default="", help="上傳者的 GitHub 帳號，天梯用")
    ap.add_argument("--out")
    ap.add_argument("--out-dir", default="data/games")
    a = ap.parse_args()

    feedback: dict = {}
    if a.issue_body:
        body = Path(a.issue_body).read_text(encoding="utf-8")
        text, feedback = extract_from_issue_body(body)
        if not text:
            print("表單裡找不到「對局紀錄」的內容")
            return 1
    else:
        text = Path(a.input).read_text(encoding="utf-8")
    if len(text) > MAX_CHARS:
        print(f"內容太大（{len(text)} 字元）")
        return 1

    recs, errs = validate(text.splitlines())
    if errs:
        print("不合格：\n- " + "\n- ".join(errs))
        return 1
    recs = sanitize(recs)
    for r in recs:
        if r["ev"] == "start":
            r["uploader"] = a.uploader
            r["issue"] = a.issue
    if feedback:
        recs.append({"t": recs[-1].get("t", 0), "ev": "feedback", **{k: redact(v) for k, v in feedback.items()}})

    if a.out:
        out = Path(a.out)
    else:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
        out = Path(a.out_dir) / f"{stamp}_issue{a.issue or 0}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in recs) + "\n", encoding="utf-8")

    start = next(r for r in recs if r["ev"] == "start")
    over = next(r for r in recs if r["ev"] == "over")
    humans = sum(1 for p in start["players"] if not p.get("is_ai"))
    ais = len(start["players"]) - humans
    print(json.dumps({"ok": True, "file": str(out), "humans": humans, "ais": ais, "rounds": over.get("rounds"),
                      "winner": over.get("winner"), "chats": sum(1 for r in recs if r["ev"] == "chat"),
                      "human_reasons": sum(1 for r in recs if r["ev"] in ("vote", "vote_reason") and not r.get("is_ai") and r.get("reason"))},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
