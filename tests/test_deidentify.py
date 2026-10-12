from deidentify import apply_manual_mask, deidentify, luhn_ok


def msgs(*texts, speaker="王小明"):
    return [{"seq": i, "sent_at": None, "speaker": speaker, "text": t, "msg_type": "text"}
            for i, t in enumerate(texts, start=1)]


def mask(*texts, self_name="陳美玲"):
    out, counts = deidentify(msgs(*texts), self_name)
    return [m["text"] for m in out], counts


def test_mobile_phone():
    assert mask("打給我 0912-345-678")[0] == ["打給我 [電話1]"]


def test_mobile_international():
    assert mask("+886 912 345 678 或 0912345678")[0] == ["[電話1] 或 [電話1]"]


def test_landline():
    assert mask("公司 02-23456789")[0] == ["公司 [電話1]"]


def test_id_and_arc():
    assert mask("身分證 A123456789，居留證 AC12345678")[0] == ["身分證 [身分證1]，居留證 [居留證1]"]


def test_address():
    assert mask("寄到台北市大安區復興南路一段100號")[0] == ["寄到[地址1]"]


def test_address_trims_leading_words():
    assert mask("我住在台北市大安區復興南路一段100號喔")[0] == ["我住在[地址1]喔"]


def test_line_id():
    assert mask("加我 abc_123")[0] == ["加我 [LINEID1]"]
    assert mask("我的 line id: Scam_Teacher")[0] == ["我的 line id: [LINEID1]"]


def test_email():
    assert mask("寄到 a.b@example.com")[0] == ["寄到 [信箱1]"]


def test_card_with_luhn():
    assert luhn_ok("4111111111111111")
    assert mask("卡號 4111 1111 1111 1111")[0] == ["卡號 [卡號1]"]


def test_non_luhn_16_digits_becomes_bank_account():
    assert not luhn_ok("1234567812345678")
    assert mask("1234567812345678")[0] == ["[帳號1]"]


def test_account_not_split_into_phone():
    texts, counts = mask("匯到 09123456789012")
    assert texts == ["匯到 [帳號1]"]
    assert "phone" not in counts


def test_same_value_same_code():
    texts, counts = mask("帳號 12345678901234", "再確認 12345678901234", "就是 12345678901234")
    assert texts == ["帳號 [帳號1]", "再確認 [帳號1]", "就是 [帳號1]"]
    assert counts["bank_account"] == 3


def test_different_values_different_codes():
    assert mask("0912345678 和 0987654321")[0] == ["[電話1] 和 [電話2]"]


def test_url_keeps_domain():
    assert mask("點 https://example.com/login?id=abc 登入")[0] == ["點 https://example.com/[路徑] 登入"]
    assert mask("官網 www.scam-site.top/a/b")[0] == ["官網 www.scam-site.top/[路徑]"]


def test_url_without_path_unchanged():
    texts, counts = mask("看 https://example.com")
    assert texts == ["看 https://example.com"]
    assert "url" not in counts


def test_money_not_masked():
    text = "先匯 3 萬，明天再補 NT$30,000"
    assert mask(text)[0] == [text]


def test_speaker_aliases_and_names_in_text():
    data = [
        {"seq": 1, "sent_at": None, "speaker": "王小明", "text": "我是王小明啦", "msg_type": "text"},
        {"seq": 2, "sent_at": None, "speaker": "陳美玲", "text": "嗨", "msg_type": "text"},
        {"seq": 3, "sent_at": None, "speaker": "林老師", "text": "王小明介紹的", "msg_type": "text"},
    ]
    out, _ = deidentify(data, "陳美玲")
    assert [(m["speaker"], m["is_self"]) for m in out] == [("對方A", False), ("我", True), ("對方B", False)]
    assert out[0]["text"] == "我是對方A啦"
    assert out[2]["text"] == "對方A介紹的"


def test_counts():
    _, counts = mask("0912345678", "0987654321 還有 0912345678", "12345678901234 和 12345678901234")
    assert counts == {"phone": 3, "bank_account": 2}


def test_original_values_absent_from_output():
    out, counts = deidentify(msgs("電話 0912345678 帳號 12345678901234"), "我")
    blob = repr(out) + repr(counts)
    assert "0912345678" not in blob and "12345678901234" not in blob


def test_manual_mask_all_occurrences():
    data = [{"text": "林大華說的"}, {"text": "問林大華 [電話1]"}]
    counts = {"phone": 1}
    n = apply_manual_mask(data, "林大華", counts)
    assert n == 2
    assert [m["text"] for m in data] == ["[遮罩1]說的", "問[遮罩1] [電話1]"]
    assert counts["manual"] == 2


def test_manual_mask_does_not_break_codes():
    data = [{"text": "[電話1] 是電話"}]
    apply_manual_mask(data, "電話", {})
    assert data[0]["text"] == "[電話1] 是[遮罩1]"


def test_manual_mask_numbering_continues():
    data = [{"text": "[遮罩1] 與 王五"}]
    apply_manual_mask(data, "王五", {})
    assert data[0]["text"] == "[遮罩1] 與 [遮罩2]"


def test_phone_with_two_dashes():
    assert mask("我的電話 09-1234-5678")[0] == ["我的電話 [電話1]"]


def test_cn_mobile():
    assert mask("聯絡 13912345678")[0] == ["聯絡 [電話1]"]


def test_passport():
    assert mask("護照號碼：312345678")[0] == ["護照號碼：[護照1]"]


def test_form_style_personal_data():
    text = ("電話號碼：0912345678\n身分證字號：A123456789\n護照號碼：312345678\n"
            "Email:fake.user@example.com\n通訊地區：台中市南屯區公益路一段100號")
    out = mask(text)[0][0]
    for raw in ("0912345678", "A123456789", "312345678", "fake.user@example.com", "公益路"):
        assert raw not in out
