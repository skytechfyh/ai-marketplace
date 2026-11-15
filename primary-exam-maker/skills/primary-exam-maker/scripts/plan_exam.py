#!/usr/bin/env python3
"""出整卷前的组卷规划：读取试卷模板、范围知识点与字词/词表范围，输出题量与分值骨架。

用法:
  python3 plan_exam.py --subject math --grade 2 --term up --kind unit --units 1,2
  python3 plan_exam.py --subject chinese --grade 3 --term down --kind final --json
"""
import argparse
import json
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
DATA = SKILL_DIR / "data"
SUBJECT_CN = {"math": "数学", "chinese": "语文", "english": "英语"}
GRADE_CN = {2: "二", 3: "三"}
KIND_CN = {"unit": "单元测验", "midterm": "期中试卷", "final": "期末试卷"}
DIFF_CN = {"basic": "基础卷", "standard": "标准卷", "advanced": "提高卷"}


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_template(templates: dict, subject: str, grade: int, term: str, kind: str) -> dict:
    node = templates.get(subject, {})
    sub = node.get(f"g{grade}") or node.get(f"g{grade}_{term}")
    if not sub:
        raise ValueError(f"模板中没有 {subject} g{grade}（或 g{grade}_{term}）")
    tpl = sub.get(kind)
    if not tpl:
        raise ValueError(f"模板中没有 {subject} g{grade} 的 {kind}")
    while "same_as" in tpl:
        tpl = sub[tpl["same_as"]]
    return tpl


def load_knowledge(subject: str, grade: int, term: str) -> list[dict]:
    path = DATA / "knowledge" / subject / f"{subject}_g{grade}_{term}.json"
    if not path.exists():
        return []
    return load_json(path).get("knowledge_points", [])


def chinese_units(grade: int, term: str, units: list[int]) -> dict:
    base = DATA / "curriculum" / "chinese" / f"chinese_g{grade}_{term}"
    tables = load_json(Path(f"{base}_tables.json"))
    curriculum = load_json(Path(f"{base}.json"))
    lesson_unit = {}
    for unit in curriculum["units"]:
        for item in unit.get("items", []):
            if item.get("type") == "lesson" and item.get("no") is not None:
                lesson_unit[(unit.get("kind", "阅读"), item["no"])] = unit["no"]
    stats = {}
    for mode in ("literacy", "writing", "words"):
        for sec in tables["tables"].get(mode, []):
            unit_no = lesson_unit.get((sec.get("section"), sec.get("no")))
            if unit_no is None or unit_no not in units:
                continue
            s = stats.setdefault(unit_no, {"literacy": 0, "writing": 0, "words": 0})
            s[mode] += len(sec.get("items", []))
    return stats


def english_units(grade: int, term: str, units: list[int]) -> dict:
    path = DATA / "curriculum" / "english" / f"english_g{grade}_{term}_wordlist.json"
    if not path.exists():
        return {}
    stats = {}
    for u in load_json(path).get("units", []):
        if u["unit"] not in units:
            continue
        core = [w for w in u.get("words", []) if w.get("core")]
        stats[u["unit"]] = {"core": len(core), "total": len(u.get("words", []))}
    return stats


def build_plan(args) -> dict:
    templates = load_json(DATA / "templates" / "exam_templates.json")
    tpl = resolve_template(templates, args.subject, args.grade, args.term, args.kind)
    kps = load_knowledge(args.subject, args.grade, args.term)
    units = sorted(set(args.units or []))
    if units:
        kps = [k for k in kps if k.get("unit") in units]
    plan = {
        "subject": args.subject,
        "grade": args.grade,
        "term": args.term,
        "kind": args.kind,
        "difficulty_level": args.difficulty,
        "units": units or "全册",
        "suggested_minutes": tpl.get("suggested_minutes"),
        "sections": [
            {k: sec[k] for k in ("id", "name", "count", "per", "points_list", "points", "tier", "note") if k in sec}
            for sec in tpl.get("sections", [])
        ],
        "tier_ratio": templates.get("difficulty_levels", {}).get(args.difficulty, {}).get("ratio"),
        "knowledge_points": [
            {"id": k["id"], "name": k["name"], "unit": k["unit"], "level": k["level"]}
            for k in kps
        ],
        "warnings": [],
    }
    if args.subject == "chinese" and units:
        plan["word_ranges"] = chinese_units(args.grade, args.term, units)
    elif args.subject == "english" and units:
        plan["word_ranges"] = english_units(args.grade, args.term, units)
    if not kps:
        plan["warnings"].append("本册/本范围没有知识点目录，出题时 knowledge_points 先写 [\"待归类\"]")
    if args.kind == "unit" and not units:
        plan["warnings"].append("单元测验建议用 --units 指定范围")
    if args.difficulty == "basic":
        plan["warnings"].append("基础卷禁止拔高题；基础题分值不得低于 75")
    return plan


def print_markdown(plan: dict) -> None:
    subj = SUBJECT_CN[plan["subject"]]
    grade = GRADE_CN.get(plan["grade"], plan["grade"])
    term = "上" if plan["term"] == "up" else "下"
    range_txt = "全册" if plan["units"] == "全册" else f"第 {'、'.join(str(u) for u in plan['units'])} 单元"
    print(f"# {grade}年级{subj}{term}册 · {KIND_CN[plan['kind']]}（{DIFF_CN[plan['difficulty_level']]}）\n")
    print(f"- 范围：{range_txt} ｜ 建议时长：{plan['suggested_minutes']} 分钟 ｜ 总分：100（不设卷面分）")
    if plan.get("tier_ratio"):
        print(f"- 难度比例：基础 {plan['tier_ratio'].get('基础')} / 中档 {plan['tier_ratio'].get('中档')} / 拔高 {plan['tier_ratio'].get('拔高')}")
    print("\n## 大题结构\n")
    print("| 大题 | 题量 | 每题分 | 总分 | 默认档 | 提示 |")
    print("|---|---|---|---|---|---|")
    for s in plan["sections"]:
        per = s.get("per") or ("、".join(str(x) for x in s.get("points_list", [])) or "-")
        print(f"| {s['name']} | {s.get('count', '-')} | {per} | {s.get('points', '-')} | {s.get('tier', '-')} | {s.get('note', '')} |")
    print("\n## 可用知识点\n")
    if plan["knowledge_points"]:
        for k in plan["knowledge_points"]:
            print(f"- `{k['id']}` {k['name']}（第 {k['unit']} 单元 · {k['level']}）")
    else:
        print("- （本范围无知识点目录）")
    if plan.get("word_ranges"):
        print("\n## 字词范围\n")
        for unit, stat in sorted(plan["word_ranges"].items()):
            print(f"- 第 {unit} 单元：{stat}")
    if plan["warnings"]:
        print("\n## 提醒\n")
        for w in plan["warnings"]:
            print(f"- {w}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--subject", required=True, choices=["math", "chinese", "english"])
    ap.add_argument("--grade", type=int, required=True, choices=[2, 3])
    ap.add_argument("--term", required=True, choices=["up", "down"])
    ap.add_argument("--kind", required=True, choices=["unit", "midterm", "final"])
    ap.add_argument("--units", help="单元范围，如 1,2 或 1-3")
    ap.add_argument("--difficulty", default="standard", choices=["basic", "standard", "advanced"])
    ap.add_argument("--json", action="store_true", help="输出 JSON 而不是 Markdown")
    args = ap.parse_args()

    if args.units:
        units = []
        for part in args.units.split(","):
            part = part.strip()
            if "-" in part:
                a, b = part.split("-", 1)
                units.extend(range(int(a), int(b) + 1))
            else:
                units.append(int(part))
        args.units = sorted(set(units))

    try:
        plan = build_plan(args)
    except ValueError as e:
        ap.error(str(e))
    if args.json:
        print(json.dumps(plan, ensure_ascii=False, indent=1))
    else:
        print_markdown(plan)
    return 0


if __name__ == "__main__":
    sys.exit(main())
