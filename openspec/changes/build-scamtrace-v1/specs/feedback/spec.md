# Spec Delta

## Purpose

讓案例擁有者回報標註結果的對錯並提出正確手法，累積資料用來計算整體與各手法的標註正確率。

## ADDED Requirements

### Requirement: 送出回饋
案例擁有者 SHALL 能對單則訊息的標註或對整體判斷送出回饋，內容包含是否正確、可選的修正手法與可選的說明；每次送出 MUST 寫入 `feedback` 日誌（不含說明文字）。

#### Scenario: 逐則回饋標註有誤
- **WHEN** 使用者在第 7 則旁按「標註有誤」，選擇正確手法為 liking 並送出
- **THEN** 系統儲存一筆針對第 7 則、is_correct 為否、修正手法為 liking 的回饋，並寫入 `feedback` 日誌

#### Scenario: 整體判斷回饋
- **WHEN** 使用者對整體判斷回饋「正確」
- **THEN** 系統儲存一筆不指定訊息、is_correct 為是的回饋

### Requirement: 回饋輸入限制
說明文字 MUST 不超過 200 字；修正手法 MUST 是既有手法代碼之一；指定的訊息 MUST 屬於該案例。

#### Scenario: 說明超過 200 字
- **WHEN** 使用者送出 201 字的說明
- **THEN** 系統拒絕並提示字數上限

#### Scenario: 訊息不屬於該案例
- **WHEN** 回饋請求指定的訊息屬於另一個案例
- **THEN** 系統回 400 且不儲存

### Requirement: 回饋權限
只有案例擁有者 SHALL 能送出回饋；訪客瀏覽示範案例與他人存取時 MUST 無法送出。

#### Scenario: 他人送出回饋
- **WHEN** 非擁有者對案例送出回饋請求
- **THEN** 系統回 404 且不儲存

### Requirement: 正確率計算
系統 SHALL 以回饋計算標註正確率：整體正確率為 is_correct 為是的回饋數除以回饋總數；各手法正確率以該則訊息被標註的手法分組計算。

#### Scenario: 整體正確率
- **WHEN** 共有 10 筆回饋，其中 8 筆為正確
- **THEN** 整體正確率為 80%
