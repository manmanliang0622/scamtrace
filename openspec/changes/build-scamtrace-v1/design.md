# Design

## Context

全新專案，三天內（2026/10/9–10/11）由一人完成，作為書審作品。動機見 proposal.md – Why；行為規格見 `specs/`。技術選型固定為 Python 3.12+／Flask 3.x／Jinja2／SQLite／原生 JS，語言模型使用 Anthropic `claude-opus-5-5`。

## Goals / Non-Goals

**Goals:**
- 個資在本機處理：資料庫與語言模型只看得到遮罩後文字。
- 單機即可執行（SQLite 單一檔案），沒有 API 憑證也能用規則比對完成整個流程。
- 模組切分清楚，方便寫單元測試與作品說明。

**Non-Goals:**
- 多人同時高流量、水平擴充、背景工作佇列（分析在請求內同步完成）。
- 前端框架或外部圖表庫。
- 正式部署到雲端（只需在本機示範；Cookie 的 `Secure` 屬性在 HTTPS 部署時再開）。

## Decisions

### 架構與模組

```
瀏覽器（上傳頁 → 預覽頁 → 結果頁；我的案例／後台／日誌）
   │ HTTP：表單 POST＋少量 JSON API
Flask app.py
   ├─ auth.py        登入、註冊、權限、CSRF、鎖定、日誌寫入
   ├─ parser.py      LINE 匯出檔 → 訊息清單
   ├─ deidentify.py  個資偵測與遮罩（本機）
   ├─ analyzer.py    語言模型為主、規則為備援
   ├─ risk.py        每則風險、整體風險、轉折點
   └─ stats.py       後台統計查詢
   │ SQL（? 參數化）                 │ HTTPS（只送遮罩後文字）
SQLite instance/scam.db               Anthropic API claude-opus-5-5
```

`parser`、`deidentify`、`risk` 寫成純函式（輸入資料、回傳資料、不碰資料庫與 Flask），以便單元測試。

### 處理流程與原文生命週期

1. 上傳 .txt 或貼上文字，選擇「哪個名字是我」。
2. parser 切訊息 → deidentify 遮罩、發話者改「我／對方A／對方B」。
3. 遮罩後訊息與 PII 計數寫入 `instance/pending/<token>.json`（`secrets.token_urlsafe`），Session 只放 token 與擁有者。原文與「代號 ↔ 原值」對照表只存在該次請求記憶體，請求結束即丟棄。
4. 預覽頁可手動補遮（對暫存檔中的遮罩後文字做替換）。
5. 確認送出 → 寫入 `cases`、`messages`、`case_pii_stats` → 刪除暫存檔 → analyzer → risk → 寫入結果 → 導向結果頁。
6. 清理：應用程式啟動時與每次上傳時，刪除超過 30 分鐘的暫存檔。

**為何用伺服器端暫存檔而非 Session**：Flask 預設 Session 是簽章 Cookie，內容會被送到瀏覽器且有 4 KB 限制；暫存檔可控大小與刪除時間。替代方案「預覽前就寫入資料庫並標 pending」會讓未確認的資料進資料庫，與隱私目標衝突，不採用。

**手動補遮的取捨**：因原文已丟棄，補遮只能作用在遮罩後文字上（使用者看到什麼就遮什麼），這正好符合「預覽所見即送出內容」。

### 資料模型

```
users 1 ── N cases 1 ── N messages N ── N tactics   （透過 message_tactics）
                │ 1                │
                │ N                │ 0..1
          case_pii_stats        feedback N ── 1 users
users 1 ── N audit_logs
scam_types 1 ── N cases
```

| 資料表 | 重點欄位 |
|---|---|
| users | username（UNIQUE，4–30 英數底線）、password_hash（scrypt）、role CHECK('user','admin')、failed_logins、locked_until、created_at |
| scam_types | code UNIQUE、name、description（查找表，seed 建立） |
| tactics | code UNIQUE、name、name_en、description、color（查找表，含 urgency_threat 共 8 筆） |
| cases | user_id FK NOT NULL、title、source_type CHECK('line_txt','paste')、is_demo、message_count、period_start/end、status CHECK('pending','analyzed','failed')、overall_risk 0–100、risk_level CHECK('low','medium','high')、scam_type_id FK NULL、summary、turning_point_seq、analyzed_by CHECK('llm','rule')、model_name、created_at、analyzed_at |
| messages | case_id FK ON DELETE CASCADE、seq（從 1，(case_id, seq) UNIQUE）、sent_at、speaker、is_self、masked_text、msg_type CHECK('text','sticker','image','file','call','system')、stage CHECK('contact','rapport','setup','action','pressure','none')、risk_score、requests_action |
| message_tactics | PK(message_id, tactic_id)、message_id FK CASCADE、tactic_id FK、evidence NOT NULL、confidence 0–1（規則固定 0.5） |
| case_pii_stats | PK(case_id, pii_type)、count；不存原值 |
| feedback | case_id FK CASCADE、message_id FK NULL（NULL＝整體判斷）、user_id、is_correct、corrected_tactic_id FK NULL、comment（≤200 字）、created_at |
| audit_logs | user_id NULL、action、target（如 case:12）、detail（不得含對話內容或密碼）、ip、created_at |

索引：`messages(case_id, seq)`、`cases(user_id, created_at)`、`audit_logs(created_at)`、`message_tactics(tactic_id)`。
連線時執行 `PRAGMA foreign_keys = ON`，否則 SQLite 不會執行 `ON DELETE CASCADE`。

### 去識別化實作

- 規則依序套用：卡號（13–19 位＋Luhn）→ 身分證 `[A-Z][12]\d{8}` → 居留證 `[A-Z][A-D89]\d{8}` → Email → 網址（保留網域，路徑換 `[路徑]`）→ 手機 `09\d{2}-?\d{3}-?\d{3}`／`+886 9…` → 市話 `0\d{1,2}-?\d{6,8}` → 銀行帳號 10–16 位數字 → LINE ID（「ID」「line id」「加我」後接英數）→ 地址 `(.{2}[縣市])?.{1,3}[區鄉鎮市].{1,10}[路街道].{0,10}號` → 發話者名字。
- 每種類型一個「原值 → 編號」字典，整段對話共用，確保同值同代號。
- 已被替換的區段不再被後續規則比對（先替換成佔位符再比下一條規則）。

### 語言模型分析

- 模型 `claude-opus-5-5`，`output_config.effort = "medium"`，`output_config.format` 提供 JSON schema 限制輸出。
- 啟用伺服器端備援：`betas=["server-side-fallback-2026-07-01"]`、`fallbacks="default"`。
- 輸入格式：每行 `#序號 [時間] 發話者：內容`；非文字訊息以 `[貼圖]` 等標記保留位置。
- 提示詞寫入：分類定義（tactics／stages／scam_types）、只標對方訊息、evidence 必須逐字取自原訊息、讚美推薦單獨出現不代表詐騙。
- 輸出 schema：
  ```json
  {"messages":[{"seq":12,"stage":"action","requests_action":true,
    "tactics":[{"code":"scarcity","evidence":"名額只剩今天","confidence":0.9}]}],
   "scam_type":"investment","is_likely_scam":true,"summary":"…"}
  ```
- 切段：每段 150 則，前後重疊 10 則；重疊訊息採後段結果；`scam_type`、`summary` 取最後一段或綜合（實作時以最後一段為主並記錄）。
- 程式驗證：seq 存在、code 在查找表、evidence 為子字串、「我」的訊息上的手法丟棄；丟棄筆數寫入 log（不寫內容）。

**為何模型為主、規則為備援**：關鍵詞規則難以處理語境（例如朋友間的讚美），但無憑證或 API 失敗時仍需可示範；兩者並存也正好成為評估比較的兩組。

### 規則比對

`lexicon/` 下每個手法與階段一份 JSON 關鍵詞表（例如 scarcity：限時、只剩、今天截止、最後機會）。命中的關鍵詞即為 evidence，confidence 固定 0.5；`requests_action` 由 action 類關鍵詞（匯款、轉帳、驗證碼、點連結、下載、加入群組）判定。

### 風險計分

```
每則：risk = min(100, 階段分數 + 15 × 手法數 + (requests_action ? 25 : 0))
階段分數：contact 0／rapport 5／setup 15／pressure 30／action 40／none 0
整體：overall = round(0.6 × 最高分 + 0.4 × 前五高平均)
等級：0–39 low、40–69 medium、70–100 high
轉折點：第一則 stage=action 的對方訊息 → 否則第一則 risk ≥ 70 → 否則 NULL
```
權重是初始值；評估（evaluation）階段檢查是否合理，若調整則記錄在作品說明。

**評估後檢查（2026-10-12，8 段示範資料、人工標註）：維持初始權重不調整。**

| 對話 | 人工標註代入公式 | 規則比對 |
|---|---|---|
| 01 假投資 | 72 high | 75 high |
| 02 假交友 | 74 high | 62 medium |
| 03 假購物 | 63 medium | 61 medium |
| 04 假冒親友 | 68 medium | 23 low |
| 05 假冒公務員 | 60 medium | 39 low |
| 06 假求職 | 62 medium | 53 medium |
| 07 正常 | 0 low | 4 low |
| 08 正常 | 0 low | 49 medium |

- 觀察：以人工標註代入時，詐騙 60–74、正常 0，公式能區分兩者；但 6 段詐騙中有 4 段落在 medium，high 門檻 70 偏高。
- 規則比對的誤差主要來自關鍵詞偵測（04、05 漏判，08 因「點這個連結」誤判），不是權重造成。
- 不調整的理由：樣本只有 8 段，若以同一批資料挑門檻（例如改為 60）會過度擬合，評估數字也不再客觀。改為記錄為已知限制，待有獨立的驗證資料再校準。
- 另見：人工標註的轉折點常早於第一則「要求行動」（02：13 vs 20；06：14 vs 19），人工認定的轉折是「開始引導」，系統定義是「開口要求」。

### 安全

- 密碼 scrypt（Werkzeug）；Session Cookie `HttpOnly`、`SameSite=Lax`，登入成功後 `session.clear()` 再寫入，避免 Session fixation。
- CSRF：自寫 token（Session 存一份，每個 POST 表單隱藏欄位比對），不另加套件。
- 存取控制集中在一個 `load_case_or_404(case_id)` 輔助函式，案例頁、時間軸 API、回饋、刪除共用。
- 分析次數限制：以 `audit_logs` 中該使用者近一小時 `case_analyze` 筆數計算，不需另建表。
- `MAX_CONTENT_LENGTH = 1 MB`；超過時由 413 錯誤頁處理。

### 前端

- Jinja 樣板輸出所有資料；`timeline.js` 透過 `/api/cases/<id>/timeline` 取得 JSON 繪製 SVG。
- 標籤標亮：在前端以 `textContent` 切分訊息文字並包 `<mark>`，不使用 `innerHTML` 插入訊息內容。
- 手法統計橫條圖用純 HTML／CSS 寬度表示即可。

## Risks / Trade-offs

- [LINE 匯出格式隨版本改變] → 開發第一天先用自己手機匯出一段無敏感內容的對話確認格式；解析器對不符合的行當成接續列，不會中斷。
- [去識別化漏遮（第三人姓名、「零九一二」等暗語化數字）] → 預覽頁手動補遮＋確認勾選；在作品說明列為已知限制。
- [規則誤遮（例如 10 位數訂單編號被當成帳號）] → 偏向多遮；遮罩數量在預覽頁可見。
- [語言模型誤判或輸出不合法] → 程式驗證 evidence 與代碼，不合法即丟棄；整體失敗改用規則並在結果頁標示「準確度較低」。
- [分析在請求內同步執行，長對話可能耗時] → 訊息上限 2,000 則、切段處理；三天時程內不做背景工作佇列。
- [API 費用失控] → 每位使用者每小時 20 次分析上限。
- [評估樣本小（8 段自編資料）] → 結論只寫「初步測試」。

## Migration Plan

全新系統，無資料遷移。部署步驟：建立 venv → `pip install -r requirements.txt` → 設定 `SECRET_KEY`、`ANTHROPIC_API_KEY` → `python seed.py`（建表、查找表、管理員、示範案例）→ `flask run`。回復方式：刪除 `instance/scam.db` 後重新 seed。

## Implementation Notes（實作時補記）

- **兩步上傳**：要先解析才知道有哪些發話者，所以上傳分兩步。第一步解析後顯示「哪個名字是我」頁面，原文放在該頁表單的隱藏欄位送回瀏覽器（使用者自己的資料，伺服器不保存）；第二步帶著原文與選定的名字重新解析、去識別化，才建立暫存檔。暫存檔因此只含遮罩後文字。
- **多段摘要合併**：任一段判斷為詐騙即視為詐騙；`scam_type` 與 `summary` 取最後一個判斷為詐騙的段落，都不是則取最後一段。
- **非文字訊息與「我」的訊息**：階段照記，但 `requests_action` 一律為否、不標手法（非文字訊息階段固定 none）。
- **伺服器端備援的輸出**：回應中若有 `fallback` 區塊，只採用最後一個 `fallback` 區塊之後的文字。
- **新增檔案**：`taxonomy.py`（手法／階段／類型定義，seed、analyzer、樣板共用）、`requirements-dev.txt`（pytest）、`pytest.ini`。
- **示範案例管理**：後台案例表可「設為示範／取消示範」（`POST /admin/cases/<id>/demo`，僅管理員）。
- **管理員初始帳密**：`seed.py` 從 `ADMIN_USERNAME`／`ADMIN_PASSWORD` 讀取，未設定密碼時互動詢問。
