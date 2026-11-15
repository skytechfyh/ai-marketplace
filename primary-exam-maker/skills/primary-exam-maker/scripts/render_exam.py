#!/usr/bin/env python3
"""将校验通过的试卷 JSON 渲染为分离的「孩子试卷.md」与「答案与评分.md」（可选一键生成 PDF）。

用法:
  python3 render_exam.py exam.json -o /path/to/out_dir [--stem 名字] [--pdf]
"""
from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import validate_exam  # noqa: E402

CN_NUMS = ["一", "二", "三", "四", "五", "六", "七", "八", "九", "十", "十一", "十二"]
SUBJECT_NAMES = {"math": "数学", "chinese": "语文", "english": "英语"}
GRADE_CN = {1: "一", 2: "二", 3: "三", 4: "四", 5: "五", 6: "六"}
DIFF_NAMES = {"basic": "基础卷", "standard": "标准卷", "advanced": "提高卷"}
ERROR_BOXES = {
    "math": "□粗心 □进退位 □单位 □审题 □概念 □方法",
    "chinese": "□错别字 □拼音声调 □审题 □积累 □表达",
    "english": "□拼写 □词义 □语序 □听力 □审题",
}


def _strip_student_answers(stem: str) -> str:
    """防止游戏化识字指令中误带的 answer/answers 参数泄露到孩子试卷。"""
    def _clean(m: re.Match) -> str:
        inner = m.group(0)
        if not (inner.startswith("{{zhaopengyou") or inner.startswith("{{tupian_xuanzi")):
            return inner
        inner = re.sub(r'\s+answers?=(?:"[^"]*"|\'[^\']*\'|\S+)', "", inner)
        return inner

    return re.sub(r"\{\{[^}]+\}\}", _clean, stem)


def _fmt_directive(name: str, params: dict) -> str:
    parts = [name]
    for k, v in params.items():
        s = str(v)
        parts.append(f"{k}={shlex.quote(s)}" if any(c.isspace() or c in "'\"=" for c in s) or s == "" else f"{k}={s}")
    return "{{" + " ".join(parts) + "}}"


def _render_layout(layout: dict) -> list[str]:
    kind = layout["kind"]
    if kind in ("workspace", "tianzige", "fourline"):
        params = {k: v for k, v in layout.items() if k != "kind"}
        return [_fmt_directive(kind, params)]
    if kind == "pinyin_tianzige":
        return ["　".join(_fmt_directive("pinyin_tianzige", entry) for entry in layout["items"])]
    raise ValueError(f"未知 layout.kind: {kind}")


def _indent_block(lines: list[str], spaces: int = 4) -> list[str]:
    pad = " " * spaces
    return [f"{pad}{line}" if line else "" for line in lines]


def _format_options(opts: list[str]) -> list[str]:
    joined = "　　".join(str(o) for o in opts)
    if len(joined) <= 42 and "\n" not in joined:
        return [joined]
    return [str(o) for o in opts]


def build_student_md(data: dict) -> str:
    lines: list[str] = [f"# {data['title']}", ""]
    total = data.get("total_points")
    score_span = f"<span>得分：____ / {total}</span>" if total else ""
    lines.append(
        f'<div class="meta"><span>姓名：________</span><span>日期：________</span>'
        f'<span>用时：____ 分钟</span>{score_span}</div>'
    )
    lines.append("")

    if data.get("audio"):
        mp3 = data["audio"].get("mp3_name") or "听力.mp3"
        lines.append(f"> 🎧 本卷配套音频：`{mp3}`（每段读两遍）")
        lines.append("")

    q_counter = 1
    for si, sec in enumerate(data["sections"]):
        cn_no = CN_NUMS[si] if si < len(CN_NUMS) else str(si + 1)
        pts = sec.get("points")
        pts_txt = f"（共 {pts:g} 分）" if pts else ""
        lines.append(f"## {cn_no}、{sec['name']}{pts_txt}")
        lines.append("")
        if sec.get("instructions"):
            lines.append(sec["instructions"])
            lines.append("")
        if sec.get("passage"):
            for pline in str(sec["passage"]).splitlines():
                lines.append(f"> {pline}" if pline.strip() else ">")
            lines.append("")

        is_dictation_section = data.get("kind") == "dictation" or sec.get("id") == "dictation"
        if is_dictation_section:
            # 听写单的题干是作答格，用 HTML 行排版，避免 Markdown 把指令行拆成空列表项
            dict_cols = sec.get("columns") or 2
            lines.append(f'<div class="dict-grid dict-cols-{dict_cols}">')
            for it in sec["items"]:
                qno = it.get("no") or q_counter
                q_counter += 1
                lines.append(f'<div class="dict-row"><span class="dict-no">{qno}.</span>{it["stem"]}</div>')
            lines.append("</div>")
            lines.append("")
            continue

        cols = sec.get("columns")
        if cols in (2, 3):
            lines.append(f'<div class="cols-{cols}" markdown="1">')
            lines.append("")

        for it in sec["items"]:
            qno = it.get("no") or q_counter
            q_counter += 1
            badge = '<span class="badge">★ 拔高</span>' if it.get("tier") == "拔高" else ""
            stem_lines = _strip_student_answers(str(it["stem"])).splitlines()
            first = f"{qno}. {badge}{stem_lines[0]}"
            lines.append(first)
            for extra in stem_lines[1:]:
                lines.append(f"    {extra}" if extra else "")

            if it.get("options"):
                lines.append("")
                for opt_line in _format_options(it["options"]):
                    lines.append(f"    {opt_line}")

            if it.get("figure"):
                fig = it["figure"]
                lines.append("")
                lines.append("    " + _fmt_directive(f"fig_{fig['type']}", fig.get("params") or {}))

            if it.get("layout"):
                lines.append("")
                lines.extend(_indent_block(_render_layout(it["layout"])))

            lines.append("")

        if cols in (2, 3):
            lines.append("</div>")
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def build_answer_md(data: dict) -> str:
    subj = data["subject"]
    subj_name = SUBJECT_NAMES.get(subj, subj)
    scope = data["scope"]
    diff = DIFF_NAMES.get(data.get("difficulty_level"), data.get("difficulty_level") or "-")
    child_nick = (data.get("child") or {}).get("nickname") or "-"
    term_cn = "上" if scope["term"] == "up" else "下"
    grade_cn = GRADE_CN.get(scope.get("grade"), str(scope.get("grade")))
    units_txt = "、".join(str(u) for u in scope.get("units") or []) or "全册"

    tier_pts = Counter()
    ability_cnt = Counter()
    flat_items: list[tuple[str, dict]] = []
    q_counter = 1
    for sec in data["sections"]:
        for it in sec["items"]:
            qno = str(it.get("no") or q_counter)
            q_counter += 1
            tier_pts[it["tier"]] += it.get("points", 0)
            ability_cnt[it["ability"]] += 1
            flat_items.append((qno, it))

    lines: list[str] = [f"# {data['title']} · 答案与评分", ""]
    lines.append(
        f"- **孩子**：{child_nick} ｜ **学科/范围**：{subj_name} {grade_cn}年级{term_cn}（第 {units_txt} 单元）"
        f" ｜ **难度**：{diff} ｜ **总分**：{data.get('total_points') or '-'} 分"
    )
    tier_str = " / ".join(f"{k} {tier_pts[k]:g}分" for k in ("基础", "中档", "拔高"))
    abil_str = " / ".join(f"{k} {ability_cnt[k]}题" for k in ("了解", "理解", "掌握", "运用") if ability_cnt[k])
    lines.append(f"- **难度分布**：{tier_str} ｜ **能力层级**：{abil_str}")
    lines.append("")

    mistakes = [(qno, it["source_mistake"]) for qno, it in flat_items if it.get("source_mistake")]
    if mistakes:
        lines.append("## 错题对应表")
        lines.append("")
        lines.append("| 原错题 | 错因 | 变式类型 | 本卷题号 |")
        lines.append("|---|---|---|---|")
        grouped: dict[tuple[str, str, str], list[str]] = {}
        for qno, sm in mistakes:
            key = (str(sm.get("original", "-")), str(sm.get("error_type", "-")), str(sm.get("variant_kind", "-")))
            grouped.setdefault(key, []).append(str(qno))
        for (orig, etype, vkind), qnos in grouped.items():
            q_str = "、".join(qnos)
            lines.append(f"| {orig} | {etype} | {vkind} | 第 {q_str} 题 |")
        lines.append("")

    if data.get("audio") and data["audio"].get("script"):
        lines.append("## 听力原文")
        lines.append("")
        lines.append(data["audio"]["script"])
        lines.append("")

    lines.append("## 答案、评分细则与讲评提示")
    lines.append("")

    q_idx = 0
    for si, sec in enumerate(data["sections"]):
        cn_no = CN_NUMS[si] if si < len(CN_NUMS) else str(si + 1)
        lines.append(f"### {cn_no}、{sec['name']}")
        lines.append("")
        for _ in sec["items"]:
            qno, it = flat_items[q_idx]
            q_idx += 1
            kps = "、".join(it.get("knowledge_points") or ["待归类"])
            pts = it.get("points", 0)
            pts_str = f"{pts:g} 分 · " if pts else ""
            lines.append('<div class="ans-item" markdown="1">')
            lines.append("")
            lines.append(f"**第 {qno} 题**（{pts_str}{it['tier']} · {it['ability']} · 知识点：`{kps}`）")
            lines.append("")
            ans = it["answer"]
            ans_str = "、".join(str(x) for x in ans) if isinstance(ans, list) else str(ans)
            lines.append(f"- **参考答案**：{ans_str}")
            lines.append(f"- **评分细则**：{it['scoring_rules']}")
            lines.append(f"- **讲评提示**：{it['hint']}")
            if it.get("figure"):
                fig = it["figure"]
                lines.append("")
                lines.append(_fmt_directive(f"fig_{fig['type']}", fig.get("params") or {}))
            if it.get("rubric"):
                lines.append("")
                lines.append("| 评分维度 | 分值 | 要求 |")
                lines.append("|---|---|---|")
                for r in it["rubric"]:
                    lines.append(f"| {r['criterion']} | {r['points']} | {r.get('detail', '')} |")
            lines.append("")
            lines.append("</div>")
            lines.append("")

    lines.append('<div class="pagebreak"></div>')
    lines.append("")
    lines.append("## 家长阅卷表")
    lines.append("")
    lines.append("订正流程：孩子自己订正 → 讲给家长听 → 数日后重做错题。")
    lines.append("")
    lines.append('<div class="grading" markdown="1">')
    lines.append("")
    err_boxes = ERROR_BOXES.get(subj, "□粗心 □概念 □审题 □方法")
    lines.append("| 题号 | 满分 | 实得 | 判定 | 错因勾选 | 复核 |")
    lines.append("|---|---|---|---|---|---|")
    for qno, it in flat_items:
        pts = it.get("points", 0)
        pts_cell = f"{pts:g}" if pts else "-"
        lines.append(f"| 第 {qno} 题 | {pts_cell} | | □对 □半对 □错 | {err_boxes} | □已讲 □待重做 |")
    total_str = str(data.get("total_points") or "-")
    lines.append(f"| **合计** | **{total_str}** | | 用时：____分 | 难度反馈：□太难 □刚好 □太简单 | |")
    lines.append("")
    lines.append("</div>")
    lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def render_exam(exam_json: Path, out_dir: Path, stem: str | None = None, to_pdf: bool = False) -> tuple[Path, Path]:
    try:
        data = json.loads(exam_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON 解析失败：{exam_json}：{e}") from None
    except FileNotFoundError:
        raise ValueError(f"文件不存在：{exam_json}") from None
    errs, warns = validate_exam.validate_exam(data)
    for w in warns:
        print("WARN", w, file=sys.stderr)
    if errs:
        raise ValueError("试卷 JSON 校验未通过，拒绝渲染：\n  " + "\n  ".join(errs))

    out_dir.mkdir(parents=True, exist_ok=True)
    base = stem or data["exam_id"]
    student_md = out_dir / f"{base}_试卷.md"
    answer_md = out_dir / f"{base}_答案与评分.md"

    student_md.write_text(build_student_md(data), encoding="utf-8")
    answer_md.write_text(build_answer_md(data), encoding="utf-8")

    if to_pdf:
        render_pdf = Path(__file__).resolve().parent / "render_pdf.py"
        for md_path in (student_md, answer_md):
            subprocess.run([sys.executable, str(render_pdf), str(md_path)], check=True)

    return student_md, answer_md


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("exam_json", type=Path)
    ap.add_argument("-o", "--out-dir", type=Path, default=Path("."))
    ap.add_argument("--stem", help="输出文件名前缀（默认取 exam_id）")
    ap.add_argument("--pdf", action="store_true", help="同时调用 render_pdf.py 生成 PDF")
    args = ap.parse_args()

    try:
        s_md, a_md = render_exam(args.exam_json, args.out_dir, args.stem, args.pdf)
    except ValueError as e:
        sys.exit(f"错误：{e}")
    print("STUDENT_MD:", s_md)
    print("ANSWER_MD:", a_md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
