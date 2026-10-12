"""不連網、不花費的語言模型呼叫檢查（task 4.3 離線版）。

用真正的 anthropic SDK，但把 HTTP 傳輸層換成假的：
- 檢查 SDK 實際送出的請求（端點、beta 標頭、模型、effort、JSON schema、server-side fallback、只含遮罩後文字）
- 回傳一段串流（SSE）回應，讓 SDK 照正式流程組回訊息，再交給 analyzer 驗證與 risk 計分

回應內容 fixtures/llm_response_01.json 是依系統提示詞與 schema 手寫、代替模型輸出的測試資料，
不是標準答案；正式呼叫模型的結果仍需設定 ANTHROPIC_API_KEY 後才能取得。
"""
import json
from pathlib import Path

import anthropic
import httpx2

import risk
from analyzer import OUTPUT_SCHEMA, analyze
from deidentify import deidentify
from parser import parse_line_export

ROOT = Path(__file__).resolve().parent.parent
RESPONSE = json.loads((Path(__file__).parent / "fixtures" / "llm_response_01.json").read_text(encoding="utf-8"))


def demo_messages():
    text = (ROOT / "demo_data" / "01_investment.txt").read_text(encoding="utf-8")
    raw = parse_line_export(text)
    masked, _ = deidentify(raw.messages, "林雅婷")
    return text, masked


def sse(text, pieces=5):
    """把文字切成幾段 text_delta，組成 Messages API 的串流回應。"""
    events = [
        ("message_start", {"type": "message_start", "message": {
            "id": "msg_offline", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
            "content": [], "stop_reason": None, "stop_sequence": None,
            "usage": {"input_tokens": 1, "output_tokens": 0}}}),
        ("content_block_start", {"type": "content_block_start", "index": 0,
                                 "content_block": {"type": "text", "text": ""}}),
    ]
    size = len(text) // pieces + 1
    for i in range(0, len(text), size):
        events.append(("content_block_delta", {"type": "content_block_delta", "index": 0,
                                               "delta": {"type": "text_delta", "text": text[i:i + size]}}))
    events += [
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                           "usage": {"output_tokens": 1}}),
        ("message_stop", {"type": "message_stop"}),
    ]
    body = "".join(f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n" for name, data in events)
    return body.encode("utf-8")


def offline_client(response_text, captured):
    def handler(request):
        captured.append(request)
        return httpx2.Response(200, headers={"content-type": "text/event-stream"}, content=sse(response_text))
    return anthropic.Anthropic(api_key="sk-ant-offline-test", max_retries=0,
                               http_client=httpx2.Client(transport=httpx2.MockTransport(handler)))


def test_request_sent_by_sdk():
    raw_text, masked = demo_messages()
    captured = []
    analyze(masked, client=offline_client(json.dumps(RESPONSE, ensure_ascii=False), captured))

    assert len(captured) == 1
    req = captured[0]
    assert req.method == "POST" and req.url.path == "/v1/messages"
    assert "server-side-fallback-2026-07-01" in req.headers.get("anthropic-beta", "")
    body = json.loads(req.content)
    assert body["model"] == "claude-opus-5-5"
    assert body["stream"] is True
    assert body["fallbacks"] == "default"
    assert body["output_config"]["effort"] == "medium"
    assert body["output_config"]["format"] == {"type": "json_schema", "schema": OUTPUT_SCHEMA}
    assert "evidence 必須逐字複製" in body["system"]

    sent = body["messages"][0]["content"]
    assert "#35" in sent and "[帳號1]" in sent and "[電話1]" in sent
    # 原文中的名字、LINE ID、網址路徑都不應送出
    for secret in ("王志明", "林雅婷", "stock_wang888"):
        assert secret in raw_text and secret not in sent


def test_streamed_response_parsed_and_scored():
    _, masked = demo_messages()
    r = analyze(masked, client=offline_client(json.dumps(RESPONSE, ensure_ascii=False), []))

    assert r.analyzed_by == "llm" and r.fallback_reason is None
    assert r.dropped == 0
    assert r.is_likely_scam and r.scam_type == "investment"
    assert set(r.messages) == {m["seq"] for m in masked}
    assert [t["code"] for t in r.messages[23]["tactics"]] == ["scarcity", "urgency_threat"]
    # 我的訊息、圖片不會有手法
    assert all(not r.messages[m["seq"]]["tactics"] for m in masked if m["is_self"] or m["msg_type"] != "text")

    rows = [{"seq": m["seq"], "is_self": m["is_self"], **r.messages[m["seq"]]} for m in masked]
    overall, level, turning = risk.score_case(rows)
    assert level == "high" and turning == 20


def test_bad_items_in_streamed_response_dropped():
    _, masked = demo_messages()
    data = json.loads(json.dumps(RESPONSE))
    data["messages"][1]["tactics"] = [{"code": "liking", "evidence": "喔喔你好", "confidence": 0.5}]  # 我的訊息
    data["messages"][2]["tactics"].append({"code": "authority", "evidence": "原文沒有這句", "confidence": 0.5})
    r = analyze(masked, client=offline_client(json.dumps(data, ensure_ascii=False), []))
    assert r.analyzed_by == "llm" and r.dropped == 2
