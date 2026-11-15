#!/usr/bin/env python3
"""孩子档案管理（~/.primary-exam/）与教材校对时效检查。

个人数据默认存在 ~/.primary-exam/（不进仓库）；可通过环境变量 PRIMARY_EXAM_HOME 覆盖，便于测试隔离。
年级由入学年份与当前日期自动推算，学年更替无需手动修改。

用法示例:
  python3 profile.py list
  python3 profile.py add --id child1 --nickname 老大 --enrollment-year 2024 --aliases 大宝
  python3 profile.py get 老大
  python3 profile.py update 老大 --subject math --current-unit 3 --difficulty standard
  python3 profile.py check-freshness
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime
from pathlib import Path

DEFAULT_EDITIONS = {
    "math": "苏教版",
    "chinese": "统编版",
    "english": "译林版",
}
VALID_DIFFICULTIES = ("basic", "standard", "advanced")
CURRICULUM_DIR = Path(__file__).resolve().parent.parent / "data" / "curriculum"


def exam_home() -> Path:
    env = os.environ.get("PRIMARY_EXAM_HOME")
    return Path(env).expanduser() if env else Path.home() / ".primary-exam"


def profiles_path() -> Path:
    return exam_home() / "profiles.json"


def load_store() -> dict:
    p = profiles_path()
    if not p.exists():
        return {"schema": 1, "children": []}
    return json.loads(p.read_text(encoding="utf-8"))


def save_store(data: dict) -> None:
    home = exam_home()
    home.mkdir(parents=True, exist_ok=True)
    for c in data["children"]:
        (home / "children" / c["id"] / "exams").mkdir(parents=True, exist_ok=True)
    profiles_path().write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def infer_grade_term(
    enrollment_year: int,
    ref_date: date | None = None,
    fall_start: str = "09-01",
    spring_start: str = "02-15",
) -> dict:
    """根据入学年份与学期起始日推算当前年级、学期与册次代号。"""
    today = ref_date or date.today()
    mmdd = today.strftime("%m-%d")
    if mmdd >= fall_start:
        school_year, term, term_en = today.year, "上", "up"
    elif mmdd < spring_start:
        school_year, term, term_en = today.year - 1, "上", "up"
    else:
        school_year, term, term_en = today.year - 1, "下", "down"

    grade = school_year - enrollment_year + 1
    return {
        "as_of": today.isoformat(),
        "school_year": school_year,
        "grade": grade,
        "term": term,
        "term_en": term_en,
        "code": f"g{grade}_{term_en}",
        "in_primary": 1 <= grade <= 6,
        "supported_v1": grade in (2, 3),
    }


def enrich_child(c: dict, ref_date: date | None = None) -> dict:
    out = dict(c)
    out["current"] = infer_grade_term(
        c["enrollment_year"],
        ref_date=ref_date,
        fall_start=c.get("fall_start", "09-01"),
        spring_start=c.get("spring_start", "02-15"),
    )
    out["workspace"] = str(exam_home() / "children" / c["id"])
    return out


def find_child(data: dict, query: str) -> dict | None:
    q = query.strip().lower()
    for c in data["children"]:
        if c["id"].lower() == q or c["nickname"].lower() == q:
            return c
        if any(a.lower() == q for a in c.get("aliases", [])):
            return c
    return None


def cmd_list(args) -> int:
    data = load_store()
    ref = date.fromisoformat(args.date) if args.date else None
    out = [enrich_child(c, ref) for c in data["children"]]
    print(json.dumps({"home": str(exam_home()), "children": out}, ensure_ascii=False, indent=2))
    return 0


def cmd_add(args) -> int:
    data = load_store()
    if find_child(data, args.id) or find_child(data, args.nickname):
        sys.exit(f"错误：孩子 id 或昵称已存在：{args.id} / {args.nickname}")
    if args.enrollment_year < 2015 or args.enrollment_year > 2035:
        sys.exit(f"错误：enrollment_year={args.enrollment_year} 不合理")
    child = {
        "id": args.id,
        "nickname": args.nickname,
        "aliases": [a.strip() for a in args.aliases.split(",") if a.strip()] if args.aliases else [],
        "enrollment_year": args.enrollment_year,
        "fall_start": args.fall_start,
        "spring_start": args.spring_start,
        "subjects": {
            s: {"edition": ed, "current_unit": None, "difficulty": "standard"}
            for s, ed in DEFAULT_EDITIONS.items()
        },
    }
    data["children"].append(child)
    save_store(data)
    print(json.dumps(enrich_child(child), ensure_ascii=False, indent=2))
    return 0


def cmd_get(args) -> int:
    data = load_store()
    c = find_child(data, args.query)
    if not c:
        sys.exit(f"未找到孩子档案：{args.query}（档案文件：{profiles_path()}）")
    ref = date.fromisoformat(args.date) if args.date else None
    print(json.dumps(enrich_child(c, ref), ensure_ascii=False, indent=2))
    return 0


def cmd_update(args) -> int:
    data = load_store()
    c = find_child(data, args.query)
    if not c:
        sys.exit(f"未找到孩子档案：{args.query}")
    if args.nickname:
        c["nickname"] = args.nickname
    if args.aliases is not None:
        c["aliases"] = [a.strip() for a in args.aliases.split(",") if a.strip()]
    if args.enrollment_year is not None:
        c["enrollment_year"] = args.enrollment_year
    if args.subject:
        subj = c.setdefault("subjects", {}).setdefault(
            args.subject, {"edition": DEFAULT_EDITIONS.get(args.subject, ""), "current_unit": None, "difficulty": "standard"}
        )
        if args.current_unit is not None:
            subj["current_unit"] = args.current_unit
        if args.difficulty:
            if args.difficulty not in VALID_DIFFICULTIES:
                sys.exit(f"错误：difficulty 必须是 {VALID_DIFFICULTIES}")
            subj["difficulty"] = args.difficulty
        if args.edition:
            subj["edition"] = args.edition
    elif args.current_unit is not None or args.difficulty or args.edition:
        sys.exit("错误：修改 current_unit / difficulty / edition 时必须指定 --subject")
    save_store(data)
    print(json.dumps(enrich_child(c), ensure_ascii=False, indent=2))
    return 0


def cmd_freshness(args) -> int:
    ref = date.fromisoformat(args.date) if args.date else date.today()
    stale = []
    checked = 0
    for p in sorted(CURRICULUM_DIR.rglob("*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        v = (d.get("source") or {}).get("verified_on")
        if not v:
            continue
        checked += 1
        days = (ref - datetime.strptime(v, "%Y-%m-%d").date()).days
        if days > args.max_days:
            stale.append({"file": str(p.relative_to(CURRICULUM_DIR)), "verified_on": v, "age_days": days})
    print(json.dumps({"as_of": ref.isoformat(), "checked": checked, "max_days": args.max_days, "stale": stale}, ensure_ascii=False, indent=2))
    return 1 if stale else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="列出全部孩子档案")
    p_list.add_argument("--date", help="按指定日期推算年级（YYYY-MM-DD）")
    p_list.set_defaults(func=cmd_list)

    p_add = sub.add_parser("add", help="新增孩子档案")
    p_add.add_argument("--id", required=True, help="唯一英文标识，如 child1")
    p_add.add_argument("--nickname", required=True, help="常用称呼，如 老大")
    p_add.add_argument("--enrollment-year", type=int, required=True, help="小学一年级入学年份，如 2024")
    p_add.add_argument("--aliases", default="", help="逗号分隔别名，如 大宝,哥哥")
    p_add.add_argument("--fall-start", default="09-01")
    p_add.add_argument("--spring-start", default="02-15")
    p_add.set_defaults(func=cmd_add)

    p_get = sub.add_parser("get", help="按 id/昵称/别名查询孩子档案")
    p_get.add_argument("query")
    p_get.add_argument("--date", help="按指定日期推算年级（YYYY-MM-DD）")
    p_get.set_defaults(func=cmd_get)

    p_upd = sub.add_parser("update", help="更新孩子档案或学科进度")
    p_upd.add_argument("query")
    p_upd.add_argument("--nickname")
    p_upd.add_argument("--aliases")
    p_upd.add_argument("--enrollment-year", type=int)
    p_upd.add_argument("--subject", choices=["math", "chinese", "english"])
    p_upd.add_argument("--current-unit", type=int)
    p_upd.add_argument("--difficulty", choices=list(VALID_DIFFICULTIES))
    p_upd.add_argument("--edition")
    p_upd.set_defaults(func=cmd_update)

    p_fr = sub.add_parser("check-freshness", help="检查教材元数据校对日期是否超过 6 个月")
    p_fr.add_argument("--date", help="按指定日期检查（YYYY-MM-DD）")
    p_fr.add_argument("--max-days", type=int, default=180)
    p_fr.set_defaults(func=cmd_freshness)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
