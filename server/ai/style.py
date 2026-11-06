"""台灣用語與去 AI 味的過濾。

hard_check() 回傳不過的原因清單（空的代表通過）
clean() 做無害的整理（去 Markdown、引號、多餘空白）
soft_score() 越高越像 AI，超過門檻就重生成
"""
from __future__ import annotations

import re

from .. import config

try:
    from opencc import OpenCC
    _s2t = OpenCC("s2t")
except Exception:  # 沒裝 OpenCC 時退化成只靠黑名單
    _s2t = None

# 中國用語（已是繁體字形）→ 台灣說法，只拿來偵測
CN_TERMS = [
    "視頻", "軟件", "信息", "質量", "牛逼", "沙發", "網友們", "立馬", "靠譜", "屏幕", "激活", "打印", "鼠標",
    "硬盤", "內存", "默認", "服務器", "高清", "智能手機", "移動支付", "短信", "小姐姐", "小哥哥",
    "給力", "坑爹", "逼格", "土豪", "佛系", "走心", "尬聊", "微信", "淘寶", "挺好", "挺有", "挺不",
    "啥", "咋", "咱", "這麼著", "整挺好", "老鐵", "兄弟們",
    "一會兒", "早上好", "晚上好", "下午好", "沒事兒", "玩兒", "哪兒", "這兒", "那兒", "點兒",
    "鏈接", "點擊", "登錄", "賬號", "充電寶", "出租車", "公交", "地鐵站", "幼兒園", "酸奶",
    "土豆", "西紅柿", "菠蘿", "獼猴桃", "方便面", "冰棍", "回車", "U盤", "優盤",
]
# 書面語／AI 味：硬擋
AI_PHRASES = [
    "首先", "其次", "再者", "總而言之", "總之", "總的來說", "作為一個", "作為一名", "值得注意", "的確",
    "不禁", "然而", "此外", "綜上", "換句話說", "無論如何", "我理解你", "我明白你", "很高興", "讓我們", "好問題",
    "有趣的", "說得好", "也就是說", "簡單來說", "宛如", "彷彿", "語言模型", "助理", "協助", "歡迎", "請問", "祝你",
]
# 偏書面但台灣人也會用：只扣分
SOFT_PHRASES = ["確實", "顯然", "基本上", "實際上", "事實上", "坦白說", "老實說", "我認為", "似乎", "因此",
                "以及", "並且", "對此", "關於", "層面", "角度", "邏輯", "分析", "觀察", "推測", "重要的是", "本質", "核心"]


# 這些字 OpenCC 會「升級」成另一個繁體字，但在台灣本來就這樣寫
TW_OK = set("台后里干采云丑几斗占征准游伙")


def has_simplified(text: str) -> bool:
    if _s2t is None:
        return False
    return any(_s2t.convert(c) != c and c not in TW_OK for c in text if "一" <= c <= "鿿")


def clean(text: str) -> str:
    text = re.sub(r"[*_`#>]+", "", text)
    text = re.sub(r"^\s*(\d+[.、)]|[-•])\s*", "", text, flags=re.M)
    text = text.replace("「", "").replace("」", "").replace('"', "").replace("'", "")
    text = re.sub(r"\s*\n\s*", " ", text)
    text = re.sub(r"[ 　]{2,}", " ", text)
    text = re.sub(r"[!！]{2,}", "！", text)
    text = re.sub(r"[?？]{2,}", "？", text)
    return text.strip()


def hard_check(text: str) -> list[str]:
    bad: list[str] = []
    if not text:
        bad.append("空的")
        return bad
    if len(text) > config.MAX_MSG_CHARS:
        bad.append(f"太長（{len(text)} 字，上限 {config.MAX_MSG_CHARS}）")
    if has_simplified(text):
        bad.append("含簡體字")
    for t in CN_TERMS:
        if t in text:
            bad.append(f"中國用語「{t}」")
            break
    hits = [p for p in AI_PHRASES if p in text]
    if hits:
        bad.append(f"書面語「{'、'.join(hits[:3])}」")
    if re.search(r"[①-⑳①-⑩]|第[一二三]點", text):
        bad.append("條列")
    return bad


def soft_score(text: str) -> int:
    s = 0
    if text.endswith("。"):
        s += 1
    if text.count("，") >= 3:
        s += 1
    if len(text) > 30:
        s += 1
    if re.search(r"[，。；：]", text) and not re.search(r"[ 　]", text) and len(text) > 15:
        s += 1  # 全部用標點、完全不用空格斷句
    if re.search(r"(我覺得|我認為).{0,6}(因為|所以)", text):
        s += 1
    if re.search(r"(呢|吧|哦)[。！]?$", text) and len(text) > 20:
        s += 1
    emojis = re.findall(r"[\U0001F300-\U0001FAFF☀-➿]", text)
    if len(emojis) > 1:
        s += 1
    s += min(2, sum(1 for p in SOFT_PHRASES if p in text))
    return s


def check(text: str) -> tuple[str, list[str]]:
    """回傳 (整理後文字, 不過的原因)。"""
    t = clean(text)
    reasons = hard_check(t)
    if soft_score(t) >= 3:
        reasons.append("太像作文：句子太完整、標點太工整")
    return t, reasons
