#!/usr/bin/env python3
"""将校验并核验通过的试卷 JSON 渲染为分离的「孩子试卷.pdf」与「答案与评分.pdf」。

默认行为：
  - 按每份试卷建独立子目录 `<out_dir>/<exam_id>/`（同日重名自动追加 `-2`、`-3` 防覆盖）
  - 归档源 JSON 为 `<子目录>/exam.json`（供记成绩、错题入库与重渲复用）
  - 默认直接渲染 PDF，不保留中间 `.md`（需要时加 `--keep-md` 或 `--md-only`）
  - 自动执行 `validate_exam.py` + `verify_exam.py`（有 FAIL 拒绝渲染）

用法:
  python3 render_exam.py exam.json --child 瑞瑞
  python3 render_exam.py exam.json -o /path/to/exams [--stem 名字] [--keep-md] [--md-only] [--flat]
"""
from __future__ import annotations

import argparse
import json
import re
import shlex
import shutil
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import profile as profile_mod  # noqa: E402
import render_pdf  # noqa: E402
import validate_exam  # noqa: E402
import verify_exam  # noqa: E402

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


def _allocate_exam_dir(
    root_dir: Path,
    base: str,
    exam_json: Path,
    *,
    overwrite: bool = False,
) -> tuple[Path, str]:
    """为当次出卷分配独立子目录；若已存在非空同名目录且非原地重渲，自动追加 -2/-3 防覆盖。"""
    src_parent = exam_json.resolve().parent
    candidate = root_dir / base
    if overwrite or not candidate.exists():
        return candidate, base
    if candidate.is_dir():
        if candidate.resolve() == src_parent or not any(candidate.iterdir()):
            return candidate, base

    idx = 2
    while True:
        name = f"{base}-{idx}"
        cand = root_dir / name
        if not cand.exists() or (cand.is_dir() and not any(cand.iterdir())):
            return cand, name
        idx += 1


def _resolve_root_dir(out_dir: Path | None, child: str | None) -> Path:
    if out_dir is not None:
        return out_dir
    if child:
        store = profile_mod.load_store()
        c = profile_mod.find_child(store, child)
        if not c:
            raise ValueError(f"未找到孩子档案：{child}（请先用 profile.py list 查看或 profile.py add 建档）")
        return profile_mod.exam_home() / "children" / c["id"] / "exams"
    return Path(".")


def render_exam(
    exam_json: Path,
    out_dir: Path | None = None,
    stem: str | None = None,
    *,
    child: str | None = None,
    keep_md: bool = False,
    md_only: bool = False,
    flat: bool = False,
    overwrite: bool = False,
    skip_verify: bool = False,
    chrome: str | None = None,
) -> dict[str, Path | None]:
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

    if not skip_verify:
        v_errs, v_warns, _ = verify_exam.verify_exam_data(data)
        for w in v_warns:
            print("WARN [verify]", w, file=sys.stderr)
        if v_errs:
            raise ValueError("试卷学科核验未通过，拒绝渲染：\n  " + "\n  ".join(v_errs))

    root_dir = _resolve_root_dir(out_dir, child)
    base = stem or data["exam_id"]
    if flat:
        target_dir = root_dir
        file_base = base
        archived_json: Path | None = None
    else:
        target_dir, file_base = _allocate_exam_dir(root_dir, base, exam_json, overwrite=overwrite)
        archived_json = target_dir / "exam.json"

    target_dir.mkdir(parents=True, exist_ok=True)
    if archived_json is not None and exam_json.resolve() != archived_json.resolve():
        shutil.copy2(exam_json, archived_json)

    student_text = build_student_md(data)
    answer_text = build_answer_md(data)

    student_md: Path | None = None
    answer_md: Path | None = None
    student_pdf: Path | None = None
    answer_pdf: Path | None = None

    if md_only or keep_md:
        student_md = target_dir / f"{file_base}_试卷.md"
        answer_md = target_dir / f"{file_base}_答案与评分.md"
        student_md.write_text(student_text, encoding="utf-8")
        answer_md.write_text(answer_text, encoding="utf-8")

    if not md_only:
        student_pdf = target_dir / f"{file_base}_试卷.pdf"
        answer_pdf = target_dir / f"{file_base}_答案与评分.pdf"
        render_pdf.render_md_text_to_pdf(student_text, student_pdf, chrome=chrome)
        render_pdf.render_md_text_to_pdf(answer_text, answer_pdf, chrome=chrome)

    return {
        "out_dir": target_dir,
        "exam_json": archived_json,
        "student_pdf": student_pdf,
        "answer_pdf": answer_pdf,
        "student_md": student_md,
        "answer_md": answer_md,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("exam_json", type=Path)
    ap.add_argument("-o", "--out-dir", type=Path, default=None, help="输出根目录（未传 --flat 时默认在此目录下建 <exam_id>/ 子目录）")
    ap.add_argument("--child", help="孩子 id/昵称/别名（自动输出到 ~/.primary-exam/children/<id>/exams/<exam_id>/）")
    ap.add_argument("--stem", help="输出子目录与文件名前缀（默认取 exam_id）")
    ap.add_argument("--pdf", action="store_true", help="兼容保留参数（现已默认直接输出 PDF）")
    ap.add_argument("--keep-md", action="store_true", help="在生成 PDF 的同时保留中间 .md 文件")
    ap.add_argument("--md-only", action="store_true", help="仅生成 .md 文件，不渲染 PDF（无 Chrome 环境或调试用）")
    ap.add_argument("--flat", action="store_true", help="直接平铺输出到 -o 目录，不建独立子目录、不归档 exam.json")
    ap.add_argument("--overwrite", action="store_true", help="同名子目录已存在时直接覆盖，不追加 -2/-3 后缀")
    ap.add_argument("--skip-verify", action="store_true", help="跳过内置的 verify_exam.py 学科核验")
    ap.add_argument("--chrome", help="Chrome/Chromium/Edge 可执行文件路径")
    args = ap.parse_args()

    try:
        res = render_exam(
            args.exam_json,
            args.out_dir,
            args.stem,
            child=args.child,
            keep_md=args.keep_md,
            md_only=args.md_only,
            flat=args.flat,
            overwrite=args.overwrite,
            skip_verify=args.skip_verify,
            chrome=args.chrome,
        )
    except (ValueError, RuntimeError) as e:
        sys.exit(f"错误：{e}")

    print("OUT_DIR:", res["out_dir"])
    if res["exam_json"]:
        print("EXAM_JSON:", res["exam_json"])
    if res["student_pdf"]:
        print("STUDENT_PDF:", res["student_pdf"])
    if res["answer_pdf"]:
        print("ANSWER_PDF:", res["answer_pdf"])
    if res["student_md"]:
        print("STUDENT_MD:", res["student_md"])
    if res["answer_md"]:
        print("ANSWER_MD:", res["answer_md"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
