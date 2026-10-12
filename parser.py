"""解析 LINE 匯出的 .txt 與貼上的文字，產生訊息清單（SPEC §7.1）。

每則訊息為 dict：seq、sent_at、speaker、text、msg_type。
"""
import re
from dataclasses import dataclass, field

MAX_MESSAGES = 2000

HEADER_PREFIXES = ("[LINE]", "儲存日期")
# 日期列：2026/10/01（三）、2026.05.15 星期五、2026-10-01
DATE_RE = re.compile(
    r"^(\d{4})[/.\-](\d{1,2})[/.\-](\d{1,2})"
    r"\s*(?:[（(]?\s*(?:星期|週|周)?\s*[一二三四五六日天][)）]?)?\s*$"
)
# 訊息列：時間 + TAB 或空白 + 其餘；時間可為 14:05、下午02:07、下午2:07
LINE_RE = re.compile(r"^(?:(上午|下午)\s?)?(\d{1,2}):(\d{2})[\t ](.*)$")
PASTE_RE = re.compile(r"^([^：:\t]{1,30}?)\s*[：:]\s?(.*)$")

# 非文字訊息（新版匯出沒有中括號，舊版有）
SPECIAL_TYPES = {
    "貼圖": "sticker", "[貼圖]": "sticker",
    "圖片": "image", "照片": "image", "[照片]": "image", "影片": "image", "[影片]": "image",
    "檔案": "file", "[檔案]": "file",
    "未接來電": "call", "取消": "call",
}
CALL_DURATION_RE = re.compile(r"^\d{1,2}(?::\d{2}){1,2}$")          # 01:41、1:28:54
FILE_NAME_RE = re.compile(r"^\S.*\.(?:pdf|docx?|xlsx?|pptx?|jpe?g|png|heic|zip|txt)$", re.IGNORECASE)
EMOJI_ONLY_RE = re.compile(r"^(?:\([A-Za-z !?\-]+(?:\s*\([A-Za-z ]+\))?\))+$")  # (watching)、(tear (dot))
SYSTEM_KEYWORDS = ("已收回訊息", "項目已新增至相簿", "已建立「", "已設定", "您收到禮物貼圖", "禮物已送出",
                   "已加入群組", "已退出群組", "邀請")
SYSTEM_SPEAKER = ""


class ParseError(ValueError):
    pass


@dataclass
class ParseResult:
    messages: list
    speakers: list
    truncated_from: int = 0  # 截取前的訊息數；0 表示未截取
    warnings: list = field(default_factory=list)


def decode_bytes(data):
    """先試 UTF-8（含 BOM），失敗再試 UTF-16；都失敗則拒絕。"""
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        pass
    try:
        text = data.decode("utf-16")
    except UnicodeDecodeError:
        raise ParseError("無法辨識檔案編碼，請確認是 UTF-8 或 UTF-16 的文字檔。")
    return text.lstrip("﻿")


def to_24h(ampm, hour, minute):
    hour, minute = int(hour), int(minute)
    if ampm == "上午" and hour == 12:
        hour = 0
    elif ampm == "下午" and hour < 12:
        hour += 12
    if hour > 23 or minute > 59:
        return None
    return f"{hour:02d}:{minute:02d}"


def classify(text):
    stripped = text.strip()
    if stripped in SPECIAL_TYPES:
        return SPECIAL_TYPES[stripped]
    if stripped.startswith("☎") or CALL_DURATION_RE.match(stripped):
        return "call"
    if FILE_NAME_RE.match(stripped) and "\n" not in stripped:
        return "file"
    if EMOJI_ONLY_RE.match(stripped):
        return "sticker"
    if "\n" not in stripped and any(k in stripped for k in SYSTEM_KEYWORDS) and len(stripped) <= 40:
        return "system"
    return "text"


def _finish(messages, max_messages):
    for m in messages:
        text = m["text"]
        # LINE 會用雙引號包住多行訊息
        if m.pop("_multiline", False) and len(text) >= 2 and text.startswith('"') and text.endswith('"'):
            text = text[1:-1]
        m["text"] = text.strip("\n")
        if m["msg_type"] != "system":
            m["msg_type"] = classify(m["text"])

    truncated_from = 0
    if len(messages) > max_messages:
        truncated_from = len(messages)
        messages = messages[-max_messages:]
    for i, m in enumerate(messages, start=1):
        m["seq"] = i

    speakers = []
    for m in messages:
        if m["msg_type"] != "system" and m["speaker"] not in speakers:
            speakers.append(m["speaker"])
    warnings = []
    if truncated_from:
        warnings.append(f"對話共 {truncated_from} 則，只保留最後 {max_messages} 則。")
    return ParseResult(messages, speakers, truncated_from, warnings)


def split_speaker(rest):
    """「名字<TAB>內容」或「名字 內容」。沒有分隔時視為系統訊息（例如「已收回訊息」）。"""
    if "\t" in rest:
        speaker, _, text = rest.partition("\t")
        return speaker.strip(), text
    if " " in rest:
        speaker, _, text = rest.partition(" ")
        return speaker.strip(), text
    return None, rest


def parse_line_export(text, max_messages=MAX_MESSAGES):
    messages = []
    current_date = None
    for raw in text.lstrip("\ufeff").splitlines():
        line = raw.rstrip("\r")
        if line.startswith(HEADER_PREFIXES):
            continue
        date_m = DATE_RE.match(line.strip())
        if date_m:
            y, mo, d = (int(x) for x in date_m.groups())
            current_date = f"{y:04d}-{mo:02d}-{d:02d}"
            continue
        m = LINE_RE.match(line)
        hhmm = to_24h(m.group(1), m.group(2), m.group(3)) if m else None
        if hhmm:
            sent_at = f"{current_date} {hhmm}" if current_date else hhmm
            speaker, body = split_speaker(m.group(4))
            if speaker:
                messages.append({"sent_at": sent_at, "speaker": speaker, "text": body, "msg_type": "text"})
            else:
                messages.append({"sent_at": sent_at, "speaker": SYSTEM_SPEAKER, "text": body, "msg_type": "system"})
            continue
        if messages:
            messages[-1]["text"] += "\n" + line
            messages[-1]["_multiline"] = True
    return _finish(messages, max_messages)


def parse_paste(text, max_messages=MAX_MESSAGES):
    """貼上文字：每行「名字：內容」。若貼上的其實是 LINE 匯出格式，改用匯出檔解析。"""
    line_result = parse_line_export(text, max_messages)
    if line_result.messages:
        return line_result
    messages = []
    for raw in text.lstrip("﻿").splitlines():
        line = raw.rstrip("\r")
        m = PASTE_RE.match(line)
        if m and m.group(1).strip():
            messages.append({"sent_at": None, "speaker": m.group(1).strip(),
                             "text": m.group(2), "msg_type": "text"})
        elif messages:
            messages[-1]["text"] += "\n" + line
    return _finish(messages, max_messages)


def parse(text, source_type, max_messages=MAX_MESSAGES):
    result = parse_line_export(text, max_messages) if source_type == "line_txt" else parse_paste(text, max_messages)
    if not result.messages:
        raise ParseError(
            "找不到可解析的訊息。LINE 匯出檔每則訊息應為「時間<TAB>名字<TAB>內容」；"
            "貼上文字請每行寫成「名字：內容」。"
        )
    return result
