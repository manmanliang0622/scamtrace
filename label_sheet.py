"""示範資料標註表：把 demo_data/<name>.json 的逐則標註轉成 CSV 方便用試算表填寫，填完再轉回 JSON。

用法：
    python label_sheet.py export            # 產生 demo_data/labels/<name>.csv（已存在的不覆蓋，加 --force 覆蓋）
    python label_sheet.py import            # 檢查並寫回 demo_data/<name>.json；有任何錯誤就不寫入

CSV 欄位：序號、發話者、訊息、階段、手法、轉折點
- 階段：填一個，中文名稱或代號皆可（例如「要求行動」或 action）
- 手法：可留空或填多個，以空白、逗號或頓號分隔（例如「稀少性、威脅恐嚇」）
- 轉折點：詐騙對話在其中一列填任意字（例如 v）；正常對話全部留空
"""
import argparse
import csv
import json
import re
import sys
from pathlib import Path

from parser import parse
from seed import DEMO_DIR, load_demo_set
from taxonomy import STAGES, TACTICS

LABEL_DIR = DEMO_DIR / "labels"
HEADER = ["序號", "發話者", "訊息", "階段", "手法", "轉折點"]

STAGE_BY_NAME = {name: code for code, name, _d in STAGES}
STAGE_NAME = {code: name for code, name, _d in STAGES}
TACTIC_BY_NAME = {name: code for code, name, _en, _d, _c in TACTICS}
TACTIC_NAME = {code: name for code, name, _en, _d, _c in TACTICS}
TACTIC_BY_NAME["承諾"] = "commitment"  # 常見簡寫，不會與其他手法混淆


def to_code(value, by_name, codes):
    value = value.strip()
    if value in codes:
        return value
    return by_name.get(value)


def export_sheet(name, text, meta, out_path):
    messages = parse(text, "line_txt").messages
    labels = meta.get("messages", {})
    with open(out_path, "w", encoding="utf-8-sig", newline="") as f:  # 加 BOM，Excel 才不會亂碼
        w = csv.writer(f)
        w.writerow(HEADER)
        for m in messages:
            lab = labels.get(str(m["seq"]), {})
            speaker = "我" if m["speaker"] == meta["self_name"] else m["speaker"]
            w.writerow([
                m["seq"], speaker, m["text"],
                STAGE_NAME.get(lab.get("stage"), ""),
                "、".join(TACTIC_NAME.get(c, c) for c in lab.get("tactics", [])),
                "v" if meta.get("turning_point") == m["seq"] else "",
            ])


def read_sheet(name, text, meta, csv_path):
    """回傳 (messages 標註, turning_point, 錯誤清單)。"""
    messages = parse(text, "line_txt").messages
    self_seqs = {m["seq"] for m in messages if m["speaker"] == meta["self_name"]}
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    errors, labels, turning = [], {}, []
    for row in rows:
        try:
            seq = int((row.get("序號") or "").strip())
        except ValueError:
            errors.append(f"{name}：有一列的序號不是數字（{row.get('序號')!r}）")
            continue
        stage = to_code(row.get("階段") or "", STAGE_BY_NAME, STAGE_NAME)
        if stage is None:
            errors.append(f"{name} #{seq}：階段 {(row.get('階段') or '').strip() or '（空白）'} 不合法")
        tactics = []
        for t in re.split(r"[\s,，、;；/]+", (row.get("手法") or "").strip()):
            if not t:
                continue
            code = to_code(t, TACTIC_BY_NAME, TACTIC_NAME)
            if code is None:
                errors.append(f"{name} #{seq}：手法 {t} 不合法")
            elif code not in tactics:
                tactics.append(code)
        if tactics and seq in self_seqs:
            errors.append(f"{name} #{seq}：「我」的訊息不標手法")
        if (row.get("轉折點") or "").strip():
            turning.append(seq)
        labels[str(seq)] = {"stage": stage, "tactics": tactics}

    expected = {m["seq"] for m in messages}
    got = {int(s) for s in labels}
    if got != expected:
        missing, extra = sorted(expected - got), sorted(got - expected)
        if missing:
            errors.append(f"{name}：缺少第 {missing} 則")
        if extra:
            errors.append(f"{name}：多出第 {extra} 則（.txt 沒有這幾則）")
    if meta.get("is_scam") and len(turning) != 1:
        errors.append(f"{name}：詐騙對話的轉折點要剛好標一則（目前 {len(turning)} 則）")
    if not meta.get("is_scam") and turning:
        errors.append(f"{name}：正常對話不標轉折點")
    return labels, (turning[0] if len(turning) == 1 else None), errors


def main(argv=None):
    ap = argparse.ArgumentParser(description="示範資料標註表（CSV ↔ JSON）")
    ap.add_argument("action", choices=["export", "import"])
    ap.add_argument("--force", action="store_true", help="export 時覆蓋已存在的 CSV")
    ap.add_argument("--demo-dir", type=Path, default=DEMO_DIR)
    args = ap.parse_args(argv)
    label_dir = args.demo_dir / "labels"
    pairs = load_demo_set(args.demo_dir)

    if args.action == "export":
        label_dir.mkdir(exist_ok=True)
        for name, text, meta in pairs:
            out = label_dir / f"{name}.csv"
            if out.exists() and not args.force:
                print(f"略過 {out}（已存在，要覆蓋請加 --force）")
                continue
            export_sheet(name, text, meta, out)
            print(f"已產生 {out}")
        return 0

    results, errors = [], []
    for name, text, meta in pairs:
        path = label_dir / f"{name}.csv"
        if not path.exists():
            errors.append(f"{name}：找不到 {path}")
            continue
        labels, turning, errs = read_sheet(name, text, meta, path)
        errors += errs
        results.append((name, meta, labels, turning))
    if errors:
        print("標註表有問題，未寫入任何 JSON：")
        for e in errors:
            print("  - " + e)
        return 1
    for name, meta, labels, turning in results:
        meta["messages"] = labels
        meta["turning_point"] = turning
        path = args.demo_dir / f"{name}.json"
        path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"已寫回 {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
