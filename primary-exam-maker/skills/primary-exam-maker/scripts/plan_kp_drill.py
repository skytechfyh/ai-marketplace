#!/usr/bin/env python3
"""知识点专项（F8）规划：读取知识点详情，按“理解→基础练→变式→综合”分配题数。

用法:
  python3 plan_kp_drill.py --subject math --grade 2 --term up --kp M2U-1-05 --count 20
  python3 plan_kp_drill.py --subject chinese --grade 3 --term down --unit 1 --count 15 --json
"""
import argparse
import json
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
DATA = SKILL_DIR / "data"
GRADIENT = [("理解", 0.15), ("基础练", 0.40), ("变式", 0.30), ("综合", 0.15)]


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def allocate(count: int) -> dict[str, int]:
    raw = [(name, count * ratio) for name, ratio in GRADIENT]
    out = {name: int(v) for name, v in raw}
    remain = count - sum(out.values())
    for name, v in sorted(raw, key=lambda x: x[1] - int(x[1]), reverse=True):
        if remain <= 0:
            break
        out[name] += 1
        remain -= 1
    if count >= 4:
        for name in ("理解", "综合"):
            if out[name] == 0:
                donor = max(out, key=lambda k: out[k])
                out[donor] -= 1
                out[name] += 1
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--subject", required=True, choices=["math", "chinese", "english"])
    ap.add_argument("--grade", type=int, required=True, choices=[2, 3])
    ap.add_argument("--term", required=True, choices=["up", "down"])
    ap.add_argument("--kp", help="知识点 ID，多个用逗号分隔")
    ap.add_argument("--unit", type=int, help="按单元取知识点（与 --kp 二选一）")
    ap.add_argument("--count", type=int, default=20, help="总题数（默认 20）")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    path = DATA / "knowledge" / args.subject / f"{args.subject}_g{args.grade}_{args.term}.json"
    if not path.exists():
        ap.error(f"缺少知识点目录：{path}（先铺开本册知识点）")
    data = load_json(path)
    all_kps = {k["id"]: k for k in data["knowledge_points"]}
    if args.kp:
        ids = [x.strip() for x in args.kp.split(",") if x.strip()]
        missing = [x for x in ids if x not in all_kps]
        if missing:
            ap.error(f"知识点不存在：{missing}")
        chosen = [all_kps[x] for x in ids]
    elif args.unit is not None:
        chosen = [k for k in data["knowledge_points"] if k["unit"] == args.unit]
        if not chosen:
            ap.error(f"第 {args.unit} 单元没有知识点")
    else:
        ap.error("需要 --kp 或 --unit")

    plan = {
        "subject": args.subject,
        "grade": args.grade,
        "term": args.term,
        "count": args.count,
        "gradient": allocate(args.count),
        "knowledge_points": chosen,
        "related": [],
        "notes": [
            "理解：1–2 道判断/填空考概念与算理，答案卷附讲解要点",
            "基础练：核心题型，基础档，保证熟练",
            "变式：换数据/情境，覆盖 error_types 中的易错点",
            "综合：与前置或同单元相邻知识点结合，含 1 道中档/拔高考题；难度等级可调",
        ],
    }
    chosen_ids = {k["id"] for k in chosen}
    related = {}
    for kp in chosen:
        for pid in kp.get("prereq", []):
            if pid in all_kps and pid not in chosen_ids:
                related[pid] = all_kps[pid]
        for other in data["knowledge_points"]:
            if other["unit"] == kp["unit"] and other["id"] not in chosen_ids and other["id"] != kp["id"]:
                related.setdefault(other["id"], other)
    plan["related"] = list(related.values())[:6]

    if args.json:
        print(json.dumps(plan, ensure_ascii=False, indent=1))
        return 0

    print(f"# 知识点专项规划（{args.count} 题）\n")
    print("## 梯度分配\n")
    for name, n in plan["gradient"].items():
        print(f"- {name}：{n} 题")
    print("\n## 目标知识点\n")
    for kp in chosen:
        print(f"### `{kp['id']}` {kp['name']}（第 {kp['unit']} 单元 · {kp['level']}）")
        print(f"- 页码：{kp.get('pages')} ｜ 课标：{'；'.join(kp.get('std', []))}")
        print(f"- 掌握标准：{kp['mastery']}")
        print(f"- 典型错因：{'；'.join(kp.get('error_types', []))}")
        print(f"- 适用题型：{'、'.join(kp.get('item_types', []))}")
        print(f"- 前置：{'、'.join(kp.get('prereq') or ['无'])}\n")
    if plan["related"]:
        print("## 可结合的相关知识点\n")
        for kp in plan["related"]:
            print(f"- `{kp['id']}` {kp['name']}（第 {kp['unit']} 单元）")
    print("\n## 出题提醒\n")
    for n in plan["notes"]:
        print(f"- {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
