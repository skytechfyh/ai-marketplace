#!/usr/bin/env python3
"""生成口算卡中间格式 JSON（答案由代码计算，保证正确；同卷题干去重）。

用法:
  python3 generate_oral_math.py --grade 2 --term up --count 50 -o oral.json
  python3 generate_oral_math.py --grade 3 --term down --topics mul_2digit,fraction --count 30 -o oral.json
  python3 generate_oral_math.py --grade 2 --term up --units 1,2 --count 20 -o oral.json

生成结果通过 validate_exam.py 校验后，用 render_exam.py 渲染为分离的孩子卷/答案卷。
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import date
from pathlib import Path

# 各主题的单元归属（按册）；用于 --units 过滤与题目 unit 字段
TOPIC_UNITS = {
    (2, "up"): {
        "mul": [1, 3],
        "div": [2],
        "add100": [5],
        "rem": [6],
        "mix": [1],
    },
    (2, "down"): {
        "mul_1digit": [3],
        "div_1digit": [3],
        "add1000": [6],
    },
    (3, "up"): {
        "add1000": [1, 7],
        "mul_1digit": [2],
        "div_1digit": [6],
        "mix": [1],
    },
    (3, "down"): {
        "mul_2digit": [3],
        "add1000": [2],
        "fraction": [6],
    },
}

TOPIC_NAMES = {
    "mul": "表内乘法",
    "div": "表内除法",
    "rem": "有余数除法",
    "add100": "100 以内加减法",
    "add1000": "万以内加减法",
    "mul_1digit": "两、三位数乘一位数",
    "div_1digit": "两、三位数除以一位数",
    "mul_2digit": "两位数乘两位数",
    "fraction": "同分母分数加减",
    "mix": "两步混合运算",
}

TOPIC_HINTS = {
    "mul": "想一想对应的乘法口诀。",
    "div": "想乘法口诀：几乘除数等于被除数。",
    "rem": "先想除数的乘法口诀，找出最接近且不超过被除数的积；余数必须比除数小。",
    "add100": "相同数位对齐，注意进位和退位。",
    "add1000": "整十、整百数相加，先想有几个十或几个百。",
    "mul_1digit": "先算整十、整百部分，再算个位部分。",
    "div_1digit": "想乘法口诀，或把被除数拆成几个百、几个十。",
    "mul_2digit": "先不看末尾的 0，用口诀算，再在积的末尾添 0。",
    "fraction": "分母不变，分子相加减；结果能约分的暂不要求约分。",
    "mix": "先算乘法，再算加减。",
}


def _mul(r: random.Random, _grade: int | None = None) -> tuple[str, str]:
    # 以 2~9 的口诀为主，0 和 1 的乘法少量穿插
    if r.random() < 0.2:
        a, b = r.choice([0, 1, 2, 3, 4, 5, 6, 7, 8, 9]), r.randint(0, 9)
    else:
        a, b = r.randint(2, 9), r.randint(2, 9)
    return f"{a} × {b} = ______", str(a * b)


def _div(r: random.Random, _grade: int | None = None) -> tuple[str, str]:
    a, q = r.randint(2, 9), r.randint(1, 9)
    b = a * q
    return f"{b} ÷ {a} = ______", str(q)


def _rem(r: random.Random, _grade: int | None = None) -> tuple[str, str]:
    a = r.randint(2, 9)
    q = r.randint(1, 9)
    rem = r.randint(1, a - 1)
    b = a * q + rem
    return f"{b} ÷ {a} = ______ 余 ______", f"{q}……{rem}"


def _add100(r: random.Random, _grade: int | None = None) -> tuple[str, str]:
    if r.random() < 0.5:
        a = r.randint(10, 80)
        b = r.randint(10, 100 - a)
        return f"{a} + {b} = ______", str(a + b)
    a = r.randint(20, 99)
    b = r.randint(10, a - 1)
    return f"{a} − {b} = ______", str(a - b)


def _add1000(r: random.Random, grade: int | None = None) -> tuple[str, str]:
    if grade == 2:
        # 二下：两、三位数加减（1000 以内，整十数口算）
        if r.random() < 0.5:
            a = r.randint(10, 80) * 10
            b = r.randint(10, 100 - a // 10) * 10
            return f"{a} + {b} = ______", str(a + b)
        a = r.randint(20, 99) * 10
        b = r.randint(1, a // 10 - 1) * 10
        return f"{a} − {b} = ______", str(a - b)
    if r.random() < 0.5:
        a = r.randint(2, 50) * 100
        b = r.randint(2, 50) * 100
        return f"{a} + {b} = ______", str(a + b)
    a = r.randint(10, 99) * 100
    b = r.randint(1, a // 100 - 1) * 100
    return f"{a} − {b} = ______", str(a - b)


def _mul_1digit(r: random.Random, grade: int | None = None) -> tuple[str, str]:
    b = r.randint(2, 9)
    if grade == 2 or r.random() < 0.6:
        a = r.randint(2, 9) * 10  # 二下：两位数乘一位数（整十数）
    else:
        a = r.randint(1, 9) * 100  # 三上：整百数乘一位数
    return f"{a} × {b} = ______", str(a * b)


def _div_1digit(r: random.Random, grade: int | None = None) -> tuple[str, str]:
    b = r.randint(2, 9)
    q = r.randint(2, 9) * (10 if grade == 2 or r.random() < 0.6 else 100)
    return f"{q * b} ÷ {b} = ______", str(q)


def _mul_2digit(r: random.Random, _grade: int | None = None) -> tuple[str, str]:
    a = r.randint(2, 9) * 10
    b = r.randint(2, 9) * 10 if r.random() < 0.5 else r.randint(11, 50)
    return f"{a} × {b} = ______", str(a * b)


def _fraction(r: random.Random, _grade: int | None = None) -> tuple[str, str]:
    d = r.randint(3, 10)
    if r.random() < 0.5:
        a = r.randint(1, d - 1)
        b = r.randint(1, d - a)
        return f"{a}/{d} + {b}/{d} = ______", f"{a + b}/{d}"
    a = r.randint(2, d - 1)
    b = r.randint(1, a - 1)
    return f"{a}/{d} − {b}/{d} = ______", f"{a - b}/{d}"


def _mix(r: random.Random, _grade: int | None = None) -> tuple[str, str]:
    a, b = r.randint(2, 9), r.randint(2, 9)
    c = r.randint(1, 30)
    if r.random() < 0.5:
        return f"{a} × {b} + {c} = ______", str(a * b + c)
    c = r.randint(1, a * b)
    return f"{a} × {b} − {c} = ______", str(a * b - c)


GENERATORS = {
    "mul": _mul,
    "div": _div,
    "rem": _rem,
    "add100": _add100,
    "add1000": _add1000,
    "mul_1digit": _mul_1digit,
    "div_1digit": _div_1digit,
    "mul_2digit": _mul_2digit,
    "fraction": _fraction,
    "mix": _mix,
}


def parse_units(spec: str | None) -> list[int] | None:
    if not spec:
        return None
    units = []
    for part in spec.split(","):
        units.append(int(part.strip()))
    return sorted(set(units))


def choose_topics(grade: int, term: str, units: list[int] | None, topics_arg: str | None) -> dict[str, list[int]]:
    catalog = TOPIC_UNITS.get((grade, term))
    if catalog is None:
        raise ValueError(f"暂不支持 {grade} 年级{'上' if term == 'up' else '下'}册的口算卡")
    if topics_arg:
        wanted = [t.strip() for t in topics_arg.split(",") if t.strip()]
        unknown = [t for t in wanted if t not in catalog]
        if unknown:
            raise ValueError(f"主题 {unknown} 不适用于 {grade} 年级{'上' if term == 'up' else '下'}册；可用：{sorted(catalog)}")
        chosen = {t: catalog[t] for t in wanted}
    else:
        chosen = dict(catalog)
    if units:
        chosen = {
            t: sorted(set(us) & set(units))
            for t, us in chosen.items()
            if set(us) & set(units)
        }
    if not chosen:
        raise ValueError(f"单元范围 {units} 内没有可生成的口算主题；本册可用主题：{sorted(catalog)}")
    return chosen


def build_exam(args: argparse.Namespace) -> tuple[dict, list[str]]:
    units = parse_units(args.units)
    topics = choose_topics(args.grade, args.term, units, args.topics)
    topic_list = list(topics)
    r = random.Random(args.seed)
    counts = {t: args.count // len(topic_list) for t in topic_list}
    for i in range(args.count % len(topic_list)):
        counts[topic_list[i]] += 1

    items: list[dict] = []
    seen: set[str] = set()
    qno = 1
    for topic in topic_list:
        gen = GENERATORS[topic]
        made, attempts = 0, 0
        while made < counts[topic]:
            attempts += 1
            if attempts > 20000:
                raise ValueError(f"主题 {topic} 无法生成足够的不重复题目（需要 {counts[topic]} 题，已生成 {made} 题）")
            stem, answer = gen(r, args.grade)
            if stem in seen:
                continue
            seen.add(stem)
            items.append({
                "id": f"q{qno}",
                "no": qno,
                "stem": stem,
                "type": "口算",
                "points": 1,
                "unit": topics[topic][0],
                "ability": "运用" if topic == "mix" else "掌握",
                "tier": "基础",
                "answer": answer,
                "scoring_rules": "答案正确得 1 分；写错、漏写或余数不小于除数不得分。",
                "hint": TOPIC_HINTS[topic],
                "knowledge_points": ["待归类"],
            })
            qno += 1
            made += 1

    grade_cn = {2: "二", 3: "三"}.get(args.grade, str(args.grade)) + "年级"
    term_cn = "上" if args.term == "up" else "下"
    title = args.title or f"{grade_cn}{term_cn}册口算卡（{args.count} 题）"
    exam_id = args.exam_id or f"oral-math-g{args.grade}-{args.term}-{date.today():%Y%m%d}"
    child = {}
    if args.child_id or args.child_nickname:
        child = {"id": args.child_id or "", "nickname": args.child_nickname or "", "grade": args.grade, "term": args.term}

    r.shuffle(items)
    for i, it in enumerate(items, 1):
        it["id"] = f"q{i}"
        it["no"] = i

    exam = {
        "schema": 1,
        "exam_id": exam_id,
        "created_at": args.created_at or date.today().isoformat(),
        "child": child,
        "subject": "math",
        "kind": "oral_math",
        "title": title,
        "scope": {
            "grade": args.grade,
            "term": args.term,
            "units": units or sorted({u for us in topics.values() for u in us}),
            "textbook_edition": "苏教版",
        },
        "difficulty_level": "basic",
        "total_points": args.count,
        "suggested_minutes": max(5, round(args.count / 10) * 5),
        "sections": [{
            "id": "oral",
            "name": "口算",
            "points": args.count,
            "columns": args.columns,
            "instructions": f"直接写出得数，共 {args.count} 题，限时 {max(5, round(args.count / 10) * 5)} 分钟。",
            "items": items,
        }],
    }
    return exam, topic_list


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--grade", type=int, required=True, choices=[2, 3])
    ap.add_argument("--term", required=True, choices=["up", "down"])
    ap.add_argument("--units", help="单元范围，如 1,2,3；默认本册全部可出口算的单元")
    ap.add_argument("--topics", help=f"主题（逗号分隔），可用：{','.join(TOPIC_NAMES)}")
    ap.add_argument("--count", type=int, default=50, help="题目数量（默认 50）")
    ap.add_argument("--columns", type=int, default=3, choices=[2, 3], help="分栏数（默认 3）")
    ap.add_argument("--seed", type=int, help="随机种子；相同种子生成相同题目")
    ap.add_argument("--title")
    ap.add_argument("--exam-id")
    ap.add_argument("--child-id")
    ap.add_argument("--child-nickname")
    ap.add_argument("--created-at")
    ap.add_argument("-o", "--out", type=Path, required=True, help="输出 JSON 路径")
    args = ap.parse_args()

    if args.count <= 0:
        ap.error("--count 必须为正整数")
    try:
        data, topics = build_exam(args)
    except ValueError as e:
        ap.error(str(e))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"OK: {args.out}  {args.count} 题  主题：{', '.join(TOPIC_NAMES[t] for t in topics)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
