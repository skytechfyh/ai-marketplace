#!/usr/bin/env python3
"""练习记录与学情跟踪（~/.primary-exam/children/<id>/practice_log.json）。

记录每次练习的成绩，用于薄弱单元分析、间隔复习推荐与进度可视化。

用法:
  # 详细记录（关联试卷 JSON，支持三种口径，可加 --sync-mistakes 同步入错题库）
  python3 practice_log.py record --child 老大 --exam-json exam.json --wrong-nos "2,5" --sync-mistakes
  python3 practice_log.py record --child 老大 --exam-json exam.json --results "1,0,1,1,0" --sync-mistakes
  python3 practice_log.py record --child 老大 --exam-json exam.json --scores "4,0,5,6,2.5" --sync-mistakes

  # 简单记录（只记总分）
  python3 practice_log.py record --child 老大 --subject math --total 100 --score 92.5

  # 查看统计 / 薄弱单元 / 历史记录（均支持 --subject 筛选）
  python3 practice_log.py stats --child 老大 [--subject math]
  python3 practice_log.py weak-points --child 老大 [--subject math] [--threshold 70]
  python3 practice_log.py history --child 老大 [--subject math] --last 7
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mistake_bank import clean_num, grade_exam_items, record_exam_mistakes  # noqa: E402
from profile import exam_home, find_child, load_store  # noqa: E402


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


def calc_streak(dates: list[str], ref_date: date | None = None) -> int:
    """计算截至今天（含昨天未断签）的当前连续打卡天数；断签超过 1 天则归 0。"""
    if not dates:
        return 0
    today = ref_date or date.today()
    past = sorted({date.fromisoformat(d) for d in dates if date.fromisoformat(d) <= today}, reverse=True)
    if not past or (today - past[0]).days > 1:
        return 0
    streak = 1
    for i in range(1, len(past)):
        if (past[i - 1] - past[i]).days == 1:
            streak += 1
        else:
            break
    return streak


def calc_longest_streak(dates: list[str]) -> int:
    """计算历史最长连续打卡天数。"""
    if not dates:
        return 0
    ordered = sorted({date.fromisoformat(d) for d in dates})
    best = cur = 1
    for i in range(1, len(ordered)):
        if (ordered[i] - ordered[i - 1]).days == 1:
            cur += 1
            best = max(best, cur)
        else:
            cur = 1
    return best


def cmd_record(args) -> int:
    c = resolve_child(args.child)
    rec_date = args.date or date.today().isoformat()
    sync_summary = None

    if args.exam_json:
        try:
            exam = json.loads(Path(args.exam_json).read_text(encoding="utf-8"))
        except FileNotFoundError:
            sys.exit(f"文件不存在：{args.exam_json}")
        except json.JSONDecodeError as e:
            sys.exit(f"JSON 解析失败：{args.exam_json}：{e}")

        try:
            graded = grade_exam_items(
                exam,
                scores=args.scores,
                results=args.results,
                wrong_nos=args.wrong_nos,
            )
        except ValueError as e:
            sys.exit(f"错误：{e}")

        total = graded["total"]
        score = graded["score"]
        item_count = graded["item_count"]
        correct_count = graded["correct_count"]
        subject = exam.get("subject", "")
        kind = exam.get("kind", "")
        scope = exam.get("scope", {})
        exam_id = exam.get("exam_id", "")
        item_records = graded["item_records"]
        unit_stats = graded["unit_stats"]

        if args.sync_mistakes:
            sync_summary = record_exam_mistakes(
                c["id"],
                exam,
                graded["wrong_indices"],
                error_type=args.error_type or "",
                ref_date=rec_date,
                source_label=exam_id or Path(args.exam_json).stem,
            )
    else:
        if args.sync_mistakes:
            sys.exit("--sync-mistakes 需要配合 --exam-json 使用")
        if not args.subject or args.total is None or args.score is None:
            sys.exit("简单记录需要 --subject --total --score，或用 --exam-json 配合 --scores/--results/--wrong-nos 详细记录")
        if args.total <= 0 or args.score < 0 or args.score > args.total + 1e-9:
            sys.exit(f"错误：得分 {args.score} / 总分 {args.total} 不合法")
        total = clean_num(args.total)
        score = clean_num(args.score)
        item_count = None
        correct_count = None
        subject = args.subject
        kind = args.kind or ""
        scope = {}
        exam_id = args.exam_id or ""
        item_records = []
        unit_stats = {}

    entry = {
        "date": rec_date,
        "exam_id": exam_id,
        "subject": subject,
        "kind": kind,
        "scope": scope,
        "total": total,
        "score": score,
        "units": unit_stats,
        "items": item_records,
    }
    if item_count is not None:
        entry["item_count"] = item_count
        entry["correct_count"] = correct_count

    log = load_log(c["id"])
    log["entries"].append(entry)
    save_log(c["id"], log)

    rate = f"{score}/{total}（{score / total * 100:.0f}%）" if total else "-"
    extra = f" · 对 {correct_count}/{item_count} 题" if item_count is not None else ""
    print(f"OK: {c['nickname']} {entry['date']} {subject} {rate}{extra}")
    if unit_stats:
        for u, s in sorted(unit_stats.items(), key=lambda x: int(x[0])):
            print(f"  第{u}单元: {s['score']}/{s['total']}")
    if sync_summary is not None:
        print(
            f"MISTAKES: 新增 {sync_summary['added']} 题，合并 {sync_summary['merged']} 题"
            f"（{sync_summary['bank_path']}）"
        )
    return 0


def _filter_entries(entries: list[dict], subject: str | None) -> list[dict]:
    if not subject:
        return entries
    return [e for e in entries if e.get("subject") == subject]


def cmd_stats(args) -> int:
    c = resolve_child(args.child)
    log = load_log(c["id"])
    entries = _filter_entries(log["entries"], args.subject)
    if not entries:
        print(json.dumps({"child": c["nickname"], "total_sessions": 0, "message": "暂无练习记录"}, ensure_ascii=False, indent=2))
        return 0

    dates = [e["date"] for e in entries]
    streak = calc_streak(dates)
    longest = calc_longest_streak(dates)
    total_points = clean_num(sum(e["total"] for e in entries))
    total_score = clean_num(sum(e["score"] for e in entries))
    avg_rate = total_score / total_points * 100 if total_points else 0

    by_subject: dict[str, dict] = {}
    by_subject_unit: dict[str, dict[str, dict]] = {}
    for e in entries:
        s = e.get("subject") or "unknown"
        sb = by_subject.setdefault(s, {"sessions": 0, "total": 0.0, "score": 0.0})
        sb["sessions"] += 1
        sb["total"] += e["total"]
        sb["score"] += e["score"]

        u_map = by_subject_unit.setdefault(s, {})
        for u_key, u_stat in e.get("units", {}).items():
            ub = u_map.setdefault(str(u_key), {"total": 0.0, "score": 0.0})
            ub["total"] += u_stat["total"]
            ub["score"] += u_stat["score"]

    for r in by_subject.values():
        r["total"] = clean_num(r["total"])
        r["score"] = clean_num(r["score"])
        r["avg_rate"] = round(r["score"] / r["total"] * 100, 1) if r["total"] else 0

    sorted_subject_units: dict[str, dict[str, dict]] = {}
    for s in sorted(by_subject_unit):
        if not by_subject_unit[s]:
            continue
        sorted_subject_units[s] = {}
        for u_key in sorted(by_subject_unit[s], key=lambda x: int(x)):
            ub = by_subject_unit[s][u_key]
            ub["total"] = clean_num(ub["total"])
            ub["score"] = clean_num(ub["score"])
            ub["avg_rate"] = round(ub["score"] / ub["total"] * 100, 1) if ub["total"] else 0
            sorted_subject_units[s][u_key] = ub

    result = {
        "child": c["nickname"],
        "subject_filter": args.subject,
        "total_sessions": len(entries),
        "total_points": total_points,
        "total_score": total_score,
        "avg_rate": round(avg_rate, 1),
        "current_streak": streak,
        "longest_streak": longest,
        "practice_days": len(set(dates)),
        "last_practice": max(dates) if dates else None,
        "by_subject": by_subject,
        "by_subject_unit": sorted_subject_units,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_weak_points(args) -> int:
    c = resolve_child(args.child)
    log = load_log(c["id"])
    entries = _filter_entries(log["entries"], args.subject)
    if not entries:
        print(json.dumps({"child": c["nickname"], "message": "暂无练习记录"}, ensure_ascii=False, indent=2))
        return 0

    # 按 (学科, 单元) 聚合，避免跨学科单元号混在一起
    by_subj_unit: dict[str, dict[str, dict]] = {}
    for e in entries:
        subj = e.get("subject") or "unknown"
        for u_key, u_stat in e.get("units", {}).items():
            ub = by_subj_unit.setdefault(subj, {}).setdefault(str(u_key), {"total": 0.0, "score": 0.0})
            ub["total"] += u_stat["total"]
            ub["score"] += u_stat["score"]

    weak = []
    all_units: dict[str, dict[str, dict]] = {}
    for subj in sorted(by_subj_unit):
        all_units[subj] = {}
        for u in sorted(by_subj_unit[subj], key=lambda x: int(x)):
            r = by_subj_unit[subj][u]
            r["total"] = clean_num(r["total"])
            r["score"] = clean_num(r["score"])
            rate = r["score"] / r["total"] * 100 if r["total"] else 0
            r["avg_rate"] = round(rate, 1)
            all_units[subj][u] = r
            if rate < args.threshold:
                weak.append({"subject": subj, "unit": int(u), **r})

    weak.sort(key=lambda x: (x["avg_rate"], x["subject"], x["unit"]))

    result = {
        "child": c["nickname"],
        "subject_filter": args.subject,
        "threshold": f"{args.threshold}%",
        "weak_units": weak,
        "all_units": all_units,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_history(args) -> int:
    c = resolve_child(args.child)
    log = load_log(c["id"])
    entries = _filter_entries(log["entries"], args.subject)
    if not entries:
        print(json.dumps({"child": c["nickname"], "message": "暂无练习记录"}, ensure_ascii=False, indent=2))
        return 0

    if args.last:
        entries = entries[-args.last:]

    result = {
        "child": c["nickname"],
        "subject_filter": args.subject,
        "count": len(entries),
        "entries": [
            {
                "date": e["date"],
                "exam_id": e.get("exam_id", ""),
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
    p_rec.add_argument("--exam-json", type=Path, help="试卷 JSON 路径（详细模式：自动提取单元/分值）")
    p_rec.add_argument("--scores", help="逐题实得分（逗号分隔，支持小数，按各题 points 之和计满分）；需配合 --exam-json")
    p_rec.add_argument("--results", help="逐题对错（逗号分隔，如 '1,0,1,1' 或 '对,错,对,对'）；需配合 --exam-json")
    p_rec.add_argument("--wrong-nos", help="错题题号（逗号分隔，如 '2,5'，全对传 none）；需配合 --exam-json")
    p_rec.add_argument("--sync-mistakes", action="store_true", help="同时把本次错题同步写入孩子错题库")
    p_rec.add_argument("--error-type", default="", help="配合 --sync-mistakes 使用的默认错因")
    p_rec.add_argument("--subject", choices=["math", "chinese", "english"], help="科目（简单模式）")
    p_rec.add_argument("--total", type=float, help="满分或总题数（简单模式）")
    p_rec.add_argument("--score", type=float, help="得分（简单模式）")
    p_rec.add_argument("--kind", help="练习类型")
    p_rec.add_argument("--exam-id", help="试卷 ID")
    p_rec.add_argument("--date", help="记录日期（默认今天，YYYY-MM-DD）")
    p_rec.set_defaults(func=cmd_record)

    p_stats = sub.add_parser("stats", help="查看练习统计")
    p_stats.add_argument("--child", required=True, help="孩子 id/昵称/别名")
    p_stats.add_argument("--subject", choices=["math", "chinese", "english"], help="只统计指定科目")
    p_stats.set_defaults(func=cmd_stats)

    p_weak = sub.add_parser("weak-points", help="查看薄弱单元")
    p_weak.add_argument("--child", required=True, help="孩子 id/昵称/别名")
    p_weak.add_argument("--subject", choices=["math", "chinese", "english"], help="只统计指定科目")
    p_weak.add_argument("--threshold", type=int, default=70, help="正确率阈值（%，默认 70）")
    p_weak.set_defaults(func=cmd_weak_points)

    p_hist = sub.add_parser("history", help="查看历史记录")
    p_hist.add_argument("--child", required=True, help="孩子 id/昵称/别名")
    p_hist.add_argument("--subject", choices=["math", "chinese", "english"], help="只查看指定科目")
    p_hist.add_argument("--last", type=int, help="只显示最近 N 条")
    p_hist.set_defaults(func=cmd_history)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
