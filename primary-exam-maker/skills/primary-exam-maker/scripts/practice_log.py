#!/usr/bin/env python3
"""练习记录与学情跟踪（~/.primary-exam/children/<id>/practice_log.json）。

记录每次练习的成绩，用于间隔复习推荐与进度可视化。

用法:
  # 详细记录（关联试卷 JSON，自动提取单元/题型）
  python3 practice_log.py record --child 老大 --exam-json daily.json --scores "1,0,1,1,1,1,1,0,1,1"

  # 简单记录（只记总分）
  python3 practice_log.py record --child 老大 --subject math --total 10 --score 8

  # 查看统计
  python3 practice_log.py stats --child 老大

  # 查看薄弱单元
  python3 practice_log.py weak-points --child 老大

  # 查看历史记录
  python3 practice_log.py history --child 老大 --last 7
"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from profile import exam_home, load_store, find_child  # noqa: E402


def log_path(child_id: str) -> Path:
    return exam_home() / "children" / child_id / "practice_log.json"


def load_log(child_id: str) -> dict:
    p = log_path(child_id)
    if not p.exists():
        return {"schema": 1, "entries": []}
    return json.loads(p.read_text(encoding="utf-8"))


def save_log(child_id: str, data: dict) -> None:
    p = log_path(child_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def resolve_child(query: str) -> dict:
    data = load_store()
    c = find_child(data, query)
    if not c:
        sys.exit(f"未找到孩子档案：{query}（用 profile.py list 查看已建档孩子）")
    return c


def calc_streak(dates: list[str]) -> int:
    """计算从最近记录开始的连续打卡天数。"""
    if not dates:
        return 0
    unique = sorted(set(dates), reverse=True)
    streak = 1
    for i in range(1, len(unique)):
        prev = date.fromisoformat(unique[i - 1])
        curr = date.fromisoformat(unique[i])
        if (prev - curr).days == 1:
            streak += 1
        else:
            break
    return streak


def cmd_record(args) -> int:
    c = resolve_child(args.child)

    if args.exam_json:
        # 详细模式：从试卷 JSON 提取元数据
        try:
            exam = json.loads(Path(args.exam_json).read_text(encoding="utf-8"))
        except FileNotFoundError:
            sys.exit(f"文件不存在：{args.exam_json}")
        except json.JSONDecodeError as e:
            sys.exit(f"JSON 解析失败：{args.exam_json}：{e}")

        if not args.scores:
            sys.exit("详细记录需要 --scores（逗号分隔的逐题得分，如 '1,0,1,1'）")

        scores = [int(s.strip()) for s in args.scores.split(",")]
        items = []
        for sec in exam.get("sections", []):
            items.extend(sec.get("items", []))
        if len(scores) != len(items):
            sys.exit(f"scores 数量 {len(scores)} 与试卷题目数 {len(items)} 不一致")

        total = len(items)
        score = sum(scores)
        subject = exam.get("subject", "")
        kind = exam.get("kind", "")
        scope = exam.get("scope", {})
        exam_id = exam.get("exam_id", "")

        item_records = []
        for i, (item, earned) in enumerate(zip(items, scores)):
            pts = item.get("points", 1)
            item_records.append({
                "no": item.get("no", i + 1),
                "unit": item.get("unit"),
                "points": pts,
                "earned": earned,
                "correct": earned >= pts,
            })

        # 按单元聚合
        unit_stats: dict[str, dict] = {}
        for ir in item_records:
            u = ir["unit"]
            if u is None:
                continue
            key = str(u)
            if key not in unit_stats:
                unit_stats[key] = {"total": 0, "score": 0}
            unit_stats[key]["total"] += 1
            unit_stats[key]["score"] += ir["earned"]
    else:
        # 简单模式：只记总分
        if not args.subject or args.total is None or args.score is None:
            sys.exit("简单记录需要 --subject --total --score，或用 --exam-json --scores 详细记录")
        total = args.total
        score = args.score
        subject = args.subject
        kind = args.kind or ""
        scope = {}
        exam_id = args.exam_id or ""
        item_records = []
        unit_stats = {}

    entry = {
        "date": args.date or date.today().isoformat(),
        "exam_id": exam_id,
        "subject": subject,
        "kind": kind,
        "scope": scope,
        "total": total,
        "score": score,
        "units": unit_stats,
        "items": item_records,
    }

    log = load_log(c["id"])
    log["entries"].append(entry)
    save_log(c["id"], log)

    rate = f"{score}/{total}（{score / total * 100:.0f}%）" if total else "-"
    print(f"OK: {c['nickname']} {entry['date']} {subject} {rate}")
    if unit_stats:
        for u, s in sorted(unit_stats.items()):
            print(f"  第{u}单元: {s['score']}/{s['total']}")
    return 0


def cmd_stats(args) -> int:
    c = resolve_child(args.child)
    log = load_log(c["id"])
    entries = log["entries"]
    if not entries:
        print(json.dumps({"child": c["nickname"], "total_sessions": 0, "message": "暂无练习记录"}, ensure_ascii=False, indent=2))
        return 0

    dates = [e["date"] for e in entries]
    streak = calc_streak(dates)
    total_items = sum(e["total"] for e in entries)
    total_score = sum(e["score"] for e in entries)
    avg_rate = total_score / total_items * 100 if total_items else 0

    # 按科目统计
    by_subject: dict[str, dict] = {}
    for e in entries:
        s = e["subject"]
        if s not in by_subject:
            by_subject[s] = {"sessions": 0, "items": 0, "score": 0}
        by_subject[s]["sessions"] += 1
        by_subject[s]["items"] += e["total"]
        by_subject[s]["score"] += e["score"]

    for s in by_subject:
        r = by_subject[s]
        r["avg_rate"] = round(r["score"] / r["items"] * 100, 1) if r["items"] else 0

    # 按单元统计
    by_unit: dict[str, dict] = {}
    for e in entries:
        for u_key, u_stat in e.get("units", {}).items():
            if u_key not in by_unit:
                by_unit[u_key] = {"total": 0, "score": 0}
            by_unit[u_key]["total"] += u_stat["total"]
            by_unit[u_key]["score"] += u_stat["score"]

    for u in by_unit:
        r = by_unit[u]
        r["avg_rate"] = round(r["score"] / r["total"] * 100, 1) if r["total"] else 0

    result = {
        "child": c["nickname"],
        "total_sessions": len(entries),
        "total_items": total_items,
        "total_score": total_score,
        "avg_rate": round(avg_rate, 1),
        "current_streak": streak,
        "practice_days": len(set(dates)),
        "last_practice": max(dates) if dates else None,
        "by_subject": by_subject,
        "by_unit": dict(sorted(by_unit.items(), key=lambda x: int(x[0]))),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_weak_points(args) -> int:
    c = resolve_child(args.child)
    log = load_log(c["id"])
    entries = log["entries"]
    if not entries:
        print(json.dumps({"child": c["nickname"], "message": "暂无练习记录"}, ensure_ascii=False, indent=2))
        return 0

    # 按单元聚合正确率
    by_unit: dict[str, dict] = {}
    for e in entries:
        for u_key, u_stat in e.get("units", {}).items():
            if u_key not in by_unit:
                by_unit[u_key] = {"total": 0, "score": 0}
            by_unit[u_key]["total"] += u_stat["total"]
            by_unit[u_key]["score"] += u_stat["score"]

    weak = []
    for u, r in by_unit.items():
        rate = r["score"] / r["total"] * 100 if r["total"] else 0
        r["avg_rate"] = round(rate, 1)
        if rate < args.threshold:
            weak.append({"unit": int(u), **r})

    weak.sort(key=lambda x: x["avg_rate"])

    result = {
        "child": c["nickname"],
        "threshold": f"{args.threshold}%",
        "weak_units": weak,
        "all_units": dict(sorted(by_unit.items(), key=lambda x: int(x[0]))),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_history(args) -> int:
    c = resolve_child(args.child)
    log = load_log(c["id"])
    entries = log["entries"]
    if not entries:
        print(json.dumps({"child": c["nickname"], "message": "暂无练习记录"}, ensure_ascii=False, indent=2))
        return 0

    if args.last:
        entries = entries[-args.last:]

    result = {
        "child": c["nickname"],
        "count": len(entries),
        "entries": [
            {
                "date": e["date"],
                "subject": e["subject"],
                "kind": e["kind"],
                "score": e["score"],
                "total": e["total"],
                "rate": round(e["score"] / e["total"] * 100, 1) if e["total"] else 0,
            }
            for e in entries
        ],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_rec = sub.add_parser("record", help="记录一次练习成绩")
    p_rec.add_argument("--child", required=True, help="孩子 id/昵称/别名")
    p_rec.add_argument("--exam-json", type=Path, help="试卷 JSON 路径（详细模式：自动提取单元/题型）")
    p_rec.add_argument("--scores", help="逐题得分（逗号分隔，如 '1,0,1,1'）；需配合 --exam-json")
    p_rec.add_argument("--subject", help="科目（简单模式）")
    p_rec.add_argument("--total", type=int, help="题目总数（简单模式）")
    p_rec.add_argument("--score", type=int, help="得分（简单模式）")
    p_rec.add_argument("--kind", help="练习类型")
    p_rec.add_argument("--exam-id", help="试卷 ID")
    p_rec.add_argument("--date", help="记录日期（默认今天，YYYY-MM-DD）")
    p_rec.set_defaults(func=cmd_record)

    p_stats = sub.add_parser("stats", help="查看练习统计")
    p_stats.add_argument("--child", required=True, help="孩子 id/昵称/别名")
    p_stats.set_defaults(func=cmd_stats)

    p_weak = sub.add_parser("weak-points", help="查看薄弱单元")
    p_weak.add_argument("--child", required=True, help="孩子 id/昵称/别名")
    p_weak.add_argument("--threshold", type=int, default=70, help="正确率阈值（%，默认 70）")
    p_weak.set_defaults(func=cmd_weak_points)

    p_hist = sub.add_parser("history", help="查看历史记录")
    p_hist.add_argument("--child", required=True, help="孩子 id/昵称/别名")
    p_hist.add_argument("--last", type=int, help="只显示最近 N 条")
    p_hist.set_defaults(func=cmd_history)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
