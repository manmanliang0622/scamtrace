from risk import message_risk, overall_risk, risk_level, score_case, turning_point


def test_action_with_two_tactics():
    assert message_risk("action", 2, True) == 95


def test_capped_at_100():
    assert message_risk("action", 4, True) == 100


def test_none_stage():
    assert message_risk("none", 0, False) == 0


def test_stage_scores():
    assert [message_risk(s, 0, False) for s in ("contact", "rapport", "setup", "pressure", "action")] == [0, 5, 15, 30, 40]


def test_overall():
    assert overall_risk([95, 80, 60, 40, 25, 10, 0]) == 81


def test_overall_fewer_than_five():
    assert overall_risk([10, 20, 30]) == 26


def test_overall_empty():
    assert overall_risk([]) == 0


def test_level_boundaries():
    assert [risk_level(x) for x in (39, 40, 69, 70)] == ["low", "medium", "medium", "high"]


def m(seq, stage="none", risk=0, is_self=False):
    return {"seq": seq, "stage": stage, "risk": risk, "is_self": is_self}


def test_turning_point_first_action():
    msgs = [m(1), m(12, "pressure", 75), m(18, "action", 65)]
    assert turning_point(msgs) == 18


def test_turning_point_falls_back_to_high_risk():
    assert turning_point([m(1), m(9, "pressure", 70), m(10, "pressure", 90)]) == 9


def test_turning_point_ignores_self_action():
    assert turning_point([m(1, "action", 65, is_self=True), m(2)]) is None


def test_score_case():
    msgs = [
        {"seq": 1, "is_self": False, "stage": "rapport", "requests_action": False, "tactics": ["liking"]},
        {"seq": 2, "is_self": False, "stage": "action", "requests_action": True, "tactics": ["scarcity", "authority"]},
    ]
    overall, level, tp = score_case(msgs)
    assert [x["risk"] for x in msgs] == [20, 95]
    assert overall == round(0.6 * 95 + 0.4 * 57.5)
    assert level == "high" and tp == 2
