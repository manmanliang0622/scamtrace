# Spec Delta

## Purpose

把每則訊息的階段、手法與行動要求換算成可比較的風險分數，並得出整體風險、風險等級與對話開始轉向的轉折點。

## ADDED Requirements

### Requirement: 單則風險分數
每則訊息的風險 SHALL 為 `min(100, 階段分數 + 15 × 手法數 + 行動加分)`；階段分數為 contact 0、rapport 5、setup 15、pressure 30、action 40、none 0；requests_action 為真時行動加分為 25，否則為 0。

#### Scenario: 要求行動且有兩個手法
- **WHEN** 一則訊息階段為 action、有 scarcity 與 authority 兩個手法、requests_action 為真
- **THEN** 風險為 min(100, 40 + 30 + 25) = 95

#### Scenario: 上限 100
- **WHEN** 一則訊息階段為 action、有 4 個手法、requests_action 為真
- **THEN** 風險為 100

#### Scenario: 一般內容
- **WHEN** 一則訊息階段為 none、沒有手法
- **THEN** 風險為 0

### Requirement: 整體風險分數
整體風險 SHALL 為 `round(0.6 × 最高單則風險 + 0.4 × 前五高單則風險的平均)`；訊息不足五則時以全部訊息平均。

#### Scenario: 計算整體風險
- **WHEN** 單則風險前五高為 95、80、60、40、25
- **THEN** 整體風險為 round(0.6 × 95 + 0.4 × 60) = 81

#### Scenario: 不足五則
- **WHEN** 案例只有三則訊息，風險為 10、20、30
- **THEN** 整體風險為 round(0.6 × 30 + 0.4 × 20) = 26

### Requirement: 風險等級
風險等級 SHALL 依整體風險決定：0–39 為 low（低）、40–69 為 medium（中）、70–100 為 high（高）。

#### Scenario: 等級邊界
- **WHEN** 整體風險分別為 39、40、69、70
- **THEN** 等級分別為 low、medium、medium、high

### Requirement: 轉折點
轉折點 SHALL 為第一則階段為 action 的對方訊息；若沒有，取第一則風險 ≥ 70 的訊息；兩者皆無時轉折點為空。

#### Scenario: 有要求行動
- **WHEN** 對方第 18 則訊息是第一則 action 階段訊息，而第 12 則風險已達 75
- **THEN** 轉折點為第 18 則

#### Scenario: 沒有 action 但有高風險
- **WHEN** 沒有任何 action 階段的對方訊息，第 9 則是第一則風險 ≥ 70 的訊息
- **THEN** 轉折點為第 9 則

#### Scenario: 我的 action 訊息不算
- **WHEN** 只有「我」的訊息被標為 action，且沒有任何訊息風險 ≥ 70
- **THEN** 轉折點為空
