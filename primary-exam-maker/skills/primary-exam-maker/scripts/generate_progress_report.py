#!/usr/bin/env python3
"""生成学习进度报告（含 fig_bars 条形图），默认直接输出 PDF 到 reports/ 目录。

用法:
  python3 generate_progress_report.py --child 老大
  python3 generate_progress_report.py --child 老大 --last 14 --subject math
  python3 generate_progress_report.py --child 老大 -o /path/to/report.pdf [--keep-md] [--md-only]
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import render_pdf  # noqa: E402
from mistake_bank import clean_num  # noqa: E402
from practice_log import calc_longest_streak, calc_streak, load_log  # noqa: E402
from profile import exam_home, find_child, load_store  # noqa: E402

SUBJECT_CN = {"math": "数学", "chinese": "语文", "english": "英语"}
SUBJECT_SHORT = {"math": "数", "chinese": "语", "english": "英"}
KIND_CN = {
    "daily_practice": "每日练习",
    "oral_math": "口算卡",
    "dictation": "听写单",
    "unit": "单元测验",
    "midterm": "期中测验",
    "final": "期末测验",
    "topic": "专项练习",
    "type": "题型专项",
    "mistake": "错题专项",
    "diagnostic": "诊断卷",
}


def resolve_child(query: str) -> dict:
    data = load_store()
    c = find_child(data, query)
    if not c:
        sys.exit(f"未找到孩子档案：{query}（用 profile.py list 查看已建档孩子）")
    return c


def default_report_path(child_id: str, *, md_only: bool = False, subject: str | None = None) -> Path:
    subj_prefix = f"{SUBJECT_CN.get(subject, subject)}_" if subject else ""
    ext = "md" if md_only else "pdf"
    return exam_home() / "children" / child_id / "reports" / f"{date.today():%Y%m%d}_{subj_prefix}学习进度报告.{ext}"


def _rate(score: float, total: float) -> int:
    """计算得分率百分比（0-100），total 为 0 时返回 0。"""
    return round(score / total * 100) if total else 0


def _streak_emoji(streak: int) -> str:
    if streak >= 7:
        return "🔥🔥🔥"
    if streak >= 3:
        return "🔥"
    return ""


def _motivational(streak: int) -> str:
    if streak >= 7:
        return f"连续打卡 {streak} 天，太棒了！继续保持！🌟"
    if streak >= 3:
        return f"连续打卡 {streak} 天，坚持就是胜利！"
    if streak >= 1:
        return "今天练习了，继续保持！"
    return "快开始今天的练习吧！"


def build_report(child: dict, log: dict, args) -> str:
    entries = log["entries"]

    if args.subject:
        entries = [e for e in entries if e["subject"] == args.subject]

    if not entries:
        lines = [
            f"# {child['nickname']}的学习进度报告",
            "",
            f"> 报告日期：{date.today().isoformat()}",
            "",
            "暂无练习记录。完成练习后用 `practice_log.py record` 记录成绩，",
            "即可生成进度报告。",
            "",
        ]
        return "\n".join(lines)

    if args.last:
        entries = entries[-args.last:]

    dates = [e["date"] for e in entries]
    streak = calc_streak(dates)
    longest = calc_longest_streak(dates)
    total_points = clean_num(sum(e["total"] for e in entries))
    total_score = clean_num(sum(e["score"] for e in entries))
    avg_rate = _rate(total_score, total_points)

    by_subject: dict[str, dict] = {}
    for e in entries:
        s = e["subject"]
        sb = by_subject.setdefault(s, {"total": 0.0, "score": 0.0})
        sb["total"] += e["total"]
        sb["score"] += e["score"]

    # 按 (学科, 单元) 聚合，避免跨学科单元合并
    by_subj_unit: dict[tuple[str, int], dict] = {}
    for e in entries:
        s = e.get("subject") or "unknown"
        for u_key, u_stat in e.get("units", {}).items():
            key = (s, int(u_key))
            ub = by_subj_unit.setdefault(key, {"total": 0.0, "score": 0.0})
            ub["total"] += u_stat["total"]
            ub["score"] += u_stat["score"]

    subject_names = "、".join(SUBJECT_CN.get(s, s) for s in sorted(by_subject))

    lines = [
        f"# {child['nickname']}的学习进度报告",
        "",
        f"> 报告日期：{date.today().isoformat()}",
        "",
        "## 📊 概况",
        "",
        f"- **累计练习**：{len(entries)} 次（累计得分 {total_score} / {total_points}）",
        f"- **平均得分率**：{avg_rate}%",
        f"- **当前连续打卡**：{streak} 天 {_streak_emoji(streak)}（历史最长 {longest} 天）",
        f"- **练习天数**：{len(set(dates))} 天",
        f"- **练习科目**：{subject_names}",
        "",
    ]

    # 最近 10 次练习得分率
    chart_entries = entries[-10:]
    chart_data = []
    for e in chart_entries:
        d = e["date"][5:].replace("-", "/")  # MM/DD
        rate = _rate(e["score"], e["total"])
        if rate > 0:  # fig_bars 不支持 0 值
            chart_data.append(f"{d}:{rate}")
    if chart_data:
        lines.extend([
            "## 📈 最近练习得分率",
            "",
            f'{{{{fig_bars data="{",".join(chart_data)}" title="每次练习得分率（%）" step=20 ymax=100}}}}',
            "",
        ])

    # 各单元掌握情况（多学科时带学科简称前缀，避免混淆）
    if by_subj_unit:
        multi_subj = len({s for s, _ in by_subj_unit}) > 1
        chart_data = []
        for s, u in sorted(by_subj_unit):
            rate = _rate(by_subj_unit[(s, u)]["score"], by_subj_unit[(s, u)]["total"])
            if rate > 0:
                label = f"{SUBJECT_SHORT.get(s, s)}U{u}" if multi_subj else f"第{u}单元"
                chart_data.append(f"{label}:{rate}")
        if chart_data:
            lines.extend([
                "## 📚 各单元掌握情况",
                "",
                f'{{{{fig_bars data="{",".join(chart_data)}" title="各单元平均得分率（%）" step=20 ymax=100}}}}',
                "",
            ])

    # 各学科对比（多科目时显示）
    if len(by_subject) > 1:
        chart_data = []
        for s in sorted(by_subject):
            r = by_subject[s]
            rate = _rate(r["score"], r["total"])
            if rate > 0:
                chart_data.append(f"{SUBJECT_CN.get(s, s)}:{rate}")
        if chart_data:
            lines.extend([
                "## 💪 各学科表现",
                "",
                f'{{{{fig_bars data="{",".join(chart_data)}" title="各学科平均得分率（%）" step=20 ymax=100}}}}',
                "",
            ])

    lines.extend([
        "## 📋 详细记录",
        "",
        "| 日期 | 科目 | 类型 | 得分 | 得分率 |",
        "|---|---|---|---|---|",
    ])
    for e in entries[-20:]:
        subj_cn = SUBJECT_CN.get(e["subject"], e["subject"])
        kind_cn = KIND_CN.get(e["kind"], e["kind"] or "-")
        score_str = f"{clean_num(e['score'])}/{clean_num(e['total'])}"
        pct = f"{_rate(e['score'], e['total'])}%"
        lines.append(f"| {e['date']} | {subj_cn} | {kind_cn} | {score_str} | {pct} |")

    lines.append("")
    lines.append("---")
    lines.append(f"> 💡 {_motivational(streak)}")
    lines.append("")

    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--child", required=True, help="孩子 id/昵称/别名")
    ap.add_argument("--last", type=int, default=30, help="只统计最近 N 条记录（默认 30）")
    ap.add_argument("--subject", choices=["math", "chinese", "english"], help="只统计指定科目")
    ap.add_argument("-o", "--out", type=Path, default=None, help="输出路径（默认 ~/.primary-exam/children/<id>/reports/<日期>_学习进度报告.pdf）")
    ap.add_argument("--keep-md", action="store_true", help="生成 PDF 的同时保留 .md 文件")
    ap.add_argument("--md-only", action="store_true", help="仅输出 .md 文件，不渲染 PDF")
    ap.add_argument("--chrome", help="Chrome/Chromium/Edge 可执行文件路径")
    args = ap.parse_args()

    c = resolve_child(args.child)
    log = load_log(c["id"])
    report_md = build_report(c, log, args)

    if args.out is not None:
        out_path = args.out
        md_only = args.md_only or (out_path.suffix.lower() == ".md" and not args.keep_md)
    else:
        md_only = args.md_only
        out_path = default_report_path(c["id"], md_only=md_only, subject=args.subject)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    if md_only:
        out_path.write_text(report_md, encoding="utf-8")
        print(f"OK: {out_path}")
        return 0

    pdf_path = out_path if out_path.suffix.lower() == ".pdf" else out_path.with_suffix(".pdf")
    if args.keep_md:
        md_path = pdf_path.with_suffix(".md")
        md_path.write_text(report_md, encoding="utf-8")
    try:
        render_pdf.render_md_text_to_pdf(report_md, pdf_path, chrome=args.chrome)
    except (ValueError, RuntimeError) as e:
        sys.exit(f"错误：{e}")
    print(f"OK: {pdf_path}")
    if args.keep_md:
        print(f"MD: {pdf_path.with_suffix('.md')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
