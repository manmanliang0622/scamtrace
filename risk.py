"""風險分數與轉折點（SPEC §9.3）。權重為設計初始值，評估後若調整需記錄。"""

STAGE_SCORES = {"contact": 0, "rapport": 5, "setup": 15, "pressure": 30, "action": 40, "none": 0}
TACTIC_WEIGHT = 15
ACTION_BONUS = 25
HIGH_RISK = 70


def message_risk(stage, tactic_count, requests_action):
    score = STAGE_SCORES.get(stage or "none", 0) + TACTIC_WEIGHT * tactic_count
    if requests_action:
        score += ACTION_BONUS
    return min(100, score)


def overall_risk(scores):
    if not scores:
        return 0
    ranked = sorted(scores, reverse=True)
    top5 = ranked[:5]
    return round(0.6 * ranked[0] + 0.4 * (sum(top5) / len(top5)))


def risk_level(overall):
    if overall >= 70:
        return "high"
    if overall >= 40:
        return "medium"
    return "low"


def turning_point(messages):
    """messages：依 seq 排序，含 seq、is_self、stage、risk。"""
    for m in messages:
        if not m["is_self"] and m["stage"] == "action":
            return m["seq"]
    for m in messages:
        if m["risk"] >= HIGH_RISK:
            return m["seq"]
    return None


def score_case(messages):
    """為每則訊息填入 risk，回傳 (overall, level, turning_point_seq)。

    messages 每筆需有 seq、is_self、stage、requests_action、tactics（清單）。
    """
    for m in messages:
        m["risk"] = message_risk(m["stage"], len(m["tactics"]), m["requests_action"])
    overall = overall_risk([m["risk"] for m in messages])
    return overall, risk_level(overall), turning_point(messages)
