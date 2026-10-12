# Tasks

> 依 SPEC.md §15 排程分組。時間不夠時依序砍：①手動補遮 → ②後台組合統計 → ③長對話切段（改為限制 150 則）→ ④回饋功能。
> 核心不能砍：去識別化、話術標註、時間軸。

## 1. 專案骨架與資料庫（10/9）

- [x] 1.1 建立 venv、`requirements.txt`（flask>=3.0、anthropic）、`.gitignore`（instance/、.env、venv/），確認 `pip install -r requirements.txt` 成功
- [x] 1.2 建立 `config.py`（從環境變數讀 `SECRET_KEY`、`ANTHROPIC_API_KEY`，`MAX_CONTENT_LENGTH = 1 MB`、Cookie 屬性），確認未設定 `SECRET_KEY` 時啟動會明確報錯
- [x] 1.3 撰寫 `schema.sql`（9 張表、CHECK 限制、CASCADE、4 個索引）與 `db.py`（連線時開啟 `foreign_keys`），確認刪除 case 時 messages 連帶刪除
- [x] 1.4 撰寫 `seed.py`：tactics 8 筆、scam_types 8 筆、管理員帳號，確認重複執行不會重複建立資料

## 2. 帳號與安全基礎（10/9）

- [x] 2.1 `auth.py`：註冊（帳號格式、密碼強度、重複檢查）與 scrypt 雜湊，寫測試確認規則與資料庫不含明碼
- [x] 2.2 登入／登出、相同錯誤訊息、5 次失敗鎖 15 分鐘、登入後重新產生 Session，寫測試覆蓋鎖定與到期解鎖
- [x] 2.3 CSRF token 產生與驗證、`login_required`／`admin_required` 裝飾器，測試缺 token 回 400、user 存取 /admin 回 403
- [x] 2.4 操作日誌寫入函式（事件、對象、細節、IP），確認登入失敗日誌不含密碼
- [x] 2.5 共用樣板 `base.html`（導覽列、165 提示）與統一錯誤頁（400／403／404／413／429／500），手動觸發 404 與 413 確認樣式一致且無堆疊

## 3. 匯入與去識別化（10/9）

- [x] 3.1 用自己手機匯出一段無敏感內容的 LINE 對話，確認實際格式並存一份去識別化後的樣本到 `tests/fixtures/`
- [x] 3.2 `parser.py`：標頭、日期列、訊息列（24 小時制與上午/下午）、接續列、非文字訊息、貼上模式、UTF-8→UTF-16、2,000 則截取；`tests/test_parser.py` 覆蓋 chat-import 規格各情境並通過
- [x] 3.3 `deidentify.py`：依序套用各規則（含 Luhn、數字邊界）、同值同代號、網址保留網域、金額不遮、發話者匿名化、統計；`tests/test_deidentify.py` 覆蓋 deidentification 規格各情境並通過
- [x] 3.4 上傳頁（檔案／貼上二擇一、LINE 匯出教學、選擇自己的名字）與 `/cases/new` 路由，確認非 .txt 被拒
- [x] 3.5 暫存檔機制（`instance/pending/<token>.json`、擁有者檢查、30 分鐘清理於啟動與上傳時執行），確認暫存檔內找不到原始電話號碼
- [x] 3.6 預覽頁（灰底代號、遮罩數量、確認勾選）；完成標準：上傳範例檔後看到正確遮罩預覽
- [x] 3.7 手動補遮 `/cases/preview/<token>/mask`＋`preview.js`，確認全文同字串都被替換、統計更新（可砍，第 ① 順位）

## 4. 分析與風險（10/10 上午）

- [x] 4.1 `risk.py`：單則公式、整體公式、等級、轉折點；`tests/test_risk.py` 覆蓋 risk-scoring 規格所有數值情境並通過
- [x] 4.2 `lexicon/` 各手法與階段關鍵詞 JSON，及 analyzer 規則比對（confidence 0.5、`analyzed_by = rule`），用一段示範對話確認能標出 scarcity
- [x] 4.3 analyzer 語言模型呼叫：提示詞（分類定義、只標對方、evidence 逐字、讚美不單獨構成詐騙）、JSON schema、effort medium、server-side fallback；以離線方式驗證（不花費）：真正的 SDK 搭配假 HTTP 傳輸層，檢查送出的請求並以示範對話 01 的串流回應確認可解析（`tests/test_llm_offline.py`）。實際呼叫模型為選做，需設定 `ANTHROPIC_API_KEY`
- [x] 4.4 輸出驗證（seq、code、evidence 子字串、我的訊息不標手法）與丟棄計數；寫測試以假造的模型輸出確認不合法標註被丟棄
- [x] 4.5 失敗時自動改用規則（無憑證、網路錯誤、拒答、驗證失敗），測試在無 `ANTHROPIC_API_KEY` 時仍完成分析
- [x] 4.6 長對話切段 150 則重疊 10 則、後段優先合併；以 300 則假資料測試每則只有一組結果（可砍，第 ③ 順位：改為超過 150 則時只取最後 150 則並提示）
- [x] 4.7 `/cases/preview/<token>/confirm`：寫入 cases／messages／pii_stats → 刪暫存 → 分析 → 風險 → 寫結果 → 導向結果頁；每小時 20 次限制＋429＋`rate_limited` 日誌；`case_analyze` 日誌
- [x] 4.8 結果頁基本版（摘要區徽章文字＋顏色、分數、類型、摘要、分析方式、規則提示；聊天泡泡與手法標籤），完成標準：一段示範案例跑出完整結果頁

## 5. 結果頁互動與案例管理（10/10 下午）

- [x] 5.1 `load_case_or_404` 存取控制（擁有者／管理員／示範），測試他人與不存在案例都回相同 404 並寫 `access_denied` 日誌
- [x] 5.2 `/api/cases/<id>/timeline` JSON API，測試欄位與排序、無權限回 404
- [x] 5.3 `timeline.js` SVG 時間軸：折線、階段背景色、轉折點垂直線與標籤、hover 摘要、點擊捲動；在 360 px 寬度下檢查可用
- [x] 5.4 標籤點擊標亮依據字句（以 textContent 處理），確認含 `<script>` 的訊息只顯示為文字
- [x] 5.5 手法統計橫條圖，確認只列出現次數 > 0 的手法
- [x] 5.6 我的案例列表與刪除（擁有者／管理員、刪除前確認、CASCADE、`case_delete` 日誌），測試刪除後訊息與標註消失
- [x] 5.7 回饋功能：「標註有誤」按鈕、修正手法、200 字限制、訊息歸屬檢查、`feedback` 日誌，寫測試覆蓋 feedback 規格情境（可砍，第 ④ 順位）

## 6. 示範資料、評估與後台（10/11 上午）

- [x] 6.1 依 165 全民防騙網手法說明自編 8 段示範對話（6 類詐騙＋2 段正常），每段 20–60 則、含假個資，存於 `demo_data/*.txt`，記錄參考網址與擷取日期
- [x] 6.2 逐則人工標註（手法、階段、轉折點、是否詐騙）存於 `demo_data/*.json`，評估腳本載入時檢查完整性
- [x] 6.3 seed 匯入示範案例（`is_demo = 1`、標示「自編示範資料」）與 `/demo` 列表、首頁示範卡片，確認訪客可看但無回饋與刪除按鈕
- [x] 6.4 `evaluate.py`：模型 vs 規則的整段正確率、各手法精確率／召回率、轉折點誤差、去識別化成功率，輸出成表；確認無憑證時只跑規則並註明
- [x] 6.5 依評估結果檢查風險權重是否合理；若調整，記錄調整前後數值與理由於 design.md
- [x] 6.6 `stats.py` 與 `/admin` 儀表板：案例數、高風險比例、手法頻率、類型分布、轉折點平均、回饋正確率、模型／規則次數，以示範資料確認數字正確
- [x] 6.7 手法組合前 10 名統計（可砍，第 ② 順位）
- [x] 6.8 `/admin/audit` 操作日誌表格、事件篩選、每頁 50 筆分頁，確認 user 存取回 403

## 7. 整合驗收與作品頁（10/11 下午）

- [x] 7.1 以全新環境依 README 從安裝到執行走一遍（建 venv → 設環境變數 → seed → 啟動 → 上傳 → 預覽 → 分析 → 結果頁 → 刪除），全部單元測試通過
- [x] 7.2 撰寫 README.md（安裝、執行、設計說明、已知限制），確認指令照抄可執行
- [x] 7.3 截圖（首頁、預覽、結果頁時間軸、後台）與 ER 圖
- [x] 7.4 作品頁 1–2 頁：與常見工具的差異表（寫「常見工具多以單則訊息查證為主」）、評估表（標示「初步測試」與樣本數）、參考資料，放入「03 著作作品」並重建書審 PDF

## Workflow follow-up

- 全部任務完成後執行 `openspec archive build-scamtrace-v1`，將 delta specs 合併成 `openspec/specs/` 正式規格。
- 封存後以 `openspec validate --specs --strict` 確認正式規格無誤。
