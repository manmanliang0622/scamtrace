"""話術標註：語言模型為主，規則比對為備援（SPEC §8、§9.1、§9.2）。

輸入一律是遮罩後的訊息；每則為 dict：seq、sent_at、speaker、is_self、text、msg_type。
輸出 AnalysisResult，其中 messages 以 seq 為鍵：stage、requests_action、tactics。
"""
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from taxonomy import (SCAM_TYPE_CODES, SCAM_TYPES, STAGE_CODES, STAGES,
                      TACTIC_CODES, TACTICS)

log = logging.getLogger(__name__)

LEXICON_DIR = Path(__file__).with_name("lexicon")
RULE_CONFIDENCE = 0.5
NON_TEXT_MARKERS = {"sticker": "[貼圖]", "image": "[照片]", "file": "[檔案]", "call": "[通話]", "system": "[系統訊息]"}
# 階段關鍵詞的判定優先順序
STAGE_PRIORITY = ["action", "pressure", "setup", "contact", "rapport"]


class AnalysisError(Exception):
    """語言模型分析無法使用（拒答、輸出格式不合法等），應改用規則比對。"""


@dataclass
class AnalysisResult:
    messages: dict                 # seq -> {"stage", "requests_action", "tactics": [{"code","evidence","confidence"}]}
    scam_type: str | None
    is_likely_scam: bool
    summary: str
    analyzed_by: str               # "llm" | "rule"
    model_name: str | None = None
    dropped: int = 0               # 驗證時丟棄的標註數
    fallback_reason: str | None = None
    notes: list = field(default_factory=list)


def empty_result(msg):
    return {"stage": "none", "requests_action": False, "tactics": []}


def taggable(msg):
    """只有對方的文字訊息可以標註手法。"""
    return not msg["is_self"] and msg["msg_type"] == "text"


# ---------------------------------------------------------------- 語言模型

SYSTEM_PROMPT = """你是協助民眾理解詐騙話術的分析員。使用者會提供一段已去識別化的聊天紀錄
（電話、帳號等個資已換成 [電話1]、[帳號1] 這類代號；「我」是上傳者本人，「對方A」「對方B」是其他人）。
請逐則判斷訊息的詐騙階段與說服手法，並判斷整段對話最可能的詐騙類型。

## 說服手法（code：名稱｜定義與典型說法）
{tactics}

## 詐騙階段（code：名稱｜說明）
{stages}

## 詐騙類型（code：名稱｜說明）
{scam_types}
- none：判斷不是詐騙

## 判斷原則
1. 只對「對方」的訊息標註手法；「我」的訊息只判斷階段，tactics 給空陣列。
2. 每個手法的 evidence 必須逐字複製自該則訊息內容（不可改寫、不可加減字、不可跨訊息），程式會檢查，不符者會被丟棄。
   evidence 取最能代表該手法的一小段即可。
3. 一般朋友聊天也會有讚美、推薦、閒聊，這些單獨出現不代表詐騙；是否為詐騙主要看對話是否走到
   「要求行動」（匯款、提供驗證碼或帳號、點連結、下載 App、加入群組）以及前後的鋪陳。
4. requests_action：該則訊息是否要求對方匯款、提供資料、點連結、下載或加入群組。
5. 標記為 [貼圖]、[照片] 等的非文字訊息，階段給 none、tactics 給空陣列。
6. confidence 為 0 到 1 之間的數字，代表你對該筆標註的把握。
7. summary 用一段繁體中文（100 字內）說明判斷依據，提到關鍵訊息的序號；不要重複個資代號以外的猜測。
8. 每一則訊息都要輸出一筆結果，seq 與輸入的序號相同。"""


def build_system_prompt():
    tactics = "\n".join(f"- {c}：{n}｜{d}" for c, n, _en, d, _color in TACTICS)
    stages = "\n".join(f"- {c}：{n}｜{d}" for c, n, d in STAGES)
    scam_types = "\n".join(f"- {c}：{n}｜{d}" for c, n, d in SCAM_TYPES)
    return SYSTEM_PROMPT.format(tactics=tactics, stages=stages, scam_types=scam_types)


OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "messages": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "seq": {"type": "integer"},
                    "stage": {"type": "string", "enum": STAGE_CODES},
                    "requests_action": {"type": "boolean"},
                    "tactics": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "code": {"type": "string", "enum": TACTIC_CODES},
                                "evidence": {"type": "string"},
                                "confidence": {"type": "number"},
                            },
                            "required": ["code", "evidence", "confidence"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["seq", "stage", "requests_action", "tactics"],
                "additionalProperties": False,
            },
        },
        "scam_type": {"type": "string", "enum": SCAM_TYPE_CODES + ["none"]},
        "is_likely_scam": {"type": "boolean"},
        "summary": {"type": "string"},
    },
    "required": ["messages", "scam_type", "is_likely_scam", "summary"],
    "additionalProperties": False,
}


def format_messages(messages):
    lines = []
    for m in messages:
        content = m["text"] if m["msg_type"] == "text" else NON_TEXT_MARKERS.get(m["msg_type"], m["text"])
        time = f"[{m['sent_at']}] " if m.get("sent_at") else ""
        lines.append(f"#{m['seq']} {time}{m['speaker']}：{content}")
    return "\n".join(lines)


def chunk_ranges(n, size, overlap):
    """回傳 [(start, end), ...]，每段 size 則、前後重疊 overlap 則。"""
    if n <= size:
        return [(0, n)]
    ranges, start = [], 0
    while True:
        end = min(start + size, n)
        ranges.append((start, end))
        if end == n:
            return ranges
        start = end - overlap


def validate_output(data, chunk):
    """驗證模型輸出；回傳 (seq -> 結果, 丟棄數)。結構不合法時丟出 AnalysisError。"""
    if not isinstance(data, dict) or not isinstance(data.get("messages"), list):
        raise AnalysisError("輸出缺少 messages")
    by_seq = {m["seq"]: m for m in chunk}
    results, dropped = {}, 0
    for item in data["messages"]:
        if not isinstance(item, dict):
            dropped += 1
            continue
        msg = by_seq.get(item.get("seq"))
        if msg is None:
            dropped += 1 + len(item.get("tactics") or [])
            continue
        stage = item.get("stage") if item.get("stage") in STAGE_CODES else "none"
        tactics, seen = [], set()
        for t in item.get("tactics") or []:
            code, evidence = t.get("code"), (t.get("evidence") or "").strip()
            ok = (taggable(msg) and code in TACTIC_CODES and code not in seen
                  and evidence and evidence in msg["text"])
            if not ok:
                dropped += 1
                continue
            seen.add(code)
            try:
                conf = min(1.0, max(0.0, float(t.get("confidence", 0.5))))
            except (TypeError, ValueError):
                conf = 0.5
            tactics.append({"code": code, "evidence": evidence, "confidence": conf})
        if msg["msg_type"] != "text":
            stage = "none"
        results[msg["seq"]] = {
            "stage": stage,
            "requests_action": bool(item.get("requests_action")) and taggable(msg),
            "tactics": tactics,
        }
    return results, dropped


def response_text(message):
    """取最後一個 fallback 區塊之後的文字（伺服器端備援時，前一個模型的部分輸出要丟棄）。"""
    texts = []
    for block in message.content:
        if block.type == "fallback":
            texts = []
        elif block.type == "text":
            texts.append(block.text)
    return "".join(texts)


def call_model(client, model, messages, part, parts):
    user = format_messages(messages)
    if parts > 1:
        user = f"（長對話分段分析：第 {part}/{parts} 段，序號 #{messages[0]['seq']}–#{messages[-1]['seq']}）\n\n" + user
    with client.beta.messages.stream(
        model=model,
        max_tokens=64000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={
            "effort": "medium",
            "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA},
        },
        system=build_system_prompt(),
        messages=[{"role": "user", "content": user}],
    ) as stream:
        final = stream.get_final_message()
    if final.stop_reason == "refusal":
        category = getattr(final.stop_details, "category", None) if final.stop_details else None
        raise AnalysisError(f"模型拒答（{category}）")
    if final.stop_reason == "max_tokens":
        raise AnalysisError("模型輸出被截斷")
    try:
        return json.loads(response_text(final))
    except json.JSONDecodeError as e:
        raise AnalysisError(f"輸出不是合法 JSON：{e.msg}")


def analyze_llm(messages, client, model, chunk_size=150, overlap=10):
    ranges = chunk_ranges(len(messages), chunk_size, overlap)
    merged, dropped, chunk_outputs = {}, 0, []
    for i, (start, end) in enumerate(ranges, start=1):
        chunk = messages[start:end]
        data = call_model(client, model, chunk, i, len(ranges))
        results, d = validate_output(data, chunk)
        dropped += d
        merged.update(results)  # 重疊部分以後段結果為準
        chunk_outputs.append(data)
    if not merged:
        raise AnalysisError("模型沒有回傳任何合法結果")
    for m in messages:
        merged.setdefault(m["seq"], empty_result(m))

    # 多段時：任一段判斷為詐騙即視為詐騙，類型與摘要取最後一個判斷為詐騙的段落
    scam_chunks = [c for c in chunk_outputs if c.get("is_likely_scam")]
    chosen = scam_chunks[-1] if scam_chunks else chunk_outputs[-1]
    is_scam = bool(scam_chunks)
    scam_type = chosen.get("scam_type") if is_scam else None
    if scam_type not in SCAM_TYPE_CODES:
        scam_type = "other" if is_scam else None
    return AnalysisResult(merged, scam_type, is_scam, str(chosen.get("summary", "")).strip(),
                          "llm", model, dropped)


# ---------------------------------------------------------------- 規則比對

def load_lexicon():
    def load(name):
        return json.loads((LEXICON_DIR / name).read_text(encoding="utf-8"))
    return {"tactics": load("tactics.json"), "stages": load("stages.json"), "scam_types": load("scam_types.json")}


def analyze_rules(messages, lexicon=None):
    lex = lexicon or load_lexicon()
    results = {}
    type_hits = {code: 0 for code in lex["scam_types"]}
    for m in messages:
        if m["msg_type"] != "text":
            results[m["seq"]] = empty_result(m)
            continue
        text = m["text"]
        stage = next((s for s in STAGE_PRIORITY if any(k in text for k in lex["stages"].get(s, []))), "none")
        tactics = []
        if taggable(m):
            for code in TACTIC_CODES:
                hit = next((k for k in lex["tactics"].get(code, []) if k in text), None)
                if hit:
                    tactics.append({"code": code, "evidence": hit, "confidence": RULE_CONFIDENCE})
            for code, words in lex["scam_types"].items():
                type_hits[code] += sum(1 for w in words if w in text)
        results[m["seq"]] = {"stage": stage, "requests_action": taggable(m) and stage == "action",
                             "tactics": tactics}

    action_seqs = [seq for seq, r in results.items() if r["requests_action"]]
    is_scam = bool(action_seqs)
    scam_type = None
    if is_scam:
        best = max(type_hits, key=type_hits.get)
        scam_type = best if type_hits[best] > 0 else "other"
    tactic_msgs = sum(1 for r in results.values() if r["tactics"])
    if is_scam:
        summary = (f"規則比對：對方共有 {tactic_msgs} 則訊息命中說服手法關鍵詞，"
                   f"第 {min(action_seqs)} 則起出現要求行動的字詞（共 {len(action_seqs)} 則）。")
    else:
        summary = f"規則比對：對方有 {tactic_msgs} 則訊息命中說服手法關鍵詞，但未出現要求匯款、提供資料等行動的字詞。"
    return AnalysisResult(results, scam_type, is_scam, summary, "rule")


# ---------------------------------------------------------------- 進入點

def make_client(api_key):
    import anthropic
    return anthropic.Anthropic(api_key=api_key, timeout=600.0, max_retries=2)


def analyze(messages, api_key=None, model="claude-opus-5-5", chunk_size=150, overlap=10, client=None):
    """語言模型可用時用模型分析，否則或失敗時改用規則比對。"""
    if client is None and not api_key:
        result = analyze_rules(messages)
        result.fallback_reason = "未設定 API 憑證"
        return result
    try:
        import anthropic
        return analyze_llm(messages, client or make_client(api_key), model, chunk_size, overlap)
    except (AnalysisError, anthropic.APIError) as e:
        # 只記錄錯誤類型，不記錄對話內容
        log.warning("語言模型分析失敗，改用規則比對：%s", type(e).__name__)
        reason = str(e) if isinstance(e, AnalysisError) else f"API 錯誤（{type(e).__name__}）"
    result = analyze_rules(messages)
    result.fallback_reason = reason
    return result
