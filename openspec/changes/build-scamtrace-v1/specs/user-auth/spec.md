# Spec Delta

## Purpose

管理使用者帳號的註冊、登入、登出與角色權限，並以密碼規則、登入失敗鎖定、安全 Session 與 CSRF 防護保護帳號。

## ADDED Requirements

### Requirement: 註冊帳號
系統 SHALL 允許訪客以帳號與密碼註冊為 `user` 角色。帳號 MUST 為 4–30 字元的英文、數字或底線且不可重複；密碼 MUST 至少 8 碼且同時包含英文字母與數字。註冊成功時 SHALL 寫入 `register` 日誌。

#### Scenario: 註冊成功
- **WHEN** 訪客以帳號 `alice_01`、密碼 `abc12345` 送出註冊
- **THEN** 系統建立角色為 `user` 的帳號、寫入 `register` 日誌，並導向登入或登入後首頁

#### Scenario: 帳號格式不符
- **WHEN** 訪客以帳號 `ab`（少於 4 字元）或含空白、中文的帳號送出註冊
- **THEN** 系統拒絕註冊並顯示帳號格式說明

#### Scenario: 密碼強度不足
- **WHEN** 訪客以密碼 `12345678`（無英文字母）或 `abc123`（少於 8 碼）送出註冊
- **THEN** 系統拒絕註冊並顯示密碼規則

#### Scenario: 帳號重複
- **WHEN** 訪客以已存在的帳號送出註冊
- **THEN** 系統拒絕註冊並提示帳號已被使用

### Requirement: 密碼雜湊儲存
系統 MUST 以 scrypt 等慢速加鹽雜湊儲存密碼，資料庫與日誌中 MUST NOT 出現明碼密碼。

#### Scenario: 資料庫不含明碼
- **WHEN** 使用者以密碼 `abc12345` 註冊後檢視 users 資料表
- **THEN** password_hash 欄位為雜湊字串，任何欄位與日誌都不含 `abc12345`

### Requirement: 登入與登出
系統 SHALL 驗證帳號密碼後建立登入狀態並寫入 `login_success` 日誌；登出 MUST 以 POST 請求進行，清除登入狀態並寫入 `logout` 日誌。

#### Scenario: 登入成功
- **WHEN** 使用者輸入正確帳號密碼
- **THEN** 系統建立登入狀態、將該帳號連續失敗次數歸零、寫入 `login_success` 日誌並導向我的案例

#### Scenario: 登出
- **WHEN** 已登入使用者送出登出 POST 請求
- **THEN** 系統清除 Session、寫入 `logout` 日誌並導向首頁

### Requirement: 登入錯誤訊息不透露原因
登入失敗時，系統 MUST 對「帳號不存在」與「密碼錯誤」顯示相同的錯誤訊息，並寫入 `login_failed` 日誌。

#### Scenario: 帳號不存在與密碼錯誤顯示相同訊息
- **WHEN** 使用者分別以不存在的帳號、以及存在帳號搭配錯誤密碼登入
- **THEN** 兩者顯示完全相同的錯誤訊息，且都寫入 `login_failed` 日誌

### Requirement: 登入失敗鎖定
同一帳號連續登入失敗 5 次時，系統 SHALL 鎖定該帳號 15 分鐘並寫入 `account_locked` 日誌；鎖定期間即使密碼正確也 MUST 拒絕登入。

#### Scenario: 第五次失敗後鎖定
- **WHEN** 使用者對同一帳號連續輸入錯誤密碼 5 次
- **THEN** 系統將帳號鎖定 15 分鐘並寫入 `account_locked` 日誌

#### Scenario: 鎖定期間拒絕正確密碼
- **WHEN** 帳號鎖定期間使用者輸入正確密碼
- **THEN** 系統拒絕登入

#### Scenario: 鎖定到期後可登入
- **WHEN** 鎖定時間超過 15 分鐘後使用者輸入正確密碼
- **THEN** 系統允許登入並將失敗次數歸零

### Requirement: Session 安全
Session Cookie MUST 設定 `HttpOnly` 與 `SameSite=Lax`，在 HTTPS 部署時 MUST 加上 `Secure`。登入成功時系統 SHALL 重新產生 Session，以防 Session 固定攻擊。`SECRET_KEY` MUST 從環境變數讀取，不得寫在程式碼中。

#### Scenario: Cookie 屬性
- **WHEN** 使用者登入後檢查回應的 Set-Cookie 標頭
- **THEN** Session Cookie 帶有 `HttpOnly` 與 `SameSite=Lax`

#### Scenario: 登入後重新產生 Session
- **WHEN** 使用者登入前已有 Session，接著登入成功
- **THEN** 登入前 Session 中的資料被清除，登入狀態寫入新的 Session

### Requirement: CSRF 防護
所有改變狀態的 POST 請求 MUST 附帶 CSRF token，伺服器 SHALL 比對 Session 中的值，不符合時拒絕請求並回 400。

#### Scenario: 缺少或錯誤的 CSRF token
- **WHEN** 有人送出不含 CSRF token 或 token 不符的 POST 請求（例如刪除案例）
- **THEN** 系統回 400 錯誤頁，且不執行該操作

### Requirement: 角色權限
系統 SHALL 依角色限制功能：訪客只能看首頁與示範案例；需要登入的頁面在未登入時 MUST 導向登入頁；`/admin` 開頭的頁面僅限 `admin`，其他角色存取 MUST 回 403。

#### Scenario: 未登入存取需登入頁面
- **WHEN** 訪客存取「我的案例」或上傳頁
- **THEN** 系統導向登入頁

#### Scenario: 一般使用者存取後台
- **WHEN** 角色為 `user` 的使用者存取 `/admin`
- **THEN** 系統回 403 錯誤頁
