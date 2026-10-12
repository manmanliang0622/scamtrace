import pytest

from parser import ParseError, decode_bytes, parse, parse_line_export, parse_paste

SAMPLE = (
    "[LINE] 與王小明的聊天記錄\n"
    "儲存日期：2026/10/09 14:00\n"
    "\n"
    "2026/10/01（三）\n"
    "14:05\t王小明\t你好，好久不見\n"
    "14:06\t王小明\t[貼圖]\n"
    "下午02:07\t陳美玲\t\"第一行\n"
    "第二行\"\n"
    "2026/10/02（四）\n"
    "上午12:30\t陳美玲\t晚安\n"
    "下午2:15\t王小明\t☎ 通話時間 3:21\n"
)


def test_basic_message_and_header_skipped():
    r = parse_line_export(SAMPLE)
    first = r.messages[0]
    assert first == {"seq": 1, "sent_at": "2026-10-01 14:05", "speaker": "王小明",
                     "text": "你好，好久不見", "msg_type": "text"}
    assert all("LINE" not in m["text"] and "儲存日期" not in m["text"] for m in r.messages)
    assert len(r.messages) == 5


def test_multiline_message_merged_and_quotes_removed():
    r = parse_line_export(SAMPLE)
    m = r.messages[2]
    assert m["text"] == "第一行\n第二行"
    assert m["sent_at"] == "2026-10-01 14:07"


def test_am_pm_conversion():
    r = parse_line_export(SAMPLE)
    assert r.messages[3]["sent_at"] == "2026-10-02 00:30"
    assert r.messages[4]["sent_at"] == "2026-10-02 14:15"


def test_special_types():
    r = parse_line_export(SAMPLE)
    assert r.messages[1]["msg_type"] == "sticker"
    assert r.messages[4]["msg_type"] == "call"
    r2 = parse_line_export("10:00\tA\t[照片]\n10:01\tA\t[檔案]\n")
    assert [m["msg_type"] for m in r2.messages] == ["image", "file"]


def test_speakers_in_order():
    assert parse_line_export(SAMPLE).speakers == ["王小明", "陳美玲"]


def test_paste_mode_full_and_half_width_colon():
    r = parse_paste("阿明：在嗎\n我: 在\n下一行接續\n")
    assert [(m["speaker"], m["text"]) for m in r.messages] == [("阿明", "在嗎"), ("我", "在\n下一行接續")]


def test_paste_mode_accepts_line_format():
    r = parse("14:05\t王小明\t你好\n", "paste")
    assert r.messages[0]["speaker"] == "王小明"


def test_utf16_decoding():
    data = SAMPLE.encode("utf-16")
    assert len(parse_line_export(decode_bytes(data)).messages) == 5


def test_utf8_bom():
    assert decode_bytes("﻿14:05\tA\tB".encode("utf-8")).startswith("14:05")


def test_truncate_to_last_2000():
    text = "2026/10/01（三）\n" + "".join(f"10:00\tA\t訊息{i}\n" for i in range(1, 2501))
    r = parse_line_export(text)
    assert len(r.messages) == 2000
    assert r.truncated_from == 2500
    assert r.messages[0]["seq"] == 1 and r.messages[0]["text"] == "訊息501"
    assert r.messages[-1]["text"] == "訊息2500"
    assert r.warnings


def test_no_messages_raises():
    with pytest.raises(ParseError):
        parse("這不是聊天紀錄\n只是一般文字", "line_txt")


def test_system_message():
    r = parse_line_export("10:00\t王小明已收回訊息\n10:01\t王小明\t嗨\n")
    assert r.messages[0]["msg_type"] == "system"
    assert r.speakers == ["王小明"]


# ---------------- 實際匯出格式（依真實匯出檔觀察，內容為假資料） ----------------
from pathlib import Path

import pytest as _pytest

FIXTURES = Path(__file__).parent / "fixtures"


@_pytest.mark.parametrize("name", ["line_ios_sample.txt", "line_ios_sample_spaces.txt"])
def test_real_export_format(name):
    r = parse_line_export((FIXTURES / name).read_text(encoding="utf-8"))
    by_text = {m["text"]: m for m in r.messages}
    assert r.messages[0] == {"seq": 1, "sent_at": "2026-05-15 13:39", "speaker": "小美",
                             "text": "在嗎", "msg_type": "text"}
    assert by_text["貼圖"]["msg_type"] == "sticker"
    assert by_text["圖片"]["msg_type"] == "image"
    assert by_text["01:41"]["msg_type"] == "call"
    assert by_text["1:28:54"]["msg_type"] == "call"
    assert by_text["未接來電"]["msg_type"] == "call"
    assert by_text["期末專題企畫書.pdf"]["msg_type"] == "file"
    assert by_text["期末專題企畫書.pdf"]["sent_at"] == "2026-05-16 20:40"
    assert by_text["第一行\n第二行\n第三行"]["speaker"] == "王大明"
    assert by_text["已收回訊息"]["msg_type"] == "system"
    assert by_text["小美已設定<u>公告</u>"]["msg_type"] == "system"
    assert by_text["4個項目已新增至相簿。"]["msg_type"] == "system"
    assert by_text["看看"]["speaker"] == "小美"
    assert by_text["(watching)"]["msg_type"] == "sticker"
    assert by_text["(tear (dot))"]["msg_type"] == "sticker"
    assert by_text["https://maps.app.goo.gl/abc123?g_st=il"]["msg_type"] == "text"
    assert r.speakers == ["小美", "王大明"]


def test_dot_date_without_weekday():
    r = parse_line_export("2026.05.15\n10:00\tA\t嗨\n")
    assert r.messages[0]["sent_at"] == "2026-05-15 10:00"


def test_date_like_text_inside_message_not_treated_as_date():
    r = parse_line_export("2026.05.15 星期五\n10:00\tA\t生日是\n2005/06/22 喔\n")
    assert r.messages[0]["text"] == "生日是\n2005/06/22 喔"
