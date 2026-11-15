#!/usr/bin/env python3
"""生成进度报告 Markdown（含 fig_bars 图表），可用 render_pdf.py 渲染为 PDF。

用法:
  python3 generate_progress_report.py --child 老大 -o report.md
  python3 generate_progress_report.py --child 老大 --last 14 -o report.md
  python3 generate_progress_report.py --child 老大 --subject math -o report.md

生成后用 render_pdf.py 渲染为 PDF：
  python3 render_pdf.py report.md -o report.pdf
"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from profile import load_store, find_child  # noqa: E402
from practice_log import load_log, calc_streak  # noqa: E402

SUBJECT_CN = {"math": "数学", "chinese": "语文", "english": "英语"}
KIND_CN = {
    "daily_practice": "每日练习",
    "oral_math": "口算卡",
    "dictation": "听写单",
    "unit": "单元测验",
    "midterm": "期中测验",
    "final": "期末测验",
    "topic": "专项练习",
    "mistake": "错题专项",
    "diagnostic": "诊断卷",
}


def resolve_child(query: str) -> dict:
    data = load_store()
    c = find_child(data, query)
    if not c:
        sys.exit(f"未找到孩子档案：{query}（用 profile.py list 查看已建档孩子）")
    return c


def _rate(score: int, total: int) -> int:
    """计算正确率百分比（0-100），total 为 0 时返回 0。"""
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

    # Filter by subject if specified
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

    # Filter to last N entries
    if args.last:
        entries = entries[-args.last:]

    dates = [e["date"] for e in entries]
    streak = calc_streak(dates)
    total_items = sum(e["total"] for e in entries)
    total_score = sum(e["score"] for e in entries)
    avg_rate = _rate(total_score, total_items)

    # Per-subject stats
    by_subject: dict[str, dict] = {}
    for e in entries:
        s = e["subject"]
        if s not in by_subject:
            by_subject[s] = {"items": 0, "score": 0}
        by_subject[s]["items"] += e["total"]
        by_subject[s]["score"] += e["score"]

    # Per-unit stats
    by_unit: dict[str, dict] = {}
    for e in entries:
        for u_key, u_stat in e.get("units", {}).items():
            if u_key not in by_unit:
                by_unit[u_key] = {"total": 0, "score": 0}
            by_unit[u_key]["total"] += u_stat["total"]
            by_unit[u_key]["score"] += u_stat["score"]

    subject_names = "、".join(SUBJECT_CN.get(s, s) for s in sorted(by_subject))

    lines = [
        f"# {child['nickname']}的学习进度报告",
        "",
        f"> 报告日期：{date.today().isoformat()}",
        "",
        "## 📊 概况",
        "",
        f"- **累计练习**：{len(entries)} 次，共 {total_items} 题",
        f"- **平均正确率**：{avg_rate}%",
        f"- **连续打卡**：{streak} 天 {_streak_emoji(streak)}",
        f"- **练习天数**：{len(set(dates))} 天",
        f"- **练习科目**：{subject_names}",
        "",
    ]

    # Daily correct rate chart (last 10 sessions for readability)
    chart_entries = entries[-10:]
    chart_data = []
    for e in chart_entries:
        d = e["date"][5:].replace("-", "/")  # MM/DD
        rate = _rate(e["score"], e["total"])
        if rate > 0:  # fig_bars 不支持 0 值
            chart_data.append(f"{d}:{rate}")
    if chart_data:
        data_str = ",".join(chart_data)
        lines.extend([
            "## 📈 最近练习正确率",
            "",
            f'{{{{fig_bars data="{data_str}" title="每次练习正确率（%）" step=20 ymax=100}}}}',
            "",
        ])

    # Per-unit chart
    if by_unit:
        chart_data = []
        for u in sorted(by_unit, key=lambda x: int(x)):
            rate = _rate(by_unit[u]["score"], by_unit[u]["total"])
            if rate > 0:
                chart_data.append(f"第{u}单元:{rate}")
        if chart_data:
            lines.extend([
                "## 📚 各单元掌握情况",
                "",
                f'{{{{fig_bars data="{",".join(chart_data)}" title="各单元平均正确率（%）" step=20 ymax=100}}}}',
                "",
            ])

    # Per-subject chart (only if >1 subject)
    if len(by_subject) > 1:
        chart_data = []
        for s in sorted(by_subject):
            r = by_subject[s]
            rate = _rate(r["score"], r["items"])
            if rate > 0:
                chart_data.append(f"{SUBJECT_CN.get(s, s)}:{rate}")
        if chart_data:
            lines.extend([
                "## 💪 各学科表现",
                "",
                f'{{{{fig_bars data="{",".join(chart_data)}" title="各学科平均正确率（%）" step=20 ymax=100}}}}',
                "",
            ])

    # Detailed history table (last 20)
    lines.extend([
        "## 📋 详细记录",
        "",
        "| 日期 | 科目 | 类型 | 得分 | 正确率 |",
        "|---|---|---|---|---|",
    ])
    for e in entries[-20:]:
        subj_cn = SUBJECT_CN.get(e["subject"], e["subject"])
        kind_cn = KIND_CN.get(e["kind"], e["kind"] or "-")
        score_str = f"{e['score']}/{e['total']}"
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
    ap.add_argument("--subject", help="只统计指定科目")
    ap.add_argument("-o", "--out", type=Path, required=True, help="输出 Markdown 路径")
    args = ap.parse_args()

    c = resolve_child(args.child)
    log = load_log(c["id"])

    report = build_report(c, log, args)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(report, encoding="utf-8")
    print(f"OK: {args.out}")
    render_pdf = Path(__file__).resolve().parent / "render_pdf.py"
    pdf_out = args.out.with_suffix(".pdf")
    print(f'渲染 PDF: python3 "{render_pdf}" "{args.out}" -o "{pdf_out}"')
    return 0


if __name__ == "__main__":
    sys.exit(main())
