"""個資偵測與遮罩，在本機執行（SPEC §7.2）。

原文與「代號 ↔ 原值」對照只存在於 Masker 物件中，函式回傳後即丟棄；
回傳值只含遮罩後文字與各類個資的遮罩處數。
"""
import re

# 已替換的片段先換成私用區字元組成的佔位符（不含數字與英文字母），
# 確保後面的規則不會再比對到；全部規則跑完後再換成最後的代號。
_PH_OPEN, _PH_CLOSE, _PH_BASE = "", "", 0xE100
_PH_RE = re.compile(f"{_PH_OPEN}(.){_PH_CLOSE}")

TYPE_LABELS = {
    "card": "卡號", "id_number": "身分證", "arc_number": "居留證", "email": "信箱",
    "url": "網址", "phone": "電話", "bank_account": "帳號", "line_id": "LINEID",
    "address": "地址", "passport": "護照", "manual": "遮罩",
}

CODE_RE = re.compile(r"\[(?:卡號|身分證|居留證|信箱|電話|帳號|LINEID|地址|護照|遮罩)\d+\]|\[路徑\]")

CARD_RE = re.compile(r"(?<!\d)\d(?:[ -]?\d){12,18}(?!\d)")
ID_RE = re.compile(r"(?<![A-Za-z0-9])[A-Z][12]\d{8}(?!\d)")
ARC_RE = re.compile(r"(?<![A-Za-z0-9])[A-Z][A-D89]\d{8}(?!\d)")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
URL_RE = re.compile(
    r"(?P<prefix>https?://(?:www\.)?|www\.)(?P<domain>[A-Za-z0-9.-]+(?::\d+)?)"
    r"(?P<rest>[/?#][A-Za-z0-9\-._~:/?#\[\]@!$&'()*+,;=%]*)?"
)
MOBILE_RE = re.compile(
    r"(?<!\d)(?:09\d{2}-?\d{3}-?\d{3}|09-\d{4}-\d{4}|\+886[ -]?9\d{2}[ -]?\d{3}[ -]?\d{3})(?!\d)"
)
CN_MOBILE_RE = re.compile(r"(?<!\d)(?:\+?86[ -]?)?1[3-9]\d{9}(?!\d)")
PASSPORT_RE = re.compile(r"(?P<lead>護照(?:號碼|號)?\s*[:：]?\s*)(?P<value>[A-Z]?\d{8,9})(?!\d)")
LANDLINE_RE = re.compile(r"(?<!\d)0\d{1,2}-?\d{6,8}(?!\d)")
BANK_RE = re.compile(r"(?<!\d)\d{10,16}(?!\d)")
LINE_ID_RE = re.compile(
    r"(?P<lead>(?:line\s*id|(?<![A-Za-z])id|加我(?:\s*line)?)\s*[:：]?\s*@?)(?P<value>[A-Za-z0-9._-]{4,20})",
    re.IGNORECASE,
)
_ADDR_CH = r"[一-鿿0-9０-９\-]"
ADDRESS_RE = re.compile(
    rf"(?:{_ADDR_CH}{{2}}[縣市])?{_ADDR_CH}{{1,3}}?[區鄉鎮市]{_ADDR_CH}{{1,10}}?[路街道]{_ADDR_CH}{{0,10}}?號"
)
CITIES = ("臺北市", "台北市", "新北市", "桃園市", "臺中市", "台中市", "臺南市", "台南市", "高雄市",
          "基隆市", "新竹市", "嘉義市", "新竹縣", "苗栗縣", "彰化縣", "南投縣", "雲林縣", "嘉義縣",
          "屏東縣", "宜蘭縣", "花蓮縣", "臺東縣", "台東縣", "澎湖縣", "金門縣", "連江縣")


def luhn_ok(digits):
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def normalize_phone(value):
    digits = re.sub(r"\D", "", value)
    if digits.startswith("8869"):
        digits = "0" + digits[3:]
    return digits


class Masker:
    def __init__(self):
        self.codes = {}      # (pii_type, 正規化原值) -> 代號
        self.next_no = {}    # pii_type -> 下一個編號
        self.counts = {}     # pii_type -> 遮罩處數
        self.slots = []      # 佔位符序號 -> 最後輸出文字

    def code_for(self, pii_type, key):
        if (pii_type, key) not in self.codes:
            n = self.next_no.get(pii_type, 0) + 1
            self.next_no[pii_type] = n
            self.codes[(pii_type, key)] = f"[{TYPE_LABELS[pii_type]}{n}]"
        return self.codes[(pii_type, key)]

    def placeholder(self, output):
        self.slots.append(output)
        return f"{_PH_OPEN}{chr(_PH_BASE + len(self.slots) - 1)}{_PH_CLOSE}"

    def hit(self, pii_type, key):
        self.counts[pii_type] = self.counts.get(pii_type, 0) + 1
        return self.placeholder(self.code_for(pii_type, key))

    # ----- 各規則 -----

    def _card(self, m):
        digits = re.sub(r"\D", "", m.group(0))
        if 13 <= len(digits) <= 19 and luhn_ok(digits):
            return self.hit("card", digits)
        return m.group(0)

    def _url(self, m):
        rest = m.group("rest") or ""
        if rest in ("", "/"):
            return self.placeholder(m.group(0))
        self.counts["url"] = self.counts.get("url", 0) + 1
        return self.placeholder(f"{m.group('prefix')}{m.group('domain')}/[路徑]")

    def _line_id(self, m):
        return m.group("lead") + self.hit("line_id", m.group("value").lower())

    def _address(self, m):
        text = m.group(0)
        # 位置最前面的縣市名之前的字（例如「住在」）不屬於地址
        starts = [text.find(c) for c in CITIES if c in text]
        cut = min(starts) if starts else 0
        return text[:cut] + self.hit("address", text[cut:])

    def mask_text(self, text):
        text = CARD_RE.sub(self._card, text)
        text = ID_RE.sub(lambda m: self.hit("id_number", m.group(0)), text)
        text = ARC_RE.sub(lambda m: self.hit("arc_number", m.group(0)), text)
        text = EMAIL_RE.sub(lambda m: self.hit("email", m.group(0).lower()), text)
        text = URL_RE.sub(self._url, text)
        text = MOBILE_RE.sub(lambda m: self.hit("phone", normalize_phone(m.group(0))), text)
        text = CN_MOBILE_RE.sub(lambda m: self.hit("phone", re.sub(r"\D", "", m.group(0))[-11:]), text)
        text = LANDLINE_RE.sub(lambda m: self.hit("phone", normalize_phone(m.group(0))), text)
        text = PASSPORT_RE.sub(lambda m: m.group("lead") + self.hit("passport", m.group("value")), text)
        text = BANK_RE.sub(lambda m: self.hit("bank_account", m.group(0)), text)
        text = LINE_ID_RE.sub(self._line_id, text)
        text = ADDRESS_RE.sub(self._address, text)
        return text

    def finalize(self, text):
        return _PH_RE.sub(lambda m: self.slots[ord(m.group(1)) - _PH_BASE], text)


def speaker_aliases(speakers, self_name):
    aliases, n = {}, 0
    for name in speakers:
        if name == self_name:
            aliases[name] = "我"
        else:
            aliases[name] = "對方" + _letters(n)
            n += 1
    return aliases


def _letters(n):
    """0 -> A, 25 -> Z, 26 -> AA"""
    s = ""
    n += 1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def deidentify(messages, self_name):
    """回傳 (遮罩後訊息清單, 各類個資遮罩處數)。輸入的原文不會出現在回傳值中。"""
    speakers = [m["speaker"] for m in messages if m["msg_type"] != "system"]
    speakers = list(dict.fromkeys(speakers))
    aliases = speaker_aliases(speakers, self_name)
    # 內文中的名字：長的先換；單一字元的名字太容易誤換，不處理
    names = sorted((n for n in aliases if len(n) >= 2), key=len, reverse=True)

    masker = Masker()
    out = []
    for m in messages:
        text = masker.mask_text(m["text"])
        for name in names:
            if name in text:
                text = text.replace(name, masker.placeholder(aliases[name]))
        is_system = m["msg_type"] == "system"
        out.append({
            "seq": m["seq"],
            "sent_at": m["sent_at"],
            "speaker": "系統" if is_system else aliases[m["speaker"]],
            "is_self": (not is_system) and m["speaker"] == self_name,
            "text": masker.finalize(text),
            "msg_type": m["msg_type"],
        })
    return out, dict(masker.counts)


def apply_manual_mask(messages, fragment, pii_counts):
    """在遮罩後文字中把 fragment 的所有出現處換成同一個 [遮罩N]。

    既有代號（例如 [電話1]）內部不會被替換。回傳替換處數；0 表示沒找到。
    """
    if not fragment or not fragment.strip():
        return 0
    used = [int(n) for m in messages for n in re.findall(r"\[遮罩(\d+)\]", m["text"])]
    code = f"[遮罩{max(used, default=0) + 1}]"
    total = 0
    for m in messages:
        parts = CODE_RE.split(m["text"])
        seps = CODE_RE.findall(m["text"])
        new_parts = []
        for part in parts:
            total += part.count(fragment)
            new_parts.append(part.replace(fragment, code))
        rebuilt = new_parts[0]
        for sep, part in zip(seps, new_parts[1:]):
            rebuilt += sep + part
        m["text"] = rebuilt
    if total:
        pii_counts["manual"] = pii_counts.get("manual", 0) + total
    return total
