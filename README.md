# ScamTrace　詐騙對話話術分析系統

上傳 LINE 匯出的聊天紀錄，系統先在本機把電話、帳號等個資換成代號，再依 Cialdini 影響力原則逐則標註對方使用的說服手法、判斷詐騙階段與類型，畫出風險時間軸並標出「轉折點」（開始要求金錢或資料的那則訊息）。

> 本系統僅供參考，若有疑慮請撥打 165 反詐騙專線。

完整規格見 `openspec/changes/build-scamtrace-v1/`（OpenSpec），原始規格書見 `SPEC.md`。

## 安裝

需要 Python 3.12 以上。

```bash
python3 -m venv venv
source venv/bin/activate          # Windows：venv\Scripts\activate
pip install -r requirements.txt
pip install -r requirements-dev.txt   # 只有要跑測試時需要
```

## 設定

機密設定一律用環境變數，不寫進程式碼：

| 變數 | 必要 | 說明 |
|---|---|---|
| `SECRET_KEY` | 是 | Session 簽章用的隨機字串，例如 `python -c "import secrets; print(secrets.token_hex(32))"` 產生 |
| `ANTHROPIC_API_KEY` | 否 | 設定後使用語言模型（claude-opus-5-5）分析；未設定時自動改用規則比對 |
| `ADMIN_USERNAME`／`ADMIN_PASSWORD` | 否 | `seed.py` 建立的管理員帳密；未設定密碼時會互動詢問 |
| `SESSION_COOKIE_SECURE` | 否 | 部署到 HTTPS 時設為 `1` |

```bash
export SECRET_KEY="（上面產生的字串）"
export ANTHROPIC_API_KEY="（可省略）"
```

## 執行

```bash
python seed.py            # 建表、查找表、管理員帳號、示範案例（可重複執行）
flask --app app run       # 開啟 http://127.0.0.1:5000
```

測試：

```bash
python -m pytest
```

評估（SPEC §13）：

```bash
python evaluate.py              # 有 API 憑證時同時跑語言模型與規則比對
python evaluate.py --no-llm     # 只跑規則比對，不產生 API 費用
```

結果寫入 `evaluation_report.md`。

## 使用流程

1. 註冊、登入。
2. 「上傳」：選 LINE 匯出的 .txt 檔（1 MB 以內）或貼上文字，接著選出哪個名字是你。
3. 預覽頁檢查遮罩後全文；漏遮的人名可選取後按「遮罩選取文字」。勾選確認後送出。
4. 結果頁：風險等級與摘要、風險時間軸（點擊可跳到該則訊息）、逐則手法標籤（點標籤會標亮依據字句）、手法統計。可對標註回饋對錯。

## 設計說明

| 模組 | 職責 |
|---|---|
| `parser.py` | 解析 LINE 匯出檔與貼上文字 → 訊息清單 |
| `deidentify.py` | 個資偵測與遮罩；同一個原值整段使用同一個代號；金額與網域保留 |
| `analyzer.py` | 語言模型分析（結構化輸出＋程式驗證依據字句）；失敗時改用 `lexicon/` 關鍵詞規則 |
| `risk.py` | 單則風險、整體風險、風險等級、轉折點 |
| `auth.py` | 註冊、登入、鎖定、CSRF、權限、操作日誌 |
| `stats.py` | 後台統計 |
| `app.py` | 路由、預覽暫存、案例存取控制、寫入分析結果 |
| `evaluate.py` | 示範資料評估 |

隱私處理：原文只在上傳那一次請求中處理。去識別化後的訊息暫存在 `instance/pending/<隨機 token>.json`（30 分鐘失效，送出後立即刪除）；資料庫與語言模型都只看得到遮罩後文字，「代號 ↔ 原值」對照表不保存。

風險分數：

```
每則：min(100, 階段分數 + 15 × 手法數 + (要求行動 ? 25 : 0))
階段分數：接觸 0／建立關係 5／鋪陳 15／施壓 30／要求行動 40／一般 0
整體：round(0.6 × 最高分 + 0.4 × 前五高平均)；0–39 低、40–69 中、70–100 高
轉折點：第一則「要求行動」的對方訊息；沒有則取第一則風險 ≥ 70 的訊息
```

## 示範資料格式

`demo_data/<名稱>.txt` 為 LINE 匯出格式的自編對話，`demo_data/<名稱>.json` 為人工標註，欄位說明見 `evaluate.py` 開頭。示範對話一律自行編寫，不使用任何真實個人對話。

標註可以用試算表填：`python label_sheet.py export` 產生 `demo_data/labels/<名稱>.csv`，用 Numbers 或 Excel 填好「階段」「手法」「轉折點」欄並存成 CSV，再執行 `python label_sheet.py import` 寫回 JSON（有錯會列出並且不寫入）。

## 已知限制

- LINE 匯出格式會隨版本改變，解析器需以實際檔案測試。
- 去識別化以規則為主，文中第三人姓名、暗語化的數字（例如「零九一二」）可能漏遮，因此預覽頁提供手動補遮。
- 話術判斷依賴語言模型，可能誤判；系統定位為輔助理解，不作為判定依據。
- 示範資料為自編、樣本小，評估數字只能說明初步可行性。
- 以人工標註代入風險公式時，6 段詐騙中有 4 段落在中風險（60–69 分），高風險門檻 70 可能偏高；因樣本太少，暫不以同一批資料調整。

## 參考資料

- 165 全民防騙網（內政部警政署）：https://165.npa.gov.tw/ ，示範對話中 6 段詐騙情節依其公開的詐騙手法說明改寫（擷取日期 2026-10-09）
- 165 打詐儀錶板：https://165dashboard.tw/
