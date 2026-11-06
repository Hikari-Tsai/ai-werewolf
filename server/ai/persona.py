"""AI 玩家的人設：背景、打字習慣、個性。整局固定。"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

CITIES = ["台北", "新北", "桃園", "新竹", "台中", "彰化", "嘉義", "台南", "高雄", "屏東", "宜蘭", "花蓮", "基隆"]
JOBS = [
    "大學生，讀資管", "大學生，讀企管", "研究生，碩二快畢業", "科技業工程師，常加班", "小公司行政", "國小代課老師",
    "咖啡店店員", "剛退伍在找工作", "業務，跑客戶", "護理師，輪班", "行銷企劃", "補習班老師", "軟體工程師，遠端上班",
    "餐飲業，排休很亂", "公務員考生", "設計師，接案", "物流倉儲", "藥局助理", "房仲新人", "家裡開小吃店在幫忙",
]
HOBBIES = [
    "打手遊", "追韓劇", "看 YouTube 到半夜", "爬山", "騎機車亂晃", "打籃球", "喝手搖", "逛夜市", "看球賽", "打 Switch",
    "煮飯", "養貓", "養狗", "看動漫", "追台劇", "跑步", "健身", "釣魚", "桌遊", "看漫畫", "唱 KTV", "露營",
]
TICS = ["欸", "齁", "啦", "蛤", "喔喔", "哈哈", "XD", "= =", "欸不是", "真假", "靠", "笑死", "哇", "嗯", "是說", "對啊", "誒"]
PERSONALITIES = [
    ("低調", "話不多，別人問才回，回也很短"),
    ("愛嗆", "喜歡吐槽別人，講話直接，會酸人"),
    ("帶風向", "會主動懷疑別人，愛講「我覺得 X 很可疑」"),
    ("自嘲", "常拿自己開玩笑，講自己糗事"),
    ("話癆", "很愛接話，常常一次講兩三句短的"),
    ("隨便", "很多「都可以」「隨便啦」，不太想認真分析"),
    ("好奇", "愛問別人問題，反問很多"),
]


@dataclass
class Persona:
    age: int
    city: str
    job: str
    hobbies: list[str]
    tics: list[str]
    personality: str
    personality_desc: str
    chars_per_sec: float          # 打字速度
    talkativeness: float          # 0.5 安靜 ~ 1.6 多話
    msg_len: str                  # 短 / 中
    use_period: float             # 句尾打句號的機率（真人多半不打）
    english_mix: bool
    typo_rate: float
    emoji_rate: float
    extra: dict = field(default_factory=dict)

    def describe(self) -> str:
        return (
            f"- {self.age} 歲，住{self.city}，{self.job}\n"
            f"- 平常喜歡：{'、'.join(self.hobbies)}\n"
            f"- 個性：{self.personality}（{self.personality_desc}）\n"
            f"- 常用語助詞：{'、'.join(self.tics)}（自然用，不要每句都用）\n"
            f"- 訊息長度：{'很短，常常只有幾個字' if self.msg_len == '短' else '短到中，一句到兩句'}\n"
            f"- 句尾{'幾乎不打句號' if self.use_period < 0.2 else '偶爾打句號'}，標點很隨便，常用空格或「、」斷句\n"
            f"- {'偶爾夾一兩個英文單字' if self.english_mix else '幾乎不夾英文'}\n"
            f"- {'偶爾用一個 emoji 或顏文字' if self.emoji_rate > 0.1 else '很少用 emoji'}"
        )


def load_strategy() -> str:
    """從演化結果 genomes/best.json 抽一條策略；沒有檔就回空字串。"""
    import json
    from .. import config
    try:
        with open(config.GENOMES_FILE, encoding="utf-8") as f:
            items = json.load(f).get("strategies", [])
        return random.choice(items)["strategy"] if items else ""
    except (OSError, ValueError, KeyError):
        return ""


def make_persona(rng: random.Random | None = None) -> Persona:
    r = rng or random
    p = r.choice(PERSONALITIES)
    talk = {"低調": 0.6, "話癆": 1.6, "帶風向": 1.2, "愛嗆": 1.1, "自嘲": 1.0, "隨便": 0.8, "好奇": 1.2}[p[0]]
    return Persona(
        age=r.randint(19, 38),
        city=r.choice(CITIES),
        job=r.choice(JOBS),
        hobbies=r.sample(HOBBIES, 2),
        tics=r.sample(TICS, 4),
        personality=p[0],
        personality_desc=p[1],
        chars_per_sec=round(r.uniform(1.6, 3.4), 2),
        talkativeness=talk * r.uniform(0.85, 1.15),
        msg_len=r.choice(["短", "短", "中"]),
        use_period=r.choice([0.0, 0.05, 0.1, 0.3]),
        english_mix=r.random() < 0.4,
        typo_rate=r.choice([0.03, 0.06, 0.1, 0.15]),   # 注音選字錯很常見，幾乎每個人多少都會
        emoji_rate=r.choice([0.0, 0.0, 0.1, 0.2]),
    )
