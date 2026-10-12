# Spec Delta

## Purpose

依 Cialdini 影響力原則與詐騙階段，對去識別化後的對話逐則標註說服手法、依據字句與階段，並判斷整段對話最可能的詐騙類型；語言模型不可用時以關鍵詞規則備援。

## ADDED Requirements

### Requirement: 說服手法分類
系統 SHALL 使用下列 8 個手法代碼：Cialdini 七項原則 reciprocity（互惠）、commitment（承諾一致）、social_proof（社會認同）、liking（喜好）、authority（權威）、scarcity（稀少性）、unity（團結），以及非 Cialdini 的 urgency_threat（威脅恐嚇）。每個手法 SHALL 有中文名稱、英文原名、定義與顯示顏色。

#### Scenario: 權威手法
- **WHEN** 對方訊息為「我是地檢署的檢察官，你的帳戶涉及洗錢」
- **THEN** 該則可標註 authority（依據「我是地檢署的檢察官」）與 urgency_threat（依據「你的帳戶涉及洗錢」）

#### Scenario: 不在清單內的代碼
- **WHEN** 分析結果出現不在上述 8 個代碼中的手法
- **THEN** 該筆標註被丟棄

### Requirement: 詐騙階段分類
每則訊息 SHALL 被標記一個階段：contact（接觸）、rapport（建立關係）、setup（鋪陳）、action（要求行動）、pressure（施壓）或 none（一般內容），並標記是否要求匯款、提供資料、點連結、下載或加入群組（requests_action）。

#### Scenario: 要求行動
- **WHEN** 對方訊息為「今天先入金 3 萬，名額只剩今天」
- **THEN** 該則階段為 action，requests_action 為真

### Requirement: 詐騙類型判斷
系統 SHALL 判斷整段對話最可能的詐騙類型：investment（假投資）、romance（感情詐騙）、shopping（網購解除分期／假買家）、impersonation_family（假冒親友）、impersonation_official（假冒公務員）、job（求職打工）、phishing（釣魚連結／盜帳號）、other（其他）；判斷為非詐騙時類型為空，並附一段判斷依據摘要。

#### Scenario: 正常對話
- **WHEN** 分析一段朋友約吃飯的對話
- **THEN** 詐騙類型為空，摘要說明未見要求行動

### Requirement: 只標註對方訊息
手法 MUST 只標註在對方的文字訊息上；「我」的訊息與非文字訊息只記錄階段，不得有手法標註。

#### Scenario: 我的訊息被標了手法
- **WHEN** 模型輸出對「我」的訊息標註 liking
- **THEN** 該筆標註被丟棄，該則訊息仍保留階段

### Requirement: 依據字句驗證
每筆手法標註 MUST 附依據字句與 0–1 的信心值；依據字句 MUST 是該則遮罩後訊息的子字串，否則該筆標註被丟棄。系統 SHALL 記錄每次分析丟棄的標註數量（不記錄內容）。

#### Scenario: 依據字句不在原訊息中
- **WHEN** 模型對第 5 則輸出依據「限時優惠」，但第 5 則內容不含這四個字
- **THEN** 該筆標註被丟棄，丟棄數量加 1

#### Scenario: 序號不存在
- **WHEN** 模型輸出序號 999，但案例只有 40 則訊息
- **THEN** 該筆結果被丟棄

### Requirement: 語言模型分析
系統 SHALL 優先以語言模型分析，只送出遮罩後訊息（每行含序號、時間、發話者代號、內容，非文字訊息以標記保留位置），並要求以固定結構輸出。案例 SHALL 記錄分析方式為 llm 與模型名稱。

#### Scenario: 模型分析成功
- **WHEN** 已設定 API 憑證且模型回傳合法結果
- **THEN** 案例的分析方式為 llm、模型名稱為 claude-opus-5-5，各訊息有階段與手法標註

### Requirement: 讚美推薦不單獨構成詐騙
整體判斷 MUST 以是否走到「要求行動」為主要依據；只有讚美、推薦、閒聊的對話 MUST NOT 僅因此被判斷為詐騙。

#### Scenario: 朋友間的讚美與推薦
- **WHEN** 分析同學互相稱讚並推薦一家餐廳、沒有任何要求行動的對話
- **THEN** 系統不判斷為詐騙

### Requirement: 長對話切段
超過 150 則的對話 SHALL 以每段 150 則、前後重疊 10 則切段分析；重疊部分 MUST 以後段結果為準，最後合併為一份完整結果。

#### Scenario: 300 則對話
- **WHEN** 分析一段 300 則的對話
- **THEN** 系統分段送出分析，每則訊息最終只有一組結果，第 141–150 則採用第二段的結果

### Requirement: 規則比對備援
在未設定 API 憑證、網路錯誤、模型拒答或輸出驗證整體失敗時，系統 SHALL 改用每個手法與階段的關鍵詞表比對；命中的關鍵詞即為依據字句，信心值固定 0.5。案例 SHALL 記錄分析方式為 rule，結果頁 MUST 顯示「本次使用規則比對，準確度較低」。

#### Scenario: 未設定 API 憑證
- **WHEN** 系統未設定 API 憑證時分析一段含「限時」「只剩」的對話
- **THEN** 系統以規則比對標註 scarcity、信心值 0.5，案例分析方式為 rule，結果頁顯示準確度較低提示

#### Scenario: 模型連線失敗
- **WHEN** 呼叫語言模型時發生網路錯誤
- **THEN** 系統自動改用規則比對完成分析，不回傳錯誤頁
