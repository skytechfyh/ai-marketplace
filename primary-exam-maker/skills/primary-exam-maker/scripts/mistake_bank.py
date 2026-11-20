#!/usr/bin/env python3
"""孩子错题库管理（~/.primary-exam/children/<id>/mistakes.json）。

无论在哪个工作目录下调用，所有错题记录均按孩子隔离保存在统一目录
`~/.primary-exam/children/<id>/mistakes.json`（可通过 PRIMARY_EXAM_HOME 覆盖）。
支持同题自动去重计数、3/7/14/30 天间隔复习调度、从试卷 JSON 批量导入、
以及导出可打印的 PDF 错题本。

用法:
  # 添加单道错题（同题自动合并计数）
  python3 mistake_bank.py add --child 老大 --subject math --grade 2 --term up --unit 3 \\
    --stem "23 + 49 = ?" --wrong-answer "62" --correct-answer "72" --error-type "进位错"

  # 从试卷 JSON 批量导入错题（支持按实得分 / 按对错 / 按错题题号三种口径）
  python3 mistake_bank.py add-from-exam --child 老大 --exam-json exam.json --wrong-nos "2,5"
  python3 mistake_bank.py add-from-exam --child 老大 --exam-json exam.json --results "1,0,1,1,0"
  python3 mistake_bank.py add-from-exam --child 老大 --exam-json exam.json --scores "4,0,5,6,2.5"

  # 查看某孩子全部未掌握错题 / 今日到期复习错题
  python3 mistake_bank.py list --child 老大
  python3 mistake_bank.py due --child 老大 --subject math

  # 标记复习结果（通过则推进 3/7/14/30 天间隔；未通过则重置为 3 天后再练）
  python3 mistake_bank.py review --child 老大 --ids m_001 --passed

  # 错题统计 & 导出可打印错题本（默认直接生成 PDF 到 reports/）
  python3 mistake_bank.py stats --child 老大
  python3 mistake_bank.py export --child 老大
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import render_pdf  # noqa: E402
from profile import exam_home, find_child, load_store  # noqa: E402

REVIEW_INTERVALS = (3, 7, 14, 30)
SUBJECT_LABELS = {"math": "数学", "chinese": "语文", "english": "英语"}
_TRUTHY_RESULTS = {"1", "t", "true", "y", "yes", "对", "✓", "√"}
_FALSY_RESULTS = {"0", "f", "false", "n", "no", "错", "✗", "×"}


def clean_num(value: float) -> int | float:
    """将整值浮点转为 int，小数保留最多 2 位，便于 JSON 与展示清洁。"""
    rounded = round(float(value), 2)
    if abs(rounded - round(rounded)) < 1e-9:
        return int(round(rounded))
    return rounded


def mistakes_path(child_id: str) -> Path:
    return exam_home() / "children" / child_id / "mistakes.json"


def default_export_path(
    child_id: str,
    *,
    md_only: bool = False,
    subject: str | None = None,
) -> Path:
    subj_prefix = f"{SUBJECT_LABELS.get(subject, subject)}_" if subject else ""
    ext = "md" if md_only else "pdf"
    return exam_home() / "children" / child_id / "reports" / f"{date.today():%Y%m%d}_{subj_prefix}错题本.{ext}"


def load_bank(child_id: str) -> dict:
    p = mistakes_path(child_id)
    if not p.exists():
        return {"schema": 1, "mistakes": []}
    return json.loads(p.read_text(encoding="utf-8"))


def save_bank(child_id: str, data: dict) -> None:
    p = mistakes_path(child_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def resolve_child(query: str) -> dict:
    data = load_store()
    c = find_child(data, query)
    if not c:
        sys.exit(f"未找到孩子档案：{query}（请先用 profile.py list 查看或 profile.py add 建档）")
    return c


def normalize_stem(stem: str) -> str:
    return re.sub(r"\s+", " ", stem.strip()).lower()


def make_fingerprint(subject: str, stem: str) -> str:
    key = f"{subject.strip().lower()}:{normalize_stem(stem)}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


def next_mistake_id(mistakes: list[dict]) -> str:
    max_num = 0
    for m in mistakes:
        mid = m.get("id", "")
        if mid.startswith("m_") and mid[2:].isdigit():
            max_num = max(max_num, int(mid[2:]))
    return f"m_{max_num + 1:03d}"


def add_days(iso_date: str, days: int) -> str:
    return (date.fromisoformat(iso_date) + timedelta(days=days)).isoformat()


def upsert_mistake(
    bank: dict,
    *,
    subject: str,
    stem: str,
    wrong_answer: str = "",
    correct_answer: str = "",
    error_type: str = "",
    knowledge_points: list[str] | None = None,
    grade: int | None = None,
    term: str | None = None,
    unit: int | None = None,
    source: str = "",
    notes: str = "",
    ref_date: str | None = None,
) -> tuple[dict, bool]:
    """插入或合并同题错题，返回 (record, is_new)。"""
    today = ref_date or date.today().isoformat()
    fp = make_fingerprint(subject, stem)
    kps = [k.strip() for k in (knowledge_points or []) if k and k.strip()]

    for m in bank["mistakes"]:
        if m.get("fingerprint") == fp:
            m["count"] = m.get("count", 1) + 1
            dates = m.setdefault("dates", [])
            if today not in dates:
                dates.append(today)
                dates.sort()
            m["last_wrong"] = max(dates)
            if wrong_answer:
                m["wrong_answer"] = wrong_answer
            if correct_answer and not m.get("correct_answer"):
                m["correct_answer"] = correct_answer
            if error_type:
                m["error_type"] = error_type
            if kps:
                existing_kps = m.setdefault("knowledge_points", [])
                for k in kps:
                    if k not in existing_kps:
                        existing_kps.append(k)
            if notes:
                m["notes"] = notes
            # 再次做错则重置间隔复习阶段
            m["mastered"] = False
            m["mastered_date"] = None
            m["review_stage"] = 0
            m["next_review"] = add_days(today, REVIEW_INTERVALS[0])
            return m, False

    record = {
        "id": next_mistake_id(bank["mistakes"]),
        "fingerprint": fp,
        "subject": subject,
        "grade": grade,
        "term": term,
        "unit": unit,
        "stem": stem.strip(),
        "wrong_answer": wrong_answer.strip(),
        "correct_answer": correct_answer.strip(),
        "error_type": error_type.strip(),
        "knowledge_points": kps,
        "source": source.strip(),
        "count": 1,
        "dates": [today],
        "last_wrong": today,
        "review_stage": 0,
        "next_review": add_days(today, REVIEW_INTERVALS[0]),
        "mastered": False,
        "mastered_date": None,
        "notes": notes.strip(),
    }
    bank["mistakes"].append(record)
    return record, True


def cmd_add(args) -> int:
    c = resolve_child(args.child)
    bank = load_bank(c["id"])
    kps = [k.strip() for k in args.kp.split(",") if k.strip()] if args.kp else []
    rec, is_new = upsert_mistake(
        bank,
        subject=args.subject,
        stem=args.stem,
        wrong_answer=args.wrong_answer or "",
        correct_answer=args.correct_answer or "",
        error_type=args.error_type or "",
        knowledge_points=kps,
        grade=args.grade,
        term=args.term,
        unit=args.unit,
        source=args.source or "",
        notes=args.notes or "",
        ref_date=args.date,
    )
    save_bank(c["id"], bank)
    print(json.dumps({
        "child": c["nickname"],
        "bank_path": str(mistakes_path(c["id"])),
        "action": "added" if is_new else "merged",
        "mistake": rec,
    }, ensure_ascii=False, indent=2))
    return 0


def grade_exam_items(
    exam: dict,
    *,
    scores: str | None = None,
    results: str | None = None,
    wrong_nos: str | None = None,
) -> dict:
    """按统一口径解析试卷逐题判分结果，支持三种互斥输入：

    - scores: 逐题实得分（支持小数，按各题 points 之和作为满分）
    - results: 逐题对/错（1/0、对/错、T/F、Y/N），对记满分、错记 0 分
    - wrong_nos: 错题题号（如 '2,5'，全对可传 '' 或 'none'），未列题号记满分
    """
    items: list[dict] = []
    for sec in exam.get("sections", []):
        items.extend(sec.get("items", []))
    if not items:
        raise ValueError("试卷 JSON 中未找到题目")

    provided = sum(x is not None for x in (scores, results, wrong_nos))
    if provided != 1:
        raise ValueError("请且仅请提供一种判分参数：--scores（实得分）、--results（对错 1/0）或 --wrong-nos（错题题号）")

    earned_list: list[float] = []
    correct_list: list[bool] = []
    pts_list: list[float] = [float(item.get("points", 1)) for item in items]

    if scores is not None:
        raw_tokens = [s.strip() for s in scores.split(",") if s.strip() != ""]
        if len(raw_tokens) != len(items):
            raise ValueError(f"scores 数量 {len(raw_tokens)} 与试卷题目数 {len(items)} 不一致")
        try:
            parsed_scores = [float(t) for t in raw_tokens]
        except ValueError as e:
            raise ValueError(f"--scores 包含非法数字：{e}") from None
        # 若全卷每题分值 > 1 但全部输入都是 0/1 且含 1，提示可能误用对错口径
        if all(p > 1 for p in pts_list) and all(v in (0.0, 1.0) for v in parsed_scores) and any(v == 1.0 for v in parsed_scores):
            print(
                "WARN: 本卷每题分值均 > 1，--scores 按「实得分」计分；若输入的是对/错（1/0），请改用 --results 或 --wrong-nos",
                file=sys.stderr,
            )
        for idx, (pts, earned) in enumerate(zip(pts_list, parsed_scores), 1):
            if earned < 0 or earned > pts + 1e-9:
                raise ValueError(f"第 {idx} 题得分 {clean_num(earned)} 超出合法范围 [0, {clean_num(pts)}]")
            earned_list.append(earned)
            correct_list.append(earned >= pts - 1e-9)

    elif results is not None:
        raw_tokens = [s.strip().lower() for s in results.split(",") if s.strip() != ""]
        if len(raw_tokens) != len(items):
            raise ValueError(f"results 数量 {len(raw_tokens)} 与试卷题目数 {len(items)} 不一致")
        for idx, (pts, tok) in enumerate(zip(pts_list, raw_tokens), 1):
            if tok in _TRUTHY_RESULTS:
                earned_list.append(pts)
                correct_list.append(True)
            elif tok in _FALSY_RESULTS:
                earned_list.append(0.0)
                correct_list.append(False)
            else:
                raise ValueError(f"--results 第 {idx} 项无法识别：{tok!r}（支持 1/0、对/错、T/F、Y/N）")

    else:
        assert wrong_nos is not None
        spec = wrong_nos.strip()
        if not spec or spec.lower() in ("none", "无"):
            nos: set[str] = set()
        else:
            nos = {s.strip() for s in spec.split(",") if s.strip()}
        valid_nos = {str(item.get("no", i + 1)) for i, item in enumerate(items)}
        unknown = sorted(nos - valid_nos)
        if unknown:
            raise ValueError(f"--wrong-nos 包含试卷中不存在的题号：{','.join(unknown)}")
        for i, (item, pts) in enumerate(zip(items, pts_list)):
            qno = str(item.get("no", i + 1))
            if qno in nos:
                earned_list.append(0.0)
                correct_list.append(False)
            else:
                earned_list.append(pts)
                correct_list.append(True)

    item_records: list[dict] = []
    wrong_indices: list[int] = []
    unit_stats: dict[str, dict] = {}
    for i, (item, pts, earned, ok) in enumerate(zip(items, pts_list, earned_list, correct_list)):
        item_records.append({
            "no": item.get("no", i + 1),
            "unit": item.get("unit"),
            "points": clean_num(pts),
            "earned": clean_num(earned),
            "correct": ok,
        })
        if not ok:
            wrong_indices.append(i)
        u = item.get("unit")
        if u is not None:
            key = str(u)
            bucket = unit_stats.setdefault(key, {"total": 0.0, "score": 0.0})
            bucket["total"] += pts
            bucket["score"] += earned

    for bucket in unit_stats.values():
        bucket["total"] = clean_num(bucket["total"])
        bucket["score"] = clean_num(bucket["score"])

    return {
        "items": items,
        "item_records": item_records,
        "wrong_indices": wrong_indices,
        "total": clean_num(sum(pts_list)),
        "score": clean_num(sum(earned_list)),
        "item_count": len(items),
        "correct_count": sum(1 for ok in correct_list if ok),
        "unit_stats": unit_stats,
    }


def record_exam_mistakes(
    child_id: str,
    exam: dict,
    wrong_indices: list[int],
    *,
    error_type: str = "",
    ref_date: str | None = None,
    source_label: str | None = None,
) -> dict:
    """将试卷中指定索引的错题批量写入孩子错题库，返回汇总字典。"""
    items: list[dict] = []
    for sec in exam.get("sections", []):
        items.extend(sec.get("items", []))
    scope = exam.get("scope", {})
    subject = exam.get("subject", "")
    grade = scope.get("grade")
    term = scope.get("term")
    exam_id = source_label or exam.get("exam_id", "")
    today = ref_date or date.today().isoformat()

    bank = load_bank(child_id)
    added = 0
    merged = 0
    recorded: list[dict] = []
    for idx in wrong_indices:
        item = items[idx]
        sm = item.get("source_mistake") or {}
        stem = sm.get("original") or item.get("stem", "")
        err_type = sm.get("error_type") or error_type or ""
        ans = item.get("answer", "")
        if isinstance(ans, (list, dict)):
            ans = json.dumps(ans, ensure_ascii=False)
        qno = item.get("no", idx + 1)
        src = f"{exam_id} 第{qno}题" if exam_id else f"第{qno}题"
        rec, is_new = upsert_mistake(
            bank,
            subject=subject,
            stem=stem,
            correct_answer=str(ans),
            error_type=err_type,
            knowledge_points=item.get("knowledge_points", []),
            grade=grade,
            term=term,
            unit=item.get("unit"),
            source=src,
            ref_date=today,
        )
        if is_new:
            added += 1
        else:
            merged += 1
        recorded.append(rec)

    if wrong_indices:
        save_bank(child_id, bank)
    return {
        "bank_path": str(mistakes_path(child_id)),
        "added": added,
        "merged": merged,
        "mistakes": recorded,
    }


def cmd_add_from_exam(args) -> int:
    c = resolve_child(args.child)
    exam_file = Path(args.exam_json)
    if not exam_file.exists():
        sys.exit(f"文件不存在：{args.exam_json}")
    exam = json.loads(exam_file.read_text(encoding="utf-8"))

    try:
        graded = grade_exam_items(
            exam,
            scores=args.scores,
            results=args.results,
            wrong_nos=args.wrong_nos,
        )
    except ValueError as e:
        sys.exit(f"错误：{e}")

    summary = record_exam_mistakes(
        c["id"],
        exam,
        graded["wrong_indices"],
        error_type=args.error_type or "",
        ref_date=args.date,
        source_label=exam.get("exam_id") or exam_file.stem,
    )
    print(json.dumps({
        "child": c["nickname"],
        **summary,
    }, ensure_ascii=False, indent=2))
    return 0


def filter_mistakes(
    mistakes: list[dict],
    *,
    subject: str | None = None,
    unit: int | None = None,
    due_only: bool = False,
    include_mastered: bool = False,
    ref_date: str | None = None,
) -> list[dict]:
    today = ref_date or date.today().isoformat()
    out = []
    for m in mistakes:
        if not include_mastered and m.get("mastered"):
            continue
        if subject and m.get("subject") != subject:
            continue
        if unit is not None and m.get("unit") != unit:
            continue
        if due_only:
            nr = m.get("next_review")
            if m.get("mastered") or not nr or nr > today:
                continue
        out.append(m)
    out.sort(key=lambda x: (x.get("next_review") or "9999-99-99", -x.get("count", 1), x.get("id", "")))
    return out


def cmd_list(args) -> int:
    c = resolve_child(args.child)
    bank = load_bank(c["id"])
    rows = filter_mistakes(
        bank["mistakes"],
        subject=args.subject,
        unit=args.unit,
        due_only=args.due,
        include_mastered=args.all,
        ref_date=args.date,
    )
    print(json.dumps({
        "child": c["nickname"],
        "bank_path": str(mistakes_path(c["id"])),
        "count": len(rows),
        "mistakes": rows,
    }, ensure_ascii=False, indent=2))
    return 0


def cmd_due(args) -> int:
    c = resolve_child(args.child)
    bank = load_bank(c["id"])
    rows = filter_mistakes(
        bank["mistakes"],
        subject=args.subject,
        due_only=True,
        include_mastered=False,
        ref_date=args.date,
    )
    if args.limit and args.limit > 0:
        rows = rows[:args.limit]
    print(json.dumps({
        "child": c["nickname"],
        "as_of": args.date or date.today().isoformat(),
        "due_count": len(rows),
        "mistakes": rows,
    }, ensure_ascii=False, indent=2))
    return 0


def cmd_review(args) -> int:
    c = resolve_child(args.child)
    bank = load_bank(c["id"])
    today = args.date or date.today().isoformat()
    target_ids = {s.strip() for s in args.ids.split(",") if s.strip()}
    updated = []
    for m in bank["mistakes"]:
        if m.get("id") not in target_ids:
            continue
        if args.passed:
            stage = m.get("review_stage", 0) + 1
            m["review_stage"] = stage
            if stage >= len(REVIEW_INTERVALS):
                m["mastered"] = True
                m["mastered_date"] = today
                m["next_review"] = None
            else:
                m["mastered"] = False
                m["next_review"] = add_days(today, REVIEW_INTERVALS[stage])
        else:
            m["count"] = m.get("count", 1) + 1
            dates = m.setdefault("dates", [])
            if today not in dates:
                dates.append(today)
                dates.sort()
            m["last_wrong"] = max(dates)
            m["review_stage"] = 0
            m["mastered"] = False
            m["mastered_date"] = None
            m["next_review"] = add_days(today, REVIEW_INTERVALS[0])
        updated.append(m)

    if not updated:
        sys.exit(f"未找到错题 ID：{args.ids}")
    save_bank(c["id"], bank)
    print(json.dumps({
        "child": c["nickname"],
        "updated": updated,
    }, ensure_ascii=False, indent=2))
    return 0


def cmd_stats(args) -> int:
    c = resolve_child(args.child)
    bank = load_bank(c["id"])
    mistakes = bank["mistakes"]
    today = args.date or date.today().isoformat()

    active = [m for m in mistakes if not m.get("mastered")]
    mastered = [m for m in mistakes if m.get("mastered")]
    due = [m for m in active if m.get("next_review") and m["next_review"] <= today]

    by_subject: dict[str, dict] = {}
    by_error_type: dict[str, int] = {}
    by_kp: dict[str, int] = {}
    for m in mistakes:
        s = m.get("subject", "unknown")
        bucket = by_subject.setdefault(s, {"total": 0, "active": 0, "mastered": 0})
        bucket["total"] += 1
        bucket["mastered" if m.get("mastered") else "active"] += 1
        et = m.get("error_type") or "未分类"
        by_error_type[et] = by_error_type.get(et, 0) + m.get("count", 1)
        for kp in m.get("knowledge_points", []):
            by_kp[kp] = by_kp.get(kp, 0) + m.get("count", 1)

    top_repeated = sorted(active, key=lambda x: (-x.get("count", 1), x.get("id", "")))[:5]
    print(json.dumps({
        "child": c["nickname"],
        "bank_path": str(mistakes_path(c["id"])),
        "total": len(mistakes),
        "active": len(active),
        "mastered": len(mastered),
        "due_today": len(due),
        "by_subject": by_subject,
        "by_error_type": dict(sorted(by_error_type.items(), key=lambda kv: -kv[1])),
        "by_kp": dict(sorted(by_kp.items(), key=lambda kv: -kv[1])),
        "top_repeated": [{"id": m["id"], "subject": m["subject"], "stem": m["stem"], "count": m["count"]} for m in top_repeated],
    }, ensure_ascii=False, indent=2))
    return 0


def cmd_export(args) -> int:
    c = resolve_child(args.child)
    bank = load_bank(c["id"])
    rows = filter_mistakes(
        bank["mistakes"],
        subject=args.subject,
        unit=args.unit,
        due_only=False,
        include_mastered=args.all,
    )

    # 决定输出格式：默认直接出 PDF；显式 --md-only 或 -o 指定 .md 时只出 MD
    if args.output:
        out_path = Path(args.output)
        md_only = args.md_only or (out_path.suffix.lower() == ".md" and not args.keep_md)
    else:
        md_only = args.md_only
        out_path = default_export_path(c["id"], md_only=md_only, subject=args.subject)

    lines = [
        f"# {c['nickname']}的错题本",
        "",
        f"> 更新日期：{date.today().isoformat()} ｜ 共 {len(rows)} 道错题",
        "",
    ]
    if not rows:
        lines.append("暂无符合条件的错题记录。")
    else:
        by_subj: dict[str, list[dict]] = {}
        for m in rows:
            by_subj.setdefault(m.get("subject", "other"), []).append(m)
        for subj, items in by_subj.items():
            label = SUBJECT_LABELS.get(subj, subj)
            lines.append(f"## {label}（{len(items)} 题）")
            lines.append("")
            for m in items:
                unit_tag = f"第{m['unit']}单元" if m.get("unit") is not None else "未分单元"
                status = "已掌握" if m.get("mastered") else f"待复习（下次 {m.get('next_review') or '-'}）"
                lines.append(f"### [{m['id']}] {m['stem']}")
                lines.append(f"- **状态**：{status} ｜ **错次**：{m.get('count', 1)} ｜ **单元**：{unit_tag}")
                if m.get("wrong_answer") or m.get("correct_answer"):
                    lines.append(f"- **错答**：{m.get('wrong_answer') or '（未记）'} ｜ **正解**：{m.get('correct_answer') or '（未记）'}")
                if m.get("error_type"):
                    lines.append(f"- **错因**：{m['error_type']}")
                if m.get("knowledge_points"):
                    lines.append(f"- **知识点**：{', '.join(m['knowledge_points'])}")
                if m.get("notes"):
                    lines.append(f"- **备注**：{m['notes']}")
                lines.append("")

    md_text = "\n".join(lines).rstrip() + "\n"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if md_only:
        out_path.write_text(md_text, encoding="utf-8")
        print(f"OK: 已导出 {len(rows)} 道错题到 {out_path}")
        return 0

    pdf_path = out_path if out_path.suffix.lower() == ".pdf" else out_path.with_suffix(".pdf")
    if args.keep_md:
        md_path = pdf_path.with_suffix(".md")
        md_path.write_text(md_text, encoding="utf-8")
    try:
        render_pdf.render_md_text_to_pdf(md_text, pdf_path, chrome=args.chrome)
    except (ValueError, RuntimeError) as e:
        sys.exit(f"错误：{e}")
    print(f"OK: 已导出 {len(rows)} 道错题到 {pdf_path}")
    if args.keep_md:
        print(f"MD: {pdf_path.with_suffix('.md')}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="孩子错题库管理（~/.primary-exam/children/<id>/mistakes.json）")
    sub = p.add_subparsers(dest="cmd", required=True)

    pa = sub.add_parser("add", help="添加单道错题（同题自动合并计数）")
    pa.add_argument("--child", required=True, help="孩子 id、昵称或别名")
    pa.add_argument("--subject", required=True, choices=["math", "chinese", "english"])
    pa.add_argument("--stem", required=True, help="原题题干")
    pa.add_argument("--wrong-answer", default="")
    pa.add_argument("--correct-answer", default="")
    pa.add_argument("--error-type", default="", help="错因，如 进位错/审题不清/错别字/拼写错")
    pa.add_argument("--kp", default="", help="知识点 ID，逗号分隔")
    pa.add_argument("--grade", type=int, default=None)
    pa.add_argument("--term", choices=["up", "down"], default=None)
    pa.add_argument("--unit", type=int, default=None)
    pa.add_argument("--source", default="", help="来源，如 作业照片/单元卷")
    pa.add_argument("--notes", default="")
    pa.add_argument("--date", default=None, help="日期 YYYY-MM-DD（默认今天）")
    pa.set_defaults(func=cmd_add)

    pe = sub.add_parser("add-from-exam", help="从试卷 JSON 批量导入错题")
    pe.add_argument("--child", required=True)
    pe.add_argument("--exam-json", required=True)
    pe.add_argument("--scores", default=None, help="逗号分隔的逐题实得分（支持小数），低于该题满分即入库")
    pe.add_argument("--results", default=None, help="逗号分隔的逐题对错（1/0、对/错、T/F），错题入库")
    pe.add_argument("--wrong-nos", default=None, help="逗号分隔的错题题号，如 2,5（全对可传 none）")
    pe.add_argument("--error-type", default="")
    pe.add_argument("--date", default=None)
    pe.set_defaults(func=cmd_add_from_exam)

    pl = sub.add_parser("list", help="列出孩子错题")
    pl.add_argument("--child", required=True)
    pl.add_argument("--subject", choices=["math", "chinese", "english"], default=None)
    pl.add_argument("--unit", type=int, default=None)
    pl.add_argument("--due", action="store_true", help="只看今日到期复习的错题")
    pl.add_argument("--all", action="store_true", help="包含已掌握的错题")
    pl.add_argument("--date", default=None)
    pl.set_defaults(func=cmd_list)

    pd = sub.add_parser("due", help="查看今日到期需要间隔复习的错题")
    pd.add_argument("--child", required=True)
    pd.add_argument("--subject", choices=["math", "chinese", "english"], default=None)
    pd.add_argument("--limit", type=int, default=0)
    pd.add_argument("--date", default=None)
    pd.set_defaults(func=cmd_due)

    pr = sub.add_parser("review", help="记录复习结果（推进或重置间隔复习）")
    pr.add_argument("--child", required=True)
    pr.add_argument("--ids", required=True, help="错题 ID，逗号分隔，如 m_001,m_002")
    grp = pr.add_mutually_exclusive_group(required=True)
    grp.add_argument("--passed", action="store_true", help="本次做对，进入下一复习间隔")
    grp.add_argument("--failed", action="store_true", help="本次仍错，错次+1并重置为3天后复习")
    pr.add_argument("--date", default=None)
    pr.set_defaults(func=cmd_review)

    ps = sub.add_parser("stats", help="查看错题库统计")
    ps.add_argument("--child", required=True)
    ps.add_argument("--date", default=None)
    ps.set_defaults(func=cmd_stats)

    px = sub.add_parser("export", help="导出可打印的错题本（默认直接输出 PDF）")
    px.add_argument("--child", required=True)
    px.add_argument("--subject", choices=["math", "chinese", "english"], default=None)
    px.add_argument("--unit", type=int, default=None)
    px.add_argument("--all", action="store_true", help="包含已掌握的错题")
    px.add_argument("-o", "--output", default=None, help="输出路径（默认 ~/.primary-exam/children/<id>/reports/<日期>_错题本.pdf）")
    px.add_argument("--keep-md", action="store_true", help="生成 PDF 的同时保留 .md 文件")
    px.add_argument("--md-only", action="store_true", help="仅输出 .md 文件，不渲染 PDF")
    px.add_argument("--chrome", default=None, help="Chrome/Chromium/Edge 可执行文件路径")
    px.set_defaults(func=cmd_export)

    return p


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
