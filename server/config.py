"""全域設定：模型、預設房間參數、費用表。"""
import os
from dotenv import load_dotenv

# override=True：專案的 .env 優先於系統環境變數，避免被舊 key 蓋掉
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"), override=True)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()

# 兩個用途層：chat 是主力發言與投票，judge 是便宜的小判斷
MODELS = {
    "anthropic": {"chat": ["claude-opus-5-5", "claude-sonnet-5-5"], "judge": "claude-haiku-5-5"},
    "openai": {"chat": ["gpt-5.5", "gpt-5.4"], "judge": "gpt-5.4-mini"},
}

# 每百萬 token 的美金價格 (input, output)，只用來估算
PRICES = {
    "claude-opus-5-5": (4.0, 20.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-haiku-5-5": (0.1, 0.5),
    "gpt-5.5": (2.5, 10.0),
    "gpt-5.4": (2.0, 8.0),
    "gpt-5.4-mini": (0.3, 1.2),
}

DEFAULT_ROOM = {
    "ai_count": 2,
    "discuss_seconds": 150,
    "vote_seconds": 30,
    "topics_on": True,
    "ai_know_each_other": False,
    "night_kill": True,        # 還有 AI 活著時，每輪放逐後的夜晚 AI 會帶走一個真人
    "reveal_on_exit": True,    # 出局就揭曉身分、看得到 AI 小抄；關掉就到結局才揭曉
    "max_rounds": 6,
    "model_strategy": "auto",  # auto | anthropic | openai
    "budget_usd": 3.0,
    "password": "",
}

MAX_MSG_CHARS = 60
ROOT = os.path.dirname(os.path.dirname(__file__))
LOG_DIR = os.path.join(ROOT, "logs")
GENOMES_FILE = os.path.join(ROOT, "genomes", "best.json")

# 遊戲結束畫面「上傳到 GitHub」會開這個 repo 的 Issue。預設是本專案；自己 fork 的話在 .env 改成 "owner/repo"
GITHUB_REPO = os.getenv("GITHUB_REPO", "").strip() or "Hikari-Tsai/ai-werewolf"

# 隧道開好之後由 server.tunnel 填入，前端會顯示成邀請連結
PUBLIC_URL = os.getenv("PUBLIC_URL", "").strip()
