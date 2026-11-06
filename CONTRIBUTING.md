# 參與方式

謝謝你想幫忙。這個專案的目標只有一個：讓 AI 在台灣的聊天室裡裝人裝得更像，讓真人更難抓。
貢獻不一定要寫程式，最有價值的其實是「玩一局然後把紀錄分享出來」。

## 1. 分享對局紀錄（最需要）

AI 要變強，需要真人局的資料：真人怎麼講話、真人憑什麼投出 AI。

1. 玩一局（至少 2 個真人，1 個以上 AI，打到結束）。
2. 投票時盡量填「為什麼投這個人」，那是最有用的訊號。
3. 結束畫面按「上傳到 GitHub」（房主要在 `.env` 設 `GITHUB_REPO`），或按「下載紀錄」再用
   [分享一局對局紀錄](../../issues/new?template=upload-log.yml) 這個 Issue 表單貼上。
4. 表單裡的「AI 哪裡露餡」請認真寫，這會直接進裁判的校準資料。

機器人會檢查格式、遮掉電話與 Email 等個資，然後開 PR 放進 `data/games/`。
**上傳前請確認同房的人都同意公開聊天內容。** 放進去的紀錄以 CC0 釋出。

## 2. 加題目、加人設素材

- 話題在 `server/topics.py`。挑題原則：答案瑣碎、具體、帶情緒，需要在地經驗，真人脫口而出但 AI 容易答得像作文。
- 人設素材（城市、職業、嗜好、語助詞、個性）在 `server/ai/persona.py`。
- 台灣聊天室的範例句在 `server/ai/prompts.py` 的 `EXAMPLES`，請用真的會出現在群組裡的句子。
- 中國用語與書面語黑名單在 `server/ai/style.py`，加詞時請確認台灣人真的不會這樣講，別把常用詞也擋掉。

這類改動直接開 PR 就好，不用先開 Issue。

## 3. 回報 AI 露餡

如果你發現 AI 有某種固定的破綻（例如「每次都用某個詞」「被點名一定秒回」），開一個 Issue 描述：
- 哪個模型（結局畫面會顯示）
- 它講了什麼、前後文是什麼
- 你為什麼覺得那像 AI

附上對局紀錄更好。

## 4. 改程式

### 環境

```bash
git clone https://github.com/Hikari-Tsai/ai-werewolf.git
cd ai-werewolf
cp .env.example .env     # 至少填一家 API key
python -m venv .venv && source .venv/bin/activate   # Windows 直接 .\run.ps1
pip install -r requirements.txt
python run.py
```

### 結構

| 目錄 | 內容 |
|---|---|
| `server/room.py` | 房間、玩家、階段狀態機。真人和 AI 走同一條路，前端拿不到任何能分辨 AI 的欄位 |
| `server/ai/brain.py` | AI 的主迴圈：要不要講、生成、過濾、照人類節奏送出 |
| `server/ai/style.py` | 台灣用語與去 AI 味的三道關卡 |
| `server/ai/timing.py` | 閱讀、思考、打字、分段、猶豫的時間模型 |
| `server/ai/llm.py` | Claude 與 OpenAI 的統一介面、路由、備援、費用估算 |
| `web/` | 單頁前端，沒有打包步驟 |
| `evolve/` | 模擬對局、模擬真人、裁判、提示詞演化 |
| `scripts/` | 紀錄驗證與去識別化、天梯 |

細節見 [ARCHITECTURE.md](ARCHITECTURE.md)。

### 原則

- **不能讓前端分辨 AI。** 任何送到瀏覽器的資料都不能帶 `is_ai`、模型名或只有 AI 會有的欄位，除了揭曉和觀眾視角。改 `room.py` 的 `state_for`、`broadcast` 時請特別注意。
- **AI 和真人用同一條管線。** AI 送訊息、送「正在輸入」都要經過 `Room.post_chat`、`Room.set_typing`，不要另開後門。
- **先用規則，再用 prompt。** 回太快、字數太穩、每句都回答這類破綻，用 `timing.py`、`style.py` 的規則修比改 prompt 可靠。
- **只用台灣的繁體中文。** 程式註解、UI 文字、prompt 都是。不確定的用語可以用 `style.py` 的檢查跑一下。
- **花錢的改動要能關掉。** 新增任何會呼叫模型的功能，要能用設定關閉，並算進 `room.cost_usd`。

### 送 PR 之前

```bash
python -c "import server.app, evolve.evolve"          # 能載入
python scripts/ingest.py --input logs/某一局.jsonl --out /tmp/t.jsonl   # 動到紀錄格式時
python scripts/leaderboard.py --data data/games --out /tmp/LB.md       # 動到天梯時
```

然後實際開一局，至少 1 個真人加 1 個 AI，打到結束畫面。PR 說明裡寫你改了什麼、怎麼測的。

## 5. 演化結果的 PR

`evolve` workflow 會定期開 PR 更新 `genomes/best.json`。合併前請看 `genomes/REPORT.md`：
- 新策略有沒有變成只針對 AI 裁判的癖好（例如全部不打句號）
- 有沒有出現簡體字、中國用語、或奇怪的指令
- 分數有沒有真的比上一代高

覺得怪就關掉 PR，不用客氣。

## 授權

程式以 MIT 釋出；`data/games/` 的對局紀錄以 CC0 釋出。送 PR 代表你同意以同樣的授權釋出你的貢獻。
