# 詐騙對話話術分析系統　系統規格書

版本：v1.0（2026-10-09）
作者：梁曼璇
暫定名稱：詐騙對話話術分析系統（英文代號 ScamTrace）

> 本檔為原始規格書，保留作為作品說明來源。開發時以 `openspec/` 內的規格為準（change：`build-scamtrace-v1`）。

---

## 1. 系統目標與範圍

### 1.1 要解決的問題
詐騙多半不是一則訊息就完成，而是經過數天、數十則訊息，從聊天、建立信任，逐步轉到要求匯款或提供資料。常見的防詐工具多以查證「單則訊息、網址、電話號碼」為主，較難看出整段對話是在哪裡開始轉向。此外，把完整聊天紀錄上傳到第三方網站，本身就有個資外洩的風險。

### 1.2 系統做什麼
使用者上傳 LINE 匯出的聊天紀錄，系統：
1. **在本機先去識別化**：電話、帳號、身分證字號等個資在送出分析前就換成代號，原文不存進資料庫、不送出本機。
2. **逐則標註說服手法**：依 Cialdini 的七項影響力原則，標出每則訊息使用的手法與依據字句。
3. **判斷詐騙階段與類型**：標出每則訊息屬於哪個階段（接觸、建立關係、鋪陳、要求行動、施壓），並判斷整段對話最可能的詐騙類型。
4. **畫出風險時間軸**：顯示風險隨對話的變化，並標出「轉折點」（開始要求金錢或資料的那則訊息）。
5. **累積案例統計**：後台統計常見話術組合，並記錄使用者對標註結果的回饋，用來計算標註正確率。

### 1.3 不做什麼（範圍外）
- 不即時攔截訊息，也不串接 LINE 官方 API（只處理使用者自行匯出的檔案）。
- 不查詢電話或網址黑名單（這是現有工具已經在做的事）。
- 不提供法律判定；結果頁一律提示「若有疑慮請撥打 165 反詐騙專線」。

### 1.4 與現有工具的差異（作品頁寫法）
| 項目 | 常見防詐工具 | 本系統 |
|---|---|---|
| 分析單位 | 單則訊息、網址、電話 | 整段對話 |
| 輸出 | 是否為詐騙、風險分數 | 每則訊息的話術標註、詐騙階段、轉折點 |
| 隱私處理 | 原文上傳 | 先在本機去識別化，資料庫只存遮罩後文字 |
| 理論依據 | 黑名單、關鍵字 | Cialdini 影響力原則 |

> 寫作品說明時用「常見工具多以單則訊息查證為主」，不要寫「市面上沒有」。

---

## 2. 使用者角色

| 角色 | 能做的事 |
|---|---|
| 訪客（未登入） | 看首頁、看示範案例的分析結果 |
| 一般使用者 `user` | 註冊、登入；上傳對話、確認去識別化結果、送出分析；查看與刪除自己的案例；對標註結果回饋對錯 |
| 管理員 `admin` | 一般使用者的所有功能；查看全站統計儀表板；查看操作日誌；管理示範案例 |

---

## 3. 技術選型

| 層級 | 技術 | 說明 |
|---|---|---|
| 程式語言 | Python 3.12 以上（本機為 3.14） | |
| 後端框架 | Flask 3.x | 路由、Session、樣板 |
| 樣板 | Jinja2（Flask 內建） | 預設自動跳脫 HTML，防 XSS |
| 資料庫 | SQLite 3 | 單一檔案，不需架伺服器；之後可換 MySQL |
| 密碼雜湊 | Werkzeug `generate_password_hash`（scrypt） | Flask 相依套件內建 |
| 語言模型 | Anthropic Python SDK，模型 `claude-opus-5-5` | 只接收去識別化後的文字 |
| 前端 | HTML＋CSS＋原生 JavaScript | 不使用前端框架；時間軸以 SVG 繪製，不依賴外部圖表庫 |
| 套件管理 | `venv`＋`requirements.txt` | |

`requirements.txt`：
```
flask>=3.0
anthropic
```

---

## 4. 系統架構

```
┌──────────────────────────── 使用者瀏覽器 ────────────────────────────┐
│  上傳頁 ─→ 去識別化預覽頁 ─→ 分析結果頁（時間軸＋訊息標註）            │
│  我的案例　／　後台儀表板　／　操作日誌                                │
└───────────────────────────────┬──────────────────────────────────────┘
                                │ HTTP（表單 POST＋少量 JSON API）
┌───────────────────────────────▼──────────────────────────────────────┐
│ Flask 應用程式 app.py                                                 │
│  ├─ auth.py      登入、註冊、權限檢查、CSRF、帳號鎖定、操作日誌        │
│  ├─ parser.py    解析 LINE 匯出檔 → 訊息清單                          │
│  ├─ deidentify.py 個資偵測與遮罩（在本機執行）                         │
│  ├─ analyzer.py  話術標註：語言模型為主，規則比對為備援                │
│  ├─ risk.py      每則風險分數、整體風險、轉折點                        │
│  └─ stats.py     後台統計查詢                                         │
└───────────┬───────────────────────────────────────┬──────────────────┘
            │ SQL（參數化查詢）                       │ HTTPS（只送遮罩後文字）
┌───────────▼────────────┐                 ┌────────▼──────────────────┐
│ SQLite  instance/scam.db│                 │ Anthropic API              │
│ 只存遮罩後文字與分析結果 │                 │ claude-opus-5-5           │
└────────────────────────┘                 └───────────────────────────┘
```

**設計重點**：原文只存在於「上傳 → 預覽」這一次請求的記憶體與 Session 暫存中；確認送出後，原文與「代號 ↔ 原值」對照表立即丟棄，資料庫和語言模型都只看得到遮罩後的文字。

---

## 5. 處理流程

```
① 上傳 .txt（或貼上文字）＋選擇「哪個名字是我」
② parser：切出每則訊息（時間、發話者、內容）
③ deidentify：偵測個資 → 換成代號；發話者名字換成「我」「對方A」「對方B」
④ 預覽頁：使用者看到遮罩後全文與各類個資數量，可手動補遮（例如文中出現的人名）
⑤ 使用者勾選「我確認以上內容已去識別化」→ 送出
⑥ 寫入 cases、messages（只存遮罩後文字）
⑦ analyzer：整段對話送語言模型 → 每則訊息的話術、階段、依據字句；失敗則改用規則
⑧ risk：計算每則風險、整體風險、轉折點
⑨ 寫入分析結果 → 導向結果頁
```

Session 暫存：步驟 ④ 前的遮罩後訊息存在伺服器端暫存檔 `instance/pending/<隨機 token>.json`，30 分鐘後或送出後刪除。Session 只放 token，不放內容。

---

## 6. 資料庫設計

### 6.1 ER 關係
```
users 1 ── N cases 1 ── N messages N ── N tactics   （透過 message_tactics）
                │ 1                │
                │ N                │ 0..1
          case_pii_stats        feedback N ── 1 users
users 1 ── N audit_logs
scam_types 1 ── N cases
```

### 6.2 資料表

**users　使用者**
| 欄位 | 型別 | 限制 | 說明 |
|---|---|---|---|
| id | INTEGER | PK, AUTOINCREMENT | |
| username | TEXT | NOT NULL, UNIQUE | 4–30 字元，英數與底線 |
| password_hash | TEXT | NOT NULL | scrypt 雜湊，不存明碼 |
| role | TEXT | NOT NULL, CHECK IN ('user','admin') | |
| failed_logins | INTEGER | NOT NULL DEFAULT 0 | 連續失敗次數 |
| locked_until | TEXT | NULL | 鎖定到期時間（ISO 8601） |
| created_at | TEXT | NOT NULL DEFAULT now | |

**scam_types　詐騙類型（查找表）**
| 欄位 | 型別 | 限制 | 說明 |
|---|---|---|---|
| id | INTEGER | PK | |
| code | TEXT | UNIQUE | 見第 8.3 節 |
| name | TEXT | NOT NULL | 中文名稱 |
| description | TEXT | | |

**tactics　說服手法（查找表）**
| 欄位 | 型別 | 限制 | 說明 |
|---|---|---|---|
| id | INTEGER | PK | |
| code | TEXT | UNIQUE | 見第 8.1 節 |
| name | TEXT | NOT NULL | 中文名稱 |
| name_en | TEXT | NOT NULL | Cialdini 原文名稱 |
| description | TEXT | | 定義與詐騙中的典型說法 |
| color | TEXT | | 前端標籤顏色 |

**cases　分析案例**
| 欄位 | 型別 | 限制 | 說明 |
|---|---|---|---|
| id | INTEGER | PK | |
| user_id | INTEGER | FK → users.id, NOT NULL | 擁有者 |
| title | TEXT | NOT NULL | 使用者自訂，預設「對話分析 + 日期」 |
| source_type | TEXT | CHECK IN ('line_txt','paste') | |
| is_demo | INTEGER | NOT NULL DEFAULT 0 | 示範案例，訪客可看 |
| message_count | INTEGER | NOT NULL | |
| period_start / period_end | TEXT | | 對話起訖時間 |
| status | TEXT | CHECK IN ('pending','analyzed','failed') | |
| overall_risk | INTEGER | 0–100 | |
| risk_level | TEXT | CHECK IN ('low','medium','high') | |
| scam_type_id | INTEGER | FK → scam_types.id, NULL | 最可能的類型；正常對話為 NULL |
| summary | TEXT | | 一段話說明判斷依據（語言模型產生） |
| turning_point_seq | INTEGER | NULL | 轉折點訊息序號 |
| analyzed_by | TEXT | CHECK IN ('llm','rule') | |
| model_name | TEXT | | 例如 claude-opus-5-5 |
| created_at / analyzed_at | TEXT | | |

**messages　訊息（只存遮罩後文字）**
| 欄位 | 型別 | 限制 | 說明 |
|---|---|---|---|
| id | INTEGER | PK | |
| case_id | INTEGER | FK → cases.id ON DELETE CASCADE | |
| seq | INTEGER | NOT NULL | 對話中的順序，從 1 開始；(case_id, seq) UNIQUE |
| sent_at | TEXT | | 解析出的時間 |
| speaker | TEXT | NOT NULL | 「我」「對方A」「對方B」… |
| is_self | INTEGER | NOT NULL | |
| masked_text | TEXT | NOT NULL | 去識別化後內容 |
| msg_type | TEXT | CHECK IN ('text','sticker','image','file','call','system') | 貼圖、照片等非文字訊息 |
| stage | TEXT | CHECK IN ('contact','rapport','setup','action','pressure','none') | 見第 8.2 節 |
| risk_score | INTEGER | 0–100 | |
| requests_action | INTEGER | NOT NULL DEFAULT 0 | 是否要求匯款、提供資料、點連結、下載 |

**message_tactics　訊息與手法（多對多）**
| 欄位 | 型別 | 限制 | 說明 |
|---|---|---|---|
| message_id | INTEGER | FK → messages.id ON DELETE CASCADE | |
| tactic_id | INTEGER | FK → tactics.id | |
| evidence | TEXT | NOT NULL | 依據字句（必須是該訊息的子字串） |
| confidence | REAL | 0–1 | 規則比對固定為 0.5 |
| | | PK (message_id, tactic_id) | |

**case_pii_stats　去識別化統計（不存原值）**
| 欄位 | 型別 | 限制 | 說明 |
|---|---|---|---|
| case_id | INTEGER | FK → cases.id ON DELETE CASCADE | |
| pii_type | TEXT | | phone、bank_account、id_number… |
| count | INTEGER | | 遮罩了幾處 |
| | | PK (case_id, pii_type) | |

**feedback　使用者回饋**
| 欄位 | 型別 | 限制 | 說明 |
|---|---|---|---|
| id | INTEGER | PK | |
| case_id | INTEGER | FK → cases.id ON DELETE CASCADE | |
| message_id | INTEGER | FK → messages.id, NULL | NULL 代表針對整體判斷 |
| user_id | INTEGER | FK → users.id | |
| is_correct | INTEGER | NOT NULL | 標註正確與否 |
| corrected_tactic_id | INTEGER | FK → tactics.id, NULL | 使用者認為正確的手法 |
| comment | TEXT | | 200 字內 |
| created_at | TEXT | | |

**audit_logs　操作日誌**
| 欄位 | 型別 | 限制 | 說明 |
|---|---|---|---|
| id | INTEGER | PK | |
| user_id | INTEGER | FK → users.id, NULL | 登入失敗時可能為 NULL |
| action | TEXT | NOT NULL | 見第 10.3 節 |
| target | TEXT | | 例如 case:12 |
| detail | TEXT | | 不得包含對話內容或密碼 |
| ip | TEXT | | |
| created_at | TEXT | | |

索引：`messages(case_id, seq)`、`cases(user_id, created_at)`、`audit_logs(created_at)`、`message_tactics(tactic_id)`。

---

## 7. 解析與去識別化

### 7.1 LINE 匯出檔解析（parser.py）
LINE 匯出的 .txt 大致格式如下（手機版本與系統不同會略有差異，**開發前先用自己手機匯出一段無敏感內容的對話確認實際格式**）：
```
[LINE] 與王小明的聊天記錄
儲存日期：2026/10/09 14:00

2026/10/01（三）
14:05	王小明	你好，好久不見
14:06	王小明	[貼圖]
下午02:07	我的名字	"第一行
第二行"
```
解析規則：
| 行的型態 | 判斷方式 | 處理 |
|---|---|---|
| 標頭 | 以 `[LINE]` 或「儲存日期」開頭 | 略過 |
| 日期列 | `^\d{4}/\d{1,2}/\d{1,2}` | 更新目前日期 |
| 訊息列 | `時間 TAB 名字 TAB 內容`，時間接受 `HH:MM` 與 `上午/下午hh:mm` | 新增一則訊息 |
| 接續列 | 不符合以上 | 接到上一則訊息內容（多行訊息） |
| 特殊內容 | `[貼圖]`、`[照片]`、`[檔案]`、`☎` 開頭 | 設定 msg_type，不送分析 |

另支援「貼上文字」模式：每行 `名字：內容` 或 `名字: 內容`。

限制：檔案 ≤ 1 MB、僅 .txt、UTF-8（失敗時再試 UTF-16）、訊息數 ≤ 2,000 則；超過時只取最後 2,000 則並提示。

### 7.2 去識別化規則（deidentify.py）
依序比對（長的規則先比，避免帳號被當成電話）：
| 類型 `pii_type` | 規則 | 代號範例 |
|---|---|---|
| 信用卡號 `card` | 13–19 位數字（可含空白或 -），通過 Luhn 檢查碼 | `[卡號1]` |
| 身分證字號 `id_number` | `[A-Z][12]\d{8}` | `[身分證1]` |
| 居留證號 `arc_number` | `[A-Z][A-D89]\d{8}` | `[居留證1]` |
| Email `email` | 標準 email 格式 | `[信箱1]` |
| 網址 `url` | `https?://` 或 `www.` 開頭；**保留網域、遮掉路徑與參數** | `https://example.com/[路徑]` |
| 手機 `phone` | `09\d{2}-?\d{3}-?\d{3}`、`+886 9…` | `[電話1]` |
| 市話 `phone` | `0\d{1,2}-?\d{6,8}` | `[電話2]` |
| 銀行帳號 `bank_account` | 10–16 位連續數字（未被前面規則吃掉者） | `[帳號1]` |
| LINE ID `line_id` | 「ID」「line id」「加我」後接英數字串 | `[LINEID1]` |
| 地址 `address` | `(.{2}[縣市])?.{1,3}[區鄉鎮市].{1,10}[路街道].{0,10}號` | `[地址1]` |
| 發話者名字 | 解析出的發話者名稱，以及它在內文中的出現 | `我`、`對方A` |

- **同一個原值在整段對話中使用同一個代號**（例如同一個帳號出現三次都是 `[帳號1]`），模型才看得出「同一個帳號反覆出現」。
- **金額不遮罩**（例如「先匯 3 萬」），因為金額是判斷詐騙的重要線索，且不屬於個人識別資料。
- **網域不遮罩**，因為可疑網域本身是判斷依據。
- 已知限制：文中出現的第三人姓名無法完全偵測，所以預覽頁提供「手動選取文字 → 遮罩」功能。

---

## 8. 話術分類規格

### 8.1 說服手法（Cialdini 七項影響力原則）
| code | 中文 | 英文 | 在詐騙對話中的典型說法 |
|---|---|---|---|
| reciprocity | 互惠 | Reciprocation | 先送小禮、先讓你小賺一筆、「我幫了你，你也幫我一下」 |
| commitment | 承諾一致 | Commitment and Consistency | 先要求小承諾再逐步加碼、「你上次都說好了」 |
| social_proof | 社會認同 | Social Proof | 「群組裡大家都賺了」、截圖別人的獲利 |
| liking | 喜好 | Liking | 大量讚美、裝熟、展示共同興趣、曖昧示好 |
| authority | 權威 | Authority | 自稱分析師、檢察官、銀行專員、出示證件照片 |
| scarcity | 稀少性 | Scarcity | 「名額只剩今天」「錯過就沒了」「限時優惠」 |
| unity | 團結 | Unity | 「我們是自己人」「同鄉」「家人才跟你說」 |

另設一個非 Cialdini 的標籤 `urgency_threat`（威脅恐嚇：帳戶將被凍結、涉及洗錢），因為假冒公務員類詐騙大量使用，且不完全等同稀少性。

### 8.2 詐騙階段
| code | 名稱 | 說明 |
|---|---|---|
| contact | 接觸 | 初次搭話、加好友、打錯人 |
| rapport | 建立關係 | 閒聊、分享生活、示好 |
| setup | 鋪陳 | 提到投資、包裹、帳戶問題等，但尚未要求行動 |
| action | 要求行動 | 要求匯款、提供驗證碼或帳號、點連結、下載 App、加入群組 |
| pressure | 施壓 | 催促、威脅、情緒勒索 |
| none | 無 | 一般內容 |

### 8.3 詐騙類型
`investment` 假投資、`romance` 感情詐騙、`shopping` 網購解除分期／假買家、`impersonation_family` 假冒親友、`impersonation_official` 假冒公務員、`job` 求職打工、`phishing` 釣魚連結／盜帳號、`other` 其他。

### 8.4 判斷原則（寫進提示詞）
- 只有對方的訊息才標註話術；「我」的訊息只記錄階段。
- 依據字句 `evidence` 必須原文出現在該則訊息中，程式會檢查，不符合就丟棄該筆標註。
- 一般朋友聊天也會出現讚美、推薦，**單獨出現不代表詐騙**；整體判斷要看是否走到「要求行動」。

---

## 9. 分析模組

### 9.1 語言模型分析（analyzer.py）
- 模型：`claude-opus-5-5`；`output_config.effort = "medium"`。
- 結構化輸出：用 `output_config.format` 的 JSON schema 限制格式，再用程式驗證每個欄位。
- 啟用伺服器端備援：`betas=["server-side-fallback-2026-07-01"]`、`fallbacks="default"`。
- 送出內容：遮罩後的訊息清單，格式 `#序號 [時間] 發話者：內容`；非文字訊息以 `[貼圖]` 等標記保留位置。
- 長對話切段：每段 150 則，前後重疊 10 則；重疊部分以後段結果為準。
- 輸出 schema：
```json
{
  "messages": [
    {"seq": 12, "stage": "action", "requests_action": true,
     "tactics": [{"code": "scarcity", "evidence": "名額只剩今天", "confidence": 0.9}]}
  ],
  "scam_type": "investment",
  "is_likely_scam": true,
  "summary": "對方先以分析師身分建立權威，第 12 則開始要求加入投資群組並催促入金。"
}
```
- 驗證：`seq` 必須存在、`code` 必須在查找表中、`evidence` 必須是該訊息子字串；不合法的標註丟棄並記錄數量。

### 9.2 規則比對（備援）
每個手法與階段各有一份關鍵詞表（例如 scarcity：限時、只剩、今天截止、最後機會）。沒有設定 API 憑證、網路錯誤、模型拒答或輸出驗證失敗時使用；`analyzed_by` 記為 `rule`，結果頁顯示「本次使用規則比對，準確度較低」。

### 9.3 風險分數（risk.py）
每則訊息：
```
risk = min(100, 階段分數 + 15 × 手法數 + 行動加分)
階段分數：contact 0／rapport 5／setup 15／pressure 30／action 40／none 0
行動加分：requests_action 為真時 +25
```
整體風險：`overall = round(0.6 × 最高分 + 0.4 × 前五高的平均)`
等級：0–39 低、40–69 中、70–100 高。
轉折點：第一則 `stage = action` 的對方訊息；若沒有，取第一則 risk ≥ 70 的訊息；都沒有則為空。

> 權重是設計時的初始值，第 13 節的評估會檢查是否合理，並記錄調整過程。

---

## 10. 資安規格

### 10.1 帳號與連線
- 密碼：至少 8 碼，需含英文與數字；以 scrypt 雜湊儲存。
- 登入失敗 5 次鎖定 15 分鐘；錯誤訊息不透露是帳號還是密碼錯誤。
- Session Cookie：`HttpOnly`、`SameSite=Lax`；部署到 HTTPS 時加上 `Secure`。登入後重新產生 Session。
- `SECRET_KEY` 與 API 憑證從環境變數讀取，不寫進程式碼、不進版本控制（`.gitignore` 排除 `instance/` 與 `.env`）。

### 10.2 存取控制與輸入處理
- 所有 POST 表單帶 CSRF token，伺服器比對 Session 中的值。
- 每個 `/cases/<id>` 請求都檢查 `cases.user_id == 目前使用者`（管理員與示範案例除外）；不符合時回 404 並寫入 `access_denied` 日誌，避免透露案例是否存在。
- 所有 SQL 使用 `?` 參數化查詢。
- 所有輸出經 Jinja 自動跳脫；訊息內容一律以文字呈現，不以 HTML 插入。
- 上傳限制：`MAX_CONTENT_LENGTH = 1 MB`，只接受 .txt，伺服器端重新檢查。
- 分析次數限制：每位使用者每小時 20 次，避免 API 費用失控。

### 10.3 資料保護與稽核
- 原文不寫入資料庫；暫存檔送出後立即刪除，未送出者 30 分鐘後由啟動時與每次上傳時的清理程序刪除。
- 使用者可刪除案例，以 `ON DELETE CASCADE` 一併刪除訊息、標註、回饋與統計。
- 日誌事件：`login_success`、`login_failed`、`account_locked`、`register`、`logout`、`case_upload`、`case_analyze`、`case_delete`、`feedback`、`access_denied`、`rate_limited`。日誌不得記錄對話內容或密碼。

---

## 11. 路由與 API 規格

| 方法 | 路徑 | 權限 | 說明 |
|---|---|---|---|
| GET | `/` | 公開 | 首頁：系統說明、示範案例入口 |
| GET/POST | `/register` | 公開 | 註冊 |
| GET/POST | `/login` | 公開 | 登入 |
| POST | `/logout` | 登入 | 登出 |
| GET | `/cases` | 登入 | 我的案例列表（標題、日期、風險等級、類型） |
| GET/POST | `/cases/new` | 登入 | 上傳頁；POST 後解析、去識別化、建立暫存，導向預覽 |
| GET | `/cases/preview/<token>` | 登入（限本人） | 去識別化預覽 |
| POST | `/cases/preview/<token>/mask` | 登入（限本人） | 手動補遮一段文字 |
| POST | `/cases/preview/<token>/confirm` | 登入（限本人） | 確認送出 → 寫入資料庫 → 分析 → 導向結果頁 |
| GET | `/cases/<id>` | 本人／管理員／示範案例公開 | 分析結果頁 |
| GET | `/api/cases/<id>/timeline` | 同上 | JSON：`[{seq, sent_at, speaker, risk, stage, tactics:[code]}]`，供前端畫時間軸 |
| POST | `/cases/<id>/feedback` | 本人 | 送出回饋 |
| POST | `/cases/<id>/delete` | 本人／管理員 | 刪除案例 |
| GET | `/demo` | 公開 | 示範案例列表 |
| GET | `/admin` | 管理員 | 統計儀表板 |
| GET | `/admin/audit` | 管理員 | 操作日誌（可依事件類型篩選，分頁 50 筆） |

錯誤頁：400、403、404、413（檔案過大）、429（超過分析次數）、500，皆用同一個錯誤樣板。

---

## 12. 前端頁面規格

共用：頂部導覽列（系統名稱、我的案例、上傳、後台〔管理員〕、登入／登出）；每頁底部提示「本系統僅供參考，若有疑慮請撥打 165 反詐騙專線」。版面最小寬度 360 px，手機可用。

| 頁面 | 內容 |
|---|---|
| 首頁 | 系統用途、三步驟說明（上傳 → 確認去識別化 → 看分析）、隱私說明、示範案例卡片 |
| 上傳頁 | 檔案上傳或貼上文字二擇一；LINE 匯出教學（展開說明）；解析後讓使用者選「哪個名字是我」 |
| 預覽頁 | 左：遮罩後全文（代號以灰底標示）；右：各類個資遮罩數量；選取文字後可按「遮罩」；底部勾選「我確認內容已去識別化」才能送出 |
| 結果頁・摘要區 | 風險等級徽章（低／中／高，配色加文字，不只靠顏色）、整體分數、詐騙類型、一段判斷摘要、分析方式（模型或規則） |
| 結果頁・時間軸 | SVG 折線圖：橫軸為訊息序號、縱軸為風險分數；背景依階段分色；轉折點以垂直線與標籤標示；滑鼠移上去顯示該則訊息摘要，點擊捲動到該則訊息 |
| 結果頁・對話區 | 聊天泡泡排版（我在右、對方在左）；每則下方顯示手法標籤；點標籤會在原文中標亮依據字句；每則旁有「標註有誤」按鈕 |
| 結果頁・手法統計 | 本案例各手法出現次數的橫條圖 |
| 我的案例 | 表格：標題、對話期間、訊息數、風險等級、類型、建立時間、刪除 |
| 後台儀表板 | 案例數與高風險比例；各手法出現頻率；最常一起出現的手法組合前 10 名；詐騙類型分布；轉折點平均出現在第幾則；回饋正確率（整體與各手法）；模型與規則的分析次數 |
| 操作日誌 | 表格＋事件類型篩選＋分頁 |

前端 JavaScript 只負責：時間軸繪製與互動、標籤點擊標亮、預覽頁選取遮罩、刪除前確認。資料一律由後端樣板或 `/api/cases/<id>/timeline` 提供。

---

## 13. 示範資料與評估

### 13.1 示範資料
- **不使用任何真實個人對話**。示範對話由開發者自行編寫，情節參考 165 全民防騙網公開的詐騙手法說明改寫；系統內標示「自編示範資料」。
- 至少 8 段：假投資、感情詐騙、網購解除分期、假冒親友借錢、假冒檢警、求職詐騙，加上 2 段正常對話（朋友約吃飯、同學討論作業），用來檢查會不會誤判。
- 每段 20–60 則訊息，含電話、帳號等假個資，用來測試去識別化。

### 13.2 評估方式
- 開發者先對示範資料逐則人工標註（手法、階段、轉折點），作為標準答案。
- 比較兩種分析方式（語言模型、規則比對）：
  - 整段判斷：是否為詐騙的正確率（含兩段正常對話是否被誤判）。
  - 手法標註：各手法的精確率與召回率。
  - 轉折點：與人工標註的轉折點相差幾則。
- 去識別化：統計示範資料中所有假個資的遮罩成功率。
- 評估結果整理成表放進作品說明。樣本很小，結論要寫成「初步測試」，不寫成一般化結論。

---

## 14. 專案目錄結構

```
詐騙對話分析系統/
├── app.py              Flask 進入點與路由
├── config.py           設定（從環境變數讀取）
├── db.py               連線、初始化、查詢工具
├── schema.sql          建表 SQL
├── seed.py             建立查找表、管理員帳號、示範案例
├── auth.py             登入、註冊、權限、CSRF、鎖定、日誌
├── parser.py           LINE 匯出檔解析
├── deidentify.py       個資偵測與遮罩
├── analyzer.py         語言模型分析＋規則備援
├── risk.py             風險分數與轉折點
├── stats.py            後台統計查詢
├── evaluate.py         第 13 節評估腳本
├── lexicon/            規則比對用的關鍵詞表（JSON）
├── demo_data/          自編示範對話（.txt）與人工標註（.json）
├── templates/          Jinja 樣板
├── static/             style.css、timeline.js、preview.js
├── tests/              parser、deidentify、risk 的單元測試
├── instance/           資料庫與暫存檔（不進版本控制）
├── requirements.txt
├── .gitignore
└── README.md           安裝、執行、設計說明
```

---

## 15. 開發排程（2026/10/9–10/11）

| 時間 | 工作 | 完成標準 |
|---|---|---|
| 10/9 | 資料庫、登入註冊、parser、deidentify、單元測試；用自己手機匯出一段對話確認格式 | 上傳後能看到正確的遮罩預覽 |
| 10/10 上午 | analyzer（模型＋規則）、risk、結果頁 | 示範案例能跑出完整結果頁 |
| 10/10 下午 | 時間軸 SVG、標籤標亮、回饋、我的案例 | 結果頁互動可用 |
| 10/11 上午 | 示範資料 8 段＋人工標註、evaluate.py、後台儀表板、操作日誌 | 有評估數字 |
| 10/11 下午 | 截圖、ER 圖、作品頁 1–2 頁放進「03 著作作品」 | 書審 PDF 重建完成 |

**時間不夠時依序砍掉**：手動補遮功能 → 後台組合統計 → 長對話切段（改為限制 150 則）→ 回饋功能。核心不能砍：去識別化、話術標註、時間軸。

---

## 16. 已知限制
- LINE 匯出格式會隨版本改變，解析器需以實際檔案測試。
- 去識別化以規則為主，文中人名、暗語化的帳號（例如「零九一二」）可能漏遮。
- 話術判斷依賴語言模型，可能誤判；系統定位為輔助理解，不作為判定依據。
- 示範資料為自編，評估樣本小，數字只能說明初步可行性。

---

## 17. 參考資料
- Cialdini, R. B. (2021). *Influence, new and expanded: The psychology of persuasion*. Harper Business.（第七項原則 Unity 為本版新增；出版社請以版權頁核對）
- 內政部警政署 165 全民防騙網：詐騙手法說明（示範資料情節參考來源，引用時附實際網址與擷取日期）。
