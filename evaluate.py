"""示範資料評估（SPEC §13）：比較語言模型與規則比對，並統計去識別化成功率。

用法：
    python evaluate.py                 # 有 ANTHROPIC_API_KEY 時兩種方式都跑，否則只跑規則比對
    python evaluate.py --no-llm        # 只跑規則比對（不產生 API 費用）
    python evaluate.py --out report.md

標註檔 demo_data/<name>.json 格式：
{
  "title": "假投資：飆股老師",
  "self_name": "陳美玲",
  "category": "investment" | "normal",
  "is_scam": true,
  "scam_type": "investment" | null,
  "turning_point": 18 | null,
  "pii": [{"type": "phone", "value": "0912-345-678"}, ...],   // 刻意放入的假個資
  "messages": {"1": {"stage": "contact", "tactics": ["authority"]}, ...},
  "source": {"title": "165 全民防騙網…", "url": "https://…", "retrieved": "2026-10-11"}
}
"""
import argparse
import os
import sys
from pathlib import Path

import analyzer
import risk
from deidentify import deidentify
from parser import parse
from seed import DEMO_DIR, load_demo_set
from taxonomy import STAGE_CODES, TACTIC_CODES, TACTIC_NAMES

MIN_CASES, MIN_MSGS, MAX_MSGS = 8, 20, 60


def check_dataset(pairs):
    """檢查資料組成與標註完整性，回傳問題清單（空清單表示通過）。"""
    problems = []
    if len(pairs) < MIN_CASES:
        problems.append(f"示範資料只有 {len(pairs)} 段，至少需要 {MIN_CASES} 段。")
    if sum(1 for _n, _t, m in pairs if not m.get("is_scam")) < 2:
        problems.append("至少需要 2 段正常對話。")
    for name, text, meta in pairs:
        n = len(parse(text, "line_txt").messages)
        if not MIN_MSGS <= n <= MAX_MSGS:
            problems.append(f"{name}：{n} 則訊息，應為 {MIN_MSGS}–{MAX_MSGS} 則。")
        if meta.get("is_scam") and not meta.get("pii"):
            problems.append(f"{name}：詐騙對話沒有放入假個資。")
        labels = meta.get("messages", {})
        missing = [s for s in range(1, n + 1) if str(s) not in labels]
        if missing:
            problems.append(f"{name}：第 {missing[:5]} 等 {len(missing)} 則沒有人工標註。")
        for seq, lab in labels.items():
            if lab.get("stage") not in STAGE_CODES:
                problems.append(f"{name} #{seq}：階段 {lab.get('stage')!r} 不合法。")
            bad = [c for c in lab.get("tactics", []) if c not in TACTIC_CODES]
            if bad:
                problems.append(f"{name} #{seq}：手法 {bad} 不合法。")
        if not meta.get("is_scam") and meta.get("turning_point") is not None:
            problems.append(f"{name}：正常對話的轉折點應為 null。")
    return problems


def prepare(text, meta):
    parsed = parse(text, "line_txt")
    masked, _counts = deidentify(parsed.messages, meta["self_name"])
    return parsed.messages, masked


def deid_success(raw_messages, masked, pii):
    """每個刻意放入的假個資，逐處檢查遮罩後是否還看得到。"""
    raw = "\n".join(m["text"] for m in raw_messages)
    out = "\n".join(m["text"] for m in masked)
    total = leaked = 0
    leaked_types = []
    for item in pii:
        n = raw.count(item["value"])
        left = out.count(item["value"])
        total += n
        leaked += left
        leaked_types += [item["type"]] * left
    return total, leaked, leaked_types


def predicted_turning_point(masked, result):
    scored = [{"seq": m["seq"], "is_self": m["is_self"], **result.messages[m["seq"]]} for m in masked]
    return risk.score_case(scored)[2]


def evaluate_method(name, pairs, run):
    """run(masked) -> AnalysisResult。回傳此方式的各項指標。"""
    correct = 0
    tp = {c: 0 for c in TACTIC_CODES}
    fp = dict(tp)
    fn = dict(tp)
    tp_errors, tp_missed = [], 0
    per_case = []
    for case_name, text, meta in pairs:
        _raw, masked = prepare(text, meta)
        result = run(masked)
        if result.analyzed_by != name:
            raise RuntimeError(f"{case_name}：預期以 {name} 分析，實際為 {result.analyzed_by}（{result.fallback_reason}）")
        ok = result.is_likely_scam == bool(meta["is_scam"])
        correct += ok
        for m in masked:
            if m["is_self"] or m["msg_type"] != "text":
                continue
            gold = set(meta["messages"].get(str(m["seq"]), {}).get("tactics", []))
            pred = {t["code"] for t in result.messages[m["seq"]]["tactics"]}
            for c in TACTIC_CODES:
                tp[c] += c in gold and c in pred
                fp[c] += c not in gold and c in pred
                fn[c] += c in gold and c not in pred
        gold_tp, pred_tp = meta.get("turning_point"), predicted_turning_point(masked, result)
        if gold_tp is not None and pred_tp is not None:
            tp_errors.append(abs(gold_tp - pred_tp))
        elif gold_tp != pred_tp:
            tp_missed += 1
        per_case.append((case_name, meta["is_scam"], result.is_likely_scam, gold_tp, pred_tp))
    tactic_rows = []
    for c in TACTIC_CODES:
        p = tp[c] / (tp[c] + fp[c]) if tp[c] + fp[c] else None
        r = tp[c] / (tp[c] + fn[c]) if tp[c] + fn[c] else None
        tactic_rows.append((c, p, r, tp[c] + fn[c]))
    return {
        "accuracy": correct / len(pairs) if pairs else 0,
        "correct": correct,
        "tactics": tactic_rows,
        "tp_mean_error": sum(tp_errors) / len(tp_errors) if tp_errors else None,
        "tp_compared": len(tp_errors),
        "tp_missed": tp_missed,
        "per_case": per_case,
    }


def fmt(x, pct=True):
    if x is None:
        return "—"
    return f"{x * 100:.0f}%" if pct else f"{x:.1f}"


def render_report(pairs, results, deid, notes):
    total, leaked, leaked_types = deid
    lines = [
        "# 示範資料評估結果（初步測試）",
        "",
        f"樣本：{len(pairs)} 段自編示範對話（{sum(1 for p in pairs if p[2]['is_scam'])} 段詐騙、"
        f"{sum(1 for p in pairs if not p[2]['is_scam'])} 段正常對話）。樣本很小，以下數字只能說明初步可行性，不代表一般化結論。",
        "",
    ]
    lines += [f"> {n}" for n in notes]
    if notes:
        lines.append("")
    methods = list(results)
    labels = {"llm": "語言模型", "rule": "規則比對"}
    lines += ["## 整段判斷與轉折點", "",
              "| 指標 | " + " | ".join(labels[m] for m in methods) + " |",
              "|---|" + "---|" * len(methods)]
    lines.append("| 是否為詐騙的正確率 | " + " | ".join(
        f"{fmt(results[m]['accuracy'])}（{results[m]['correct']}/{len(pairs)}）" for m in methods) + " |")
    lines.append("| 轉折點平均誤差（則） | " + " | ".join(
        f"{fmt(results[m]['tp_mean_error'], pct=False)}（{results[m]['tp_compared']} 段可比較）" for m in methods) + " |")
    lines.append("| 轉折點有無判斷不一致 | " + " | ".join(f"{results[m]['tp_missed']} 段" for m in methods) + " |")
    lines += ["", "## 各手法精確率／召回率", "",
              "| 手法 | 人工標註數 | " + " | ".join(f"{labels[m]} 精確率 | {labels[m]} 召回率" for m in methods) + " |",
              "|---|---|" + "---|---|" * len(methods)]
    for i, code in enumerate(TACTIC_CODES):
        support = results[methods[0]]["tactics"][i][3]
        cells = []
        for m in methods:
            _c, p, r, _s = results[m]["tactics"][i]
            cells += [fmt(p), fmt(r)]
        lines.append(f"| {TACTIC_NAMES[code]} | {support} | " + " | ".join(cells) + " |")
    lines += ["", "## 各段結果", "",
              "| 對話 | 人工：詐騙 | " + " | ".join(f"{labels[m]}：詐騙" for m in methods)
              + " | 人工轉折點 | " + " | ".join(f"{labels[m]}轉折點" for m in methods) + " |",
              "|---|---|" + "---|" * len(methods) + "---|" + "---|" * len(methods)]
    yes = lambda b: "是" if b else "否"
    for idx, (name, _t, meta) in enumerate(pairs):
        row = [name, yes(meta["is_scam"])]
        row += [yes(results[m]["per_case"][idx][2]) for m in methods]
        row += [str(meta.get("turning_point") or "—")]
        row += [str(results[m]["per_case"][idx][4] or "—") for m in methods]
        lines.append("| " + " | ".join(row) + " |")
    rate = (total - leaked) / total if total else None
    lines += ["", "## 去識別化", "",
              f"刻意放入的假個資共 {total} 處，成功遮罩 {total - leaked} 處，成功率 {fmt(rate)}。"]
    if leaked_types:
        lines.append("漏遮類型：" + "、".join(sorted(set(leaked_types))) + "。")
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--demo-dir", default=str(DEMO_DIR))
    ap.add_argument("--out", default="evaluation_report.md")
    ap.add_argument("--no-llm", action="store_true", help="只跑規則比對")
    args = ap.parse_args(argv)

    pairs = load_demo_set(args.demo_dir)
    if not pairs:
        sys.exit(f"{args.demo_dir} 沒有成對的 .txt／.json 示範資料。")
    problems = check_dataset(pairs)
    for p in problems:
        print("⚠", p)

    notes = []
    results = {}
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if api_key and not args.no_llm:
        client = analyzer.make_client(api_key)
        results["llm"] = evaluate_method("llm", pairs, lambda msgs: analyzer.analyze_llm(msgs, client, "claude-opus-5-5"))
    else:
        notes.append("未設定 ANTHROPIC_API_KEY（或指定 --no-llm），語言模型部分未執行。")
    lexicon = analyzer.load_lexicon()
    results["rule"] = evaluate_method("rule", pairs, lambda msgs: analyzer.analyze_rules(msgs, lexicon))
    if problems:
        notes.append(f"資料檢查有 {len(problems)} 項問題，見執行輸出。")

    deid = [0, 0, []]
    for _name, text, meta in pairs:
        raw, masked = prepare(text, meta)
        t, l, types = deid_success(raw, masked, meta.get("pii", []))
        deid[0] += t
        deid[1] += l
        deid[2] += types

    report = render_report(pairs, results, deid, notes)
    Path(args.out).write_text(report, encoding="utf-8")
    print(report)
    print(f"已寫入 {args.out}")
    return results


if __name__ == "__main__":
    main()
