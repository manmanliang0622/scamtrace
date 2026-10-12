import json
from types import SimpleNamespace

import anthropic
import httpx2

from analyzer import analyze, analyze_rules, chunk_ranges, format_messages, validate_output


def msg(seq, text, is_self=False, msg_type="text", speaker=None):
    return {"seq": seq, "sent_at": "2026-10-01 10:00", "speaker": speaker or ("我" if is_self else "對方A"),
            "is_self": is_self, "text": text, "msg_type": msg_type}


CONVO = [
    msg(1, "你好，我是投資分析師王老師"),
    msg(2, "你好", is_self=True),
    msg(3, "[貼圖]", msg_type="sticker"),
    msg(4, "今天先入金 3 萬，名額只剩今天"),
]


class FakeStream:
    def __init__(self, final):
        self.final = final

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get_final_message(self):
        return self.final


class FakeClient:
    """模擬 client.beta.messages.stream，依序回傳預先準備的回應。"""

    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=self.stream))

    def stream(self, **kwargs):
        self.calls.append(kwargs)
        out = self.outputs.pop(0)
        if isinstance(out, Exception):
            raise out
        if isinstance(out, SimpleNamespace):
            return FakeStream(out)
        text = out if isinstance(out, str) else json.dumps(out, ensure_ascii=False)
        return FakeStream(SimpleNamespace(stop_reason="end_turn", stop_details=None,
                                          content=[SimpleNamespace(type="text", text=text)]))


def good_output(seqs=(1, 2, 3, 4)):
    items = {
        1: {"seq": 1, "stage": "contact", "requests_action": False,
            "tactics": [{"code": "authority", "evidence": "投資分析師", "confidence": 0.9}]},
        2: {"seq": 2, "stage": "contact", "requests_action": False, "tactics": []},
        3: {"seq": 3, "stage": "none", "requests_action": False, "tactics": []},
        4: {"seq": 4, "stage": "action", "requests_action": True,
            "tactics": [{"code": "scarcity", "evidence": "名額只剩今天", "confidence": 0.95}]},
    }
    return {"messages": [items[s] for s in seqs], "scam_type": "investment",
            "is_likely_scam": True, "summary": "第 4 則要求入金並強調名額。"}


def test_format_messages_marks_non_text():
    text = format_messages(CONVO)
    assert "#1 [2026-10-01 10:00] 對方A：你好，我是投資分析師王老師" in text
    assert "#3 [2026-10-01 10:00] 對方A：[貼圖]" in text


def test_llm_success():
    client = FakeClient([good_output()])
    r = analyze(CONVO, client=client)
    assert r.analyzed_by == "llm" and r.model_name == "claude-opus-5-5"
    assert r.scam_type == "investment" and r.is_likely_scam
    assert r.messages[4]["tactics"][0]["code"] == "scarcity"
    assert r.messages[4]["requests_action"] is True
    call = client.calls[0]
    assert call["model"] == "claude-opus-5-5"
    assert call["output_config"]["effort"] == "medium"
    assert call["output_config"]["format"]["type"] == "json_schema"
    assert call["fallbacks"] == "default"
    assert call["betas"] == ["server-side-fallback-2026-07-01"]


def test_only_masked_text_sent():
    client = FakeClient([good_output()])
    analyze(CONVO, client=client)
    assert "名額只剩今天" in client.calls[0]["messages"][0]["content"]


def test_evidence_not_substring_dropped():
    out = good_output()
    out["messages"][0]["tactics"].append({"code": "scarcity", "evidence": "限時優惠", "confidence": 0.8})
    results, dropped = validate_output(out, CONVO)
    assert dropped == 1
    assert [t["code"] for t in results[1]["tactics"]] == ["authority"]


def test_unknown_seq_dropped():
    out = good_output()
    out["messages"].append({"seq": 999, "stage": "action", "requests_action": True, "tactics": []})
    _, dropped = validate_output(out, CONVO)
    assert dropped == 1


def test_unknown_code_dropped():
    out = good_output()
    out["messages"][0]["tactics"] = [{"code": "greed", "evidence": "投資", "confidence": 0.5}]
    results, dropped = validate_output(out, CONVO)
    assert dropped == 1 and results[1]["tactics"] == []


def test_self_message_tactics_dropped_stage_kept():
    out = good_output()
    out["messages"][1] = {"seq": 2, "stage": "rapport", "requests_action": True,
                          "tactics": [{"code": "liking", "evidence": "你好", "confidence": 0.5}]}
    results, dropped = validate_output(out, CONVO)
    assert dropped == 1
    assert results[2] == {"stage": "rapport", "requests_action": False, "tactics": []}


def test_missing_messages_filled():
    r = analyze(CONVO, client=FakeClient([good_output(seqs=(1, 4))]))
    assert r.messages[2] == {"stage": "none", "requests_action": False, "tactics": []}


def test_not_scam_has_no_type():
    out = good_output()
    out.update(is_likely_scam=False, scam_type="none")
    r = analyze(CONVO, client=FakeClient([out]))
    assert r.scam_type is None and not r.is_likely_scam


def test_no_api_key_uses_rules():
    r = analyze(CONVO, api_key=None)
    assert r.analyzed_by == "rule"
    assert r.fallback_reason == "未設定 API 憑證"
    codes = [t["code"] for t in r.messages[4]["tactics"]]
    assert "scarcity" in codes
    assert all(t["confidence"] == 0.5 for t in r.messages[4]["tactics"])


def test_network_error_falls_back_to_rules():
    err = anthropic.APIConnectionError(request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages"))
    r = analyze(CONVO, client=FakeClient([err]))
    assert r.analyzed_by == "rule" and "APIConnectionError" in r.fallback_reason


def test_refusal_falls_back_to_rules():
    refusal = SimpleNamespace(stop_reason="refusal", stop_details=SimpleNamespace(category="cyber"), content=[])
    r = analyze(CONVO, client=FakeClient([refusal]))
    assert r.analyzed_by == "rule" and "拒答" in r.fallback_reason


def test_invalid_json_falls_back_to_rules():
    r = analyze(CONVO, client=FakeClient(["不是 JSON"]))
    assert r.analyzed_by == "rule"


def test_text_after_fallback_block_used():
    final = SimpleNamespace(stop_reason="end_turn", stop_details=None, content=[
        SimpleNamespace(type="text", text='{"partial'),
        SimpleNamespace(type="fallback"),
        SimpleNamespace(type="text", text=json.dumps(good_output(), ensure_ascii=False)),
    ])
    r = analyze(CONVO, client=FakeClient([final]))
    assert r.analyzed_by == "llm"


def test_chunk_ranges():
    assert chunk_ranges(100, 150, 10) == [(0, 100)]
    assert chunk_ranges(300, 150, 10) == [(0, 150), (140, 290), (280, 300)]


def test_long_conversation_chunked_later_chunk_wins():
    convo = [msg(i, f"訊息{i}") for i in range(1, 301)]

    def output(start, end, stage):
        return {"messages": [{"seq": s, "stage": stage, "requests_action": False, "tactics": []}
                             for s in range(start, end + 1)],
                "scam_type": "none", "is_likely_scam": False, "summary": stage}

    client = FakeClient([output(1, 150, "rapport"), output(141, 290, "setup"), output(281, 300, "pressure")])
    r = analyze(convo, client=client)
    assert len(client.calls) == 3
    assert len(r.messages) == 300
    assert r.messages[140]["stage"] == "rapport"
    assert r.messages[141]["stage"] == "setup" and r.messages[150]["stage"] == "setup"
    assert r.messages[281]["stage"] == "pressure"


def test_rules_normal_chat_not_scam():
    convo = [msg(1, "晚上要不要一起吃飯？"), msg(2, "好啊，七點見", is_self=True), msg(3, "你今天穿得好漂亮")]
    r = analyze_rules(convo)
    assert not r.is_likely_scam and r.scam_type is None
