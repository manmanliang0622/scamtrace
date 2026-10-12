"""後台統計查詢（SPEC §12 後台儀表板）。只回傳統計數字，不含任何對話內容。"""
from db import query_all, query_one
from taxonomy import SCAM_TYPE_NAMES, TACTIC_NAMES


def overview():
    row = query_one(
        "SELECT COUNT(*) AS total, SUM(CASE WHEN risk_level = 'high' THEN 1 ELSE 0 END) AS high "
        "FROM cases WHERE status = 'analyzed'"
    )
    total, high = row["total"], row["high"] or 0
    return {"total": total, "high": high, "high_ratio": (high / total) if total else 0.0}


def tactic_frequency():
    rows = query_all(
        "SELECT t.code, COUNT(mt.message_id) AS n FROM tactics t "
        "LEFT JOIN message_tactics mt ON mt.tactic_id = t.id GROUP BY t.id ORDER BY n DESC, t.id"
    )
    return [{"code": r["code"], "name": TACTIC_NAMES.get(r["code"], r["code"]), "count": r["n"]} for r in rows]


def tactic_pairs(limit=10):
    """同一則訊息中同時出現的兩個手法組合。"""
    rows = query_all(
        "SELECT ta.code AS a, tb.code AS b, COUNT(*) AS n FROM message_tactics x "
        "JOIN message_tactics y ON x.message_id = y.message_id AND x.tactic_id < y.tactic_id "
        "JOIN tactics ta ON ta.id = x.tactic_id JOIN tactics tb ON tb.id = y.tactic_id "
        "GROUP BY x.tactic_id, y.tactic_id ORDER BY n DESC, ta.id, tb.id LIMIT ?",
        (limit,),
    )
    return [{"a": TACTIC_NAMES[r["a"]], "b": TACTIC_NAMES[r["b"]], "count": r["n"]} for r in rows]


def scam_type_distribution():
    rows = query_all(
        "SELECT st.code, COUNT(c.id) AS n FROM cases c LEFT JOIN scam_types st ON st.id = c.scam_type_id "
        "WHERE c.status = 'analyzed' GROUP BY st.code ORDER BY n DESC"
    )
    return [{"name": SCAM_TYPE_NAMES.get(r["code"], "非詐騙") if r["code"] else "非詐騙", "count": r["n"]}
            for r in rows]


def avg_turning_point():
    row = query_one(
        "SELECT AVG(turning_point_seq) AS avg, COUNT(turning_point_seq) AS n FROM cases "
        "WHERE status = 'analyzed' AND turning_point_seq IS NOT NULL"
    )
    return {"avg": row["avg"], "count": row["n"]}


def feedback_accuracy():
    row = query_one("SELECT COUNT(*) AS n, SUM(is_correct) AS ok FROM feedback")
    overall = {"count": row["n"], "accuracy": (row["ok"] / row["n"]) if row["n"] else None}
    rows = query_all(
        "SELECT t.code, COUNT(*) AS n, SUM(f.is_correct) AS ok FROM feedback f "
        "JOIN message_tactics mt ON mt.message_id = f.message_id JOIN tactics t ON t.id = mt.tactic_id "
        "GROUP BY t.id ORDER BY t.id"
    )
    per_tactic = [{"name": TACTIC_NAMES[r["code"]], "count": r["n"], "accuracy": r["ok"] / r["n"]} for r in rows]
    return {"overall": overall, "per_tactic": per_tactic}


def analysis_method_counts():
    rows = query_all("SELECT analyzed_by, COUNT(*) AS n FROM cases WHERE status = 'analyzed' GROUP BY analyzed_by")
    counts = {"llm": 0, "rule": 0}
    for r in rows:
        counts[r["analyzed_by"]] = r["n"]
    return counts


def dashboard():
    return {
        "overview": overview(),
        "tactics": tactic_frequency(),
        "pairs": tactic_pairs(),
        "scam_types": scam_type_distribution(),
        "turning_point": avg_turning_point(),
        "feedback": feedback_accuracy(),
        "methods": analysis_method_counts(),
    }
