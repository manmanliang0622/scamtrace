# Spec Delta

## Purpose

定義跨功能的安全防護與稽核要求，包括注入與 XSS 防護、上傳檢查、分析次數限制、操作日誌事件與內容限制，以及統一的錯誤頁。

## ADDED Requirements

### Requirement: 防止 SQL 注入
所有資料庫查詢 MUST 以參數化方式帶入使用者輸入，不得以字串拼接組成 SQL。

#### Scenario: 帳號欄位注入
- **WHEN** 使用者以帳號 `' OR '1'='1` 嘗試登入
- **THEN** 登入失敗，且不影響任何資料

### Requirement: 防止 XSS
所有輸出到頁面的資料 MUST 經 HTML 跳脫；前端插入訊息內容時 MUST 以純文字方式插入。

#### Scenario: 案例標題含 HTML
- **WHEN** 使用者將案例標題設為 `<img src=x onerror=alert(1)>`
- **THEN** 我的案例列表原樣顯示該文字，不執行程式

### Requirement: 上傳大小與類型檢查
請求內容 MUST 不超過 1 MB，超過時回 413 錯誤頁；檔案類型 MUST 在伺服器端重新檢查，不得只依賴前端限制。

#### Scenario: 檔案過大
- **WHEN** 使用者上傳 2 MB 的檔案
- **THEN** 系統回 413 錯誤頁並提示檔案過大

### Requirement: 分析次數限制
每位使用者每小時最多執行 20 次分析；超過時系統 SHALL 回 429 錯誤頁、不執行分析，並寫入 `rate_limited` 日誌。

#### Scenario: 第 21 次分析
- **WHEN** 使用者在一小時內第 21 次確認送出分析
- **THEN** 系統回 429 錯誤頁、不呼叫語言模型，並寫入 `rate_limited` 日誌

### Requirement: 操作日誌事件
系統 SHALL 記錄下列事件：`login_success`、`login_failed`、`account_locked`、`register`、`logout`、`case_upload`、`case_analyze`、`case_delete`、`feedback`、`access_denied`、`rate_limited`；每筆含使用者（可為空）、事件、對象、細節、IP 與時間。

#### Scenario: 分析完成記錄
- **WHEN** 使用者完成一次案例分析
- **THEN** 新增一筆 `case_analyze` 日誌，對象為 `case:<id>`，細節含分析方式

#### Scenario: 未知帳號登入失敗
- **WHEN** 有人以不存在的帳號登入失敗
- **THEN** 新增一筆使用者為空的 `login_failed` 日誌

### Requirement: 日誌不含敏感內容
操作日誌與應用程式紀錄 MUST NOT 包含對話內容、個資原值或密碼。

#### Scenario: 登入失敗不記密碼
- **WHEN** 使用者以錯誤密碼 `wrongpass1` 登入
- **THEN** 日誌中任何欄位都不含 `wrongpass1`

### Requirement: 機密設定
`SECRET_KEY` 與語言模型 API 憑證 MUST 從環境變數讀取；資料庫、暫存檔與 `.env` MUST 排除在版本控制之外。

#### Scenario: 原始碼不含憑證
- **WHEN** 檢查專案原始碼與版本控制追蹤的檔案
- **THEN** 找不到 API 憑證或 SECRET_KEY 的實際值，`instance/` 與 `.env` 不被追蹤

### Requirement: 統一錯誤頁
400、403、404、413、429、500 錯誤 SHALL 使用同一個錯誤頁面樣式，顯示錯誤代碼與易懂說明，且 MUST NOT 顯示程式堆疊或內部資訊。

#### Scenario: 伺服器錯誤
- **WHEN** 處理請求時發生未預期例外
- **THEN** 使用者看到 500 錯誤頁，頁面不含堆疊追蹤
