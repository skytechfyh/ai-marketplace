#!/usr/bin/env python3
"""校验试卷中间格式 JSON（schema、分值、难度分布、指令与图形、不超纲、不缺图）。

用法: python3 -I validate_exam.py exam.json [--strict]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import directives  # noqa: E402

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
TEMPLATES_PATH = DATA_DIR / "templates" / "exam_templates.json"

SUBJECTS = {"math", "chinese", "english"}
KINDS = {"unit", "midterm", "final", "oral_math", "dictation", "topic", "type", "mistake", "diagnostic", "daily_practice"}
SCORED_100_KINDS = {"unit", "midterm", "final"}
DIFFICULTIES = {"basic", "standard", "advanced"}
TIERS = {"基础", "中档", "拔高"}
ABILITIES = {"了解", "理解", "掌握", "运用"}
VISUAL_TYPES = {
    # 语文
    "看图写话", "看图写词", "看图写词/抄写", "看图写词/抄写句子",
    # 英语
    "听音选图", "听音选图/选内容", "看图选词",
    # 数学
    "看图列式", "看图填空", "看图选择", "看图判断", "看钟面",
    "量长度", "数一数", "看图连线", "操作与作图",
}


def check_figure_obj(fig: dict, loc: str, errs: list[str]) -> None:
    if not isinstance(fig, dict) or not fig.get("type"):
        errs.append(f"{loc}: figure 必须是含 type 的对象")
        return
    ftype = fig["type"]
    params = fig.get("params") or {}
    if not isinstance(params, dict):
        errs.append(f"{loc}: figure.params 必须是对象")
        return
    fn_name = f"fig_{ftype}"
    if fn_name not in directives.DIRECTIVES:
        avail = sorted(k[4:] for k in directives.DIRECTIVES if k.startswith("fig_"))
        errs.append(f"{loc}: 未知图形类型 figure.type={ftype!r}，可用：{avail}")
        return
    try:
        directives.DIRECTIVES[fn_name](**{k: str(v) for k, v in params.items()})
    except (TypeError, ValueError) as e:
        errs.append(f"{loc}: 图形参数错误（{fn_name}）：{e}")


def check_layout_obj(layout: dict, loc: str, errs: list[str]) -> None:
    if not isinstance(layout, dict) or not layout.get("kind"):
        errs.append(f"{loc}: layout 必须是含 kind 的对象")
        return
    kind = layout["kind"]
    if kind in ("workspace", "tianzige", "fourline"):
        params = {k: str(v) for k, v in layout.items() if k != "kind"}
        try:
            directives.DIRECTIVES[kind](**params)
        except (TypeError, ValueError) as e:
            errs.append(f"{loc}: layout({kind}) 参数错误：{e}")
    elif kind == "pinyin_tianzige":
        items = layout.get("items")
        if not isinstance(items, list) or not items:
            errs.append(f"{loc}: layout(pinyin_tianzige) 需要非空 items 列表")
            return
        for idx, entry in enumerate(items):
            if not isinstance(entry, dict):
                errs.append(f"{loc}: layout.items[{idx}] 必须是对象")
                continue
            try:
                directives.pinyin_tianzige(**{k: str(v) for k, v in entry.items()})
            except (TypeError, ValueError) as e:
                errs.append(f"{loc}: layout.items[{idx}] 错误：{e}")
    else:
        errs.append(f"{loc}: 未知 layout.kind={kind!r}")


CIRCLED_MAP = {ch: i for i, ch in enumerate("①②③④⑤⑥⑦⑧", 1)}
LETTER_MAP = {ch: i for i, ch in enumerate("ABCDEFGH", 1)}


def _check_choice_answer(opts: list, ans_raw, iloc: str, errs: list[str], warns: list[str]) -> None:
    """校验选择题答案与 options 是否匹配或越界。"""
    ans = str(ans_raw or "").strip()
    if not ans:
        return
    opt_strs = [str(o).strip() for o in opts]
    if ans in opt_strs:
        return
    if ans in CIRCLED_MAP:
        idx = CIRCLED_MAP[ans]
        if idx > len(opts):
            errs.append(f"{iloc}: 选择题答案 {ans!r} 超出选项数量 {len(opts)}")
        return
    upper = ans.upper()
    if upper in LETTER_MAP:
        idx = LETTER_MAP[upper]
        if idx > len(opts):
            errs.append(f"{iloc}: 选择题答案 {ans!r} 超出选项数量 {len(opts)}")
        return
    # 若选项带 ①/A 前缀而答案是选项正文，也放行
    stripped_opts = [re.sub(r"^[①②③④⑤⑥⑦⑧A-Ha-h][.、\s]*", "", o) for o in opt_strs]
    if ans in stripped_opts:
        return
    warns.append(f"{iloc}: 选择题答案 {ans!r} 未直接匹配任何选项")


def _clean_stem_for_sim(stem: str) -> str:
    s = re.sub(r"\{\{[^}]*\}\}", "", stem)
    s = re.sub(r"[0-9\s，。！？、；：（）()【】《》“”‘’\"'.,!?;:\-+=×÷○<>]+", "", s)
    return s


def _ngrams(s: str, n: int = 3) -> set[str]:
    return {s[i:i + n] for i in range(len(s) - n + 1)} if len(s) >= n else set()


def _extract_math_exprs(text: str) -> list[str]:
    norm = (text.replace("×", "*").replace("÷", "/").replace("−", "-")
            .replace("—", "-").replace("＋", "+").replace(" ", ""))
    exprs = []
    for m in re.finditer(r"\d+(?:[+\-*/]\d+)+", norm):
        exprs.append(m.group(0))
    return exprs


def _check_duplicates_and_clustering(sections: list[dict], subj: str | None, kind: str | None, warns: list[str]) -> None:
    """检查同源错题重复、近重复题干、跨大题算式撞车及口算得数扎堆。"""
    if kind == "dictation":
        return

    mistake_same_kind: dict[tuple[str, str], list[str]] = {}
    cleaned_stems: list[tuple[str, str, set[str]]] = []
    expr_locs: dict[str, list[tuple[str, str]]] = {}
    oral_answers: list[str] = []

    for sec in sections:
        sid = sec.get("id") or ""
        for ii, it in enumerate(sec.get("items") or []):
            iid = it.get("id") or f"#{ii + 1}"
            iloc = f"{sid}/{iid}"

            sm = it.get("source_mistake")
            if isinstance(sm, dict) and sm.get("original"):
                vk = str(sm.get("variant_kind") or "同构").strip()
                if vk == "同构":
                    key = (str(sm["original"]).strip(), vk)
                    mistake_same_kind.setdefault(key, []).append(iloc)

            stem = str(it.get("stem") or "")
            cleaned = _clean_stem_for_sim(stem)
            if len(cleaned) >= 14:
                grams = _ngrams(cleaned, 3)
                for prev_loc, prev_cleaned, prev_grams in cleaned_stems:
                    inter = len(grams & prev_grams)
                    union = len(grams | prev_grams)
                    jacc = inter / union if union else 0.0
                    contain = inter / min(len(grams), len(prev_grams)) if min(len(grams), len(prev_grams)) else 0.0
                    if jacc >= 0.50 or contain >= 0.55:
                        warns.append(f"{iloc}: 题干与 {prev_loc} 高度相似（疑似重复出题）")
                        break
                cleaned_stems.append((iloc, cleaned, grams))

            if subj == "math":
                is_oral = it.get("type") == "口算" or sid == "oral"
                if is_oral:
                    oral_answers.append(str(it.get("answer") or "").strip())
                    for ex in _extract_math_exprs(stem.split("=")[0]):
                        expr_locs.setdefault(ex, []).append((iloc, sid))
                else:
                    ans_str = str(it.get("answer") or "")
                    for ex in _extract_math_exprs(ans_str):
                        expr_locs.setdefault(ex, []).append((iloc, sid))

    for (orig, vk), locs in mistake_same_kind.items():
        if len(locs) >= 2:
            warns.append(f"{'、'.join(locs)} 共用同一原错题（{orig[:18]}…）且均为「{vk}」变式，建议合并或改用不同情境/迁移")

    for ex, locs in expr_locs.items():
        sids = {s for _, s in locs}
        if len(sids) >= 2:
            warns.append(f"跨大题算式撞车：算式 {ex} 同时出现在 {'、'.join(loc for loc, _ in locs)}")

    if len(oral_answers) >= 6:
        cnt = Counter(a for a in oral_answers if a)
        for ans, c in cnt.most_common():
            if c >= 3 and c / len(oral_answers) >= 0.25:
                warns.append(f"口算题答案扎堆：得数 {ans!r} 出现了 {c}/{len(oral_answers)} 次")


def load_kp_catalog(subject: str, grade: int, term: str) -> dict[str, int] | None:
    p = DATA_DIR / "knowledge" / subject / f"{subject}_g{grade}_{term}.json"
    if not p.exists():
        return None
    d = json.loads(p.read_text(encoding="utf-8"))
    return {kp["id"]: kp["unit"] for kp in d.get("knowledge_points", [])}


def validate_exam(data: dict) -> tuple[list[str], list[str]]:
    errs: list[str] = []
    warns: list[str] = []

    if data.get("schema") != 1:
        errs.append(f"schema 必须为 1，实际 {data.get('schema')!r}")
    for req in ("exam_id", "subject", "kind", "title", "scope", "sections"):
        if not data.get(req):
            errs.append(f"缺少必填字段：{req}")

    subj = data.get("subject")
    if subj and subj not in SUBJECTS:
        errs.append(f"subject={subj!r} 无效，应为 {sorted(SUBJECTS)}")
    kind = data.get("kind")
    if kind and kind not in KINDS:
        errs.append(f"kind={kind!r} 无效，应为 {sorted(KINDS)}")

    scope = data.get("scope") or {}
    grade = scope.get("grade")
    term = scope.get("term")
    units = scope.get("units")
    if not isinstance(grade, int) or not (1 <= grade <= 6):
        errs.append(f"scope.grade 应为 1..6 整数，实际 {grade!r}")
    if term not in ("up", "down"):
        errs.append(f"scope.term 应为 'up' 或 'down'，实际 {term!r}")
    max_unit = max(units) if isinstance(units, list) and units and all(isinstance(u, int) for u in units) else None

    diff = data.get("difficulty_level")
    if kind in SCORED_100_KINDS and diff not in DIFFICULTIES:
        errs.append(f"整卷类型 {kind!r} 必须指定 difficulty_level ∈ {sorted(DIFFICULTIES)}，实际 {diff!r}")
    elif diff is not None and diff not in DIFFICULTIES:
        errs.append(f"difficulty_level={diff!r} 无效")

    kp_catalog = load_kp_catalog(subj, grade, term) if subj in SUBJECTS and isinstance(grade, int) and term in ("up", "down") else None

    sections = data.get("sections") or []
    if not isinstance(sections, list) or not sections:
        errs.append("sections 必须是非空列表")
        return errs, warns

    sec_ids: set[str] = set()
    item_ids: set[str] = set()
    stems_seen: dict[str, str] = {}
    answers_seen: dict[str, str] = {}
    tier_points = {t: 0.0 for t in TIERS}
    total_section_points = 0.0

    for si, sec in enumerate(sections):
        sloc = f"sections[{si}]"
        sid = sec.get("id")
        if not sid or not sec.get("name"):
            errs.append(f"{sloc}: 缺 id 或 name")
        elif sid in sec_ids:
            errs.append(f"{sloc}: section id 重复：{sid!r}")
        else:
            sec_ids.add(sid)

        if sec.get("passage"):
            try:
                directives.expand(str(sec["passage"]))
            except ValueError as e:
                errs.append(f"{sloc}({sid}) passage 指令错误：{e}")

        items = sec.get("items") or []
        if not isinstance(items, list) or not items:
            errs.append(f"{sloc}({sid}): items 必须是非空列表")
            continue

        sec_item_pts = 0.0
        for ii, it in enumerate(items):
            iid = it.get("id") or f"#{ii + 1}"
            iloc = f"{sid}/{iid}"
            for req in ("id", "stem", "type", "ability", "tier", "answer", "scoring_rules", "hint"):
                v = it.get(req)
                if v is None or (isinstance(v, str) and not v.strip()):
                    errs.append(f"{iloc}: 缺必填字段 {req}")

            if it.get("id"):
                if it["id"] in item_ids:
                    errs.append(f"{iloc}: 题目 id 重复：{it['id']!r}")
                item_ids.add(it["id"])

            pts = it.get("points", 0)
            if not isinstance(pts, (int, float)) or pts < 0:
                errs.append(f"{iloc}: points 必须为非负数，实际 {pts!r}")
                pts = 0
            elif kind in SCORED_100_KINDS and pts <= 0:
                errs.append(f"{iloc}: 整卷题目 points 必须 > 0，实际 {pts!r}")
            sec_item_pts += pts

            tier = it.get("tier")
            if tier and tier not in TIERS:
                errs.append(f"{iloc}: tier={tier!r} 无效，应为 {sorted(TIERS)}")
            elif tier:
                tier_points[tier] += pts

            if it.get("ability") and it["ability"] not in ABILITIES:
                errs.append(f"{iloc}: ability={it['ability']!r} 无效，应为 {sorted(ABILITIES)}")

            stem = str(it.get("stem") or "")
            norm_stem = " ".join(stem.split())
            if norm_stem:
                if kind == "dictation" or sid == "dictation":
                    # 听写单（及每日练习卡的 dictation section）题干是作答格，内容在答案里，按答案去重
                    ans_key = str(it.get("answer") or "").strip()
                    if ans_key:
                        if ans_key in answers_seen:
                            errs.append(f"{iloc}: 听写内容与 {answers_seen[ans_key]} 重复")
                        else:
                            answers_seen[ans_key] = iloc
                elif norm_stem in stems_seen:
                    errs.append(f"{iloc}: 题干与 {stems_seen[norm_stem]} 重复")
                else:
                    stems_seen[norm_stem] = iloc
                try:
                    directives.expand(stem)
                except ValueError as e:
                    errs.append(f"{iloc}: stem 指令错误：{e}")

            if it.get("options") is not None:
                opts = it["options"]
                if not isinstance(opts, list) or len(opts) < 2:
                    errs.append(f"{iloc}: options 至少需要 2 项")
                else:
                    if len(set(str(o).strip() for o in opts)) != len(opts):
                        errs.append(f"{iloc}: options 存在重复选项")
                    _check_choice_answer(opts, it.get("answer"), iloc, errs, warns)

            has_inline_fig = "{{fig_" in stem
            if "figure" in it and it["figure"] is not None:
                check_figure_obj(it["figure"], iloc, errs)
            elif it.get("requires_figure") or it.get("type") in VISUAL_TYPES:
                if not has_inline_fig:
                    errs.append(f"{iloc}: 题型 {it.get('type')!r} 必须带图（缺图拒绝出卷）")

            if "layout" in it and it["layout"] is not None:
                check_layout_obj(it["layout"], iloc, errs)

            unit = it.get("unit")
            if unit is None and kind != "diagnostic":
                warns.append(f"{iloc}: 未标 unit 单元号")
            elif isinstance(unit, int) and max_unit is not None and kind != "diagnostic":
                if unit > max_unit:
                    errs.append(f"{iloc}: 超纲检查未通过，题目 unit={unit} > 允许最大单元 {max_unit}")

            if kp_catalog is not None:
                for kp in it.get("knowledge_points") or []:
                    if kp == "待归类":
                        continue
                    if kp not in kp_catalog:
                        errs.append(f"{iloc}: 知识点 {kp!r} 不在本册目录中")
                    elif max_unit is not None and kind != "diagnostic" and kp_catalog[kp] > max_unit:
                        errs.append(f"{iloc}: 知识点 {kp!r} 属于第 {kp_catalog[kp]} 单元 > 允许最大单元 {max_unit}")

        if "points" in sec and sec["points"] is not None:
            if abs(sec["points"] - sec_item_pts) > 1e-6:
                errs.append(f"{sloc}({sid}): 大题分值 {sec['points']} ≠ 小题分值之和 {sec_item_pts}")
            total_section_points += sec["points"]
        else:
            total_section_points += sec_item_pts

    if kind in SCORED_100_KINDS:
        if data.get("total_points") != 100:
            errs.append(f"整卷 {kind!r} total_points 必须为 100，实际 {data.get('total_points')!r}")
        if abs(total_section_points - 100) > 1e-6:
            errs.append(f"整卷各大题分值之和 {total_section_points} ≠ 100")
        if diff == "basic":
            if tier_points["拔高"] > 0:
                errs.append(f"基础卷不允许拔高题，当前拔高分值 {tier_points['拔高']}")
            if tier_points["基础"] < 75:
                errs.append(f"基础卷基础题分值 {tier_points['基础']} < 75")
        elif diff == "standard":
            if tier_points["基础"] < 60:
                errs.append(f"标准卷基础题分值 {tier_points['基础']} < 60")
            if tier_points["拔高"] > 18:
                errs.append(f"标准卷拔高题分值 {tier_points['拔高']} > 18")
            if tier_points["拔高"] == 0:
                warns.append("标准卷拔高题分值为 0（建议 5–15 分）")
        elif diff == "advanced":
            if tier_points["拔高"] < 12:
                errs.append(f"提高卷拔高题分值 {tier_points['拔高']} < 12")
    elif data.get("total_points") is not None:
        if abs(total_section_points - data["total_points"]) > 1e-6:
            errs.append(f"total_points={data['total_points']} ≠ 各大题分值之和 {total_section_points}")

    _check_duplicates_and_clustering(sections, subj, kind, warns)

    return errs, warns


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("exam_json", type=Path)
    ap.add_argument("--strict", action="store_true", help="将 warning 也视为失败")
    args = ap.parse_args()

    try:
        data = json.loads(args.exam_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        sys.exit(f"JSON 解析失败：{args.exam_json}：{e}")
    except FileNotFoundError:
        sys.exit(f"文件不存在：{args.exam_json}")
    errs, warns = validate_exam(data)
    for w in warns:
        print("WARN", w)
    for e in errs:
        print("FAIL", e)
    status = "PASS" if not errs and not (args.strict and warns) else "FAIL"
    print(f"{status}: {len(errs)} errors, {len(warns)} warnings")
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
