import csv
import json
import shutil
from pathlib import Path

import label_sheet

DEMO = Path(__file__).resolve().parent.parent / "demo_data"


def setup_demo(tmp_path, name):
    for ext in (".txt", ".json"):
        shutil.copy(DEMO / f"{name}{ext}", tmp_path / f"{name}{ext}")
    assert label_sheet.main(["export", "--demo-dir", str(tmp_path)]) == 0
    return tmp_path / "labels" / f"{name}.csv"


def read_rows(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_rows(path, rows):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=label_sheet.HEADER)
        w.writeheader()
        w.writerows(rows)


def test_export_lists_every_message_with_self_marked(tmp_path):
    rows = read_rows(setup_demo(tmp_path, "01_investment"))
    assert len(rows) == 35
    assert rows[0]["序號"] == "1" and rows[0]["發話者"] == "王志明分析師"
    assert rows[1]["發話者"] == "我"
    assert rows[3]["訊息"] == "圖片"


def test_export_does_not_overwrite(tmp_path):
    path = setup_demo(tmp_path, "07_normal_dinner")
    path.write_text("我填到一半", encoding="utf-8")
    label_sheet.main(["export", "--demo-dir", str(tmp_path)])
    assert path.read_text(encoding="utf-8") == "我填到一半"


def test_import_accepts_names_and_codes(tmp_path):
    path = setup_demo(tmp_path, "01_investment")
    rows = read_rows(path)
    for r in rows:
        r["階段"], r["手法"], r["轉折點"] = "無", "", ""
    rows[0]["階段"], rows[0]["手法"] = "接觸", "權威 承諾"
    rows[22]["階段"], rows[22]["手法"] = "action", "稀少性、urgency_threat"
    rows[19]["轉折點"] = "v"
    write_rows(path, rows)

    assert label_sheet.main(["import", "--demo-dir", str(tmp_path)]) == 0
    meta = json.loads((tmp_path / "01_investment.json").read_text(encoding="utf-8"))
    assert meta["turning_point"] == 20
    assert meta["messages"]["1"] == {"stage": "contact", "tactics": ["authority", "commitment"]}
    assert meta["messages"]["23"] == {"stage": "action", "tactics": ["scarcity", "urgency_threat"]}
    assert meta["messages"]["2"] == {"stage": "none", "tactics": []}
    assert meta["pii"] and meta["source"]["url"]  # 其他欄位保留


def test_import_errors_block_writing(tmp_path, capsys):
    path = setup_demo(tmp_path, "01_investment")
    before = (tmp_path / "01_investment.json").read_text(encoding="utf-8")
    rows = read_rows(path)
    for r in rows:
        r["階段"], r["手法"], r["轉折點"] = "無", "", ""
    rows[0]["階段"] = "鋪成"            # 打錯字
    rows[1]["手法"] = "喜好"            # 我的訊息
    rows[2]["手法"] = "恐嚇"            # 不存在的手法
    del rows[5]                         # 漏一則
    write_rows(path, rows)

    assert label_sheet.main(["import", "--demo-dir", str(tmp_path)]) == 1
    out = capsys.readouterr().out
    for expected in ("#1：階段 鋪成 不合法", "#2：「我」的訊息不標手法", "#3：手法 恐嚇 不合法",
                     "缺少第 [6] 則", "轉折點要剛好標一則"):
        assert expected in out
    assert (tmp_path / "01_investment.json").read_text(encoding="utf-8") == before


def test_normal_conversation_rejects_turning_point(tmp_path, capsys):
    path = setup_demo(tmp_path, "07_normal_dinner")
    rows = read_rows(path)
    for r in rows:
        r["階段"], r["手法"], r["轉折點"] = "none", "", ""
    rows[3]["轉折點"] = "v"
    write_rows(path, rows)
    assert label_sheet.main(["import", "--demo-dir", str(tmp_path)]) == 1
    assert "正常對話不標轉折點" in capsys.readouterr().out
