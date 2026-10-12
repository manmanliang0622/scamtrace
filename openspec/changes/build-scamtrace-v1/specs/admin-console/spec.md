# Spec Delta

## Purpose

提供管理員全站統計儀表板與操作日誌查詢，用來觀察常見話術組合、分析品質與系統使用狀況。

## ADDED Requirements

### Requirement: 統計儀表板
管理員 SHALL 能在 `/admin` 看到：案例總數與高風險比例、各手法出現頻率、最常一起出現的手法組合前 10 名、詐騙類型分布、轉折點平均出現在第幾則、回饋正確率（整體與各手法）、語言模型與規則比對各自的分析次數。統計 MUST NOT 顯示任何對話內容。

#### Scenario: 高風險比例
- **WHEN** 全站共 20 個已分析案例，其中 6 個等級為 high
- **THEN** 儀表板顯示案例數 20、高風險比例 30%

#### Scenario: 轉折點平均
- **WHEN** 有轉折點的案例轉折點分別為第 10、20、30 則
- **THEN** 儀表板顯示轉折點平均出現在第 20 則（沒有轉折點的案例不列入）

### Requirement: 手法組合統計
系統 SHALL 計算同一則訊息中同時出現的兩個手法組合次數，列出前 10 名。

#### Scenario: 組合計數
- **WHEN** 有 5 則訊息同時標註 authority 與 urgency_threat，3 則同時標註 liking 與 unity
- **THEN** 組合排行第一為「權威＋威脅恐嚇（5）」，其次「喜好＋團結（3）」

### Requirement: 操作日誌查詢
管理員 SHALL 能在 `/admin/audit` 以表格查看操作日誌（時間、使用者、事件、對象、IP、細節），依時間由新到舊排序，可依事件類型篩選，每頁 50 筆。

#### Scenario: 篩選登入失敗
- **WHEN** 管理員選擇事件類型 `login_failed`
- **THEN** 只列出 `login_failed` 事件

#### Scenario: 分頁
- **WHEN** 日誌共 120 筆，管理員開啟第 3 頁
- **THEN** 顯示第 101–120 筆

### Requirement: 後台存取限制
儀表板與操作日誌 MUST 只允許 `admin` 角色存取。

#### Scenario: 一般使用者存取日誌
- **WHEN** 角色為 `user` 的使用者開啟 `/admin/audit`
- **THEN** 系統回 403
