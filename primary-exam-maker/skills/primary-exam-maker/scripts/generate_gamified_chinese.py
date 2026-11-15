#!/usr/bin/env python3
"""生成语文游戏化识字练习卡 JSON（连线、找朋友、猜字谜、看图选字）。

题目类型：
  lianxian    — 看拼音连线（词语 ↔ 拼音）
  zhaopengyou — 找朋友（单字 + 候选字，圈出能组词的字）
  caizimi     — 猜字谜（谜面 + 大方格填字）
  tupian_xuanzi — 看图选字（图意描述 + 候选字）

注意：猜字谜（caizimi）和看图选字（tupian_xuanzi）的谜面与图意描述
需要由模型根据字义撰写，本脚本只生成框架（连线、找朋友可全自动生成）。

用法:
  python3 generate_gamified_chinese.py --grade 2 --term up --units 1,2 --type lianxian --count 5 -o game.json
  python3 generate_gamified_chinese.py --grade 2 --term up --units 1,2 --type zhaopengyou --count 4 -o game.json
  python3 generate_gamified_chinese.py --grade 2 --term up --type mixed --count 8 -o game.json

生成结果通过 validate_exam.py 校验后，用 render_exam.py 渲染为孩子卷/答案卷。
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import date
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
CURRICULUM = SKILL_DIR / "data" / "curriculum"

# 二字词拼音表（有限内置，用于自动生成连线题）
# 格式: 词语 -> 拼音（声调用数字标注，渲染时仍显示原字；这里只做提示，不渲染拼音）
# 实际连线题展示汉字↔拼音，拼音由 tables 中的信息推导
# 注意：本脚本只用词语本身，拼音需要模型补充或从教材获取
# 此处留空，连线题的两列都由词语对/词语↔释义对生成

GRADE_CN = {2: "二", 3: "三"}

PLACEHOLDER_RIDDLES = [
    "一口咬掉牛尾巴（打一字）",
    "日月同辉（打一字）",
    "八十八（打一字）",
    "二小（打一字）",
    "一人守门口（打一字）",
    "一加一（打一字）",
    "心字缺一点（打一字）",
    "人在云上走（打一字）",
]

PLACEHOLDER_RIDDLE_ANSWERS = ["告", "明", "米", "尘", "闪", "王", "必", "仙"]

PLACEHOLDER_SCENE_DESCS = [
    "图中画着一只小（  ）在池塘边唱歌。",
    "图上有一朵（  ）开在绿色的枝头。",
    "图中小朋友在（  ）下面乘凉。",
    "画面里有一只（  ）在水面上飞翔。",
    "图中一棵大（  ）长在山坡上。",
]


def parse_units(spec: str | None) -> list[int] | None:
    if not spec:
        return None
    units = []
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            units.extend(range(int(a), int(b) + 1))
        else:
            units.append(int(part))
    return sorted(set(units))


def load_tables(grade: int, term: str) -> dict:
    p = CURRICULUM / "chinese" / f"chinese_g{grade}_{term}_tables.json"
    return json.loads(p.read_text(encoding="utf-8"))


def load_curriculum(grade: int, term: str) -> dict:
    p = CURRICULUM / "chinese" / f"chinese_g{grade}_{term}.json"
    return json.loads(p.read_text(encoding="utf-8"))


def lesson_to_unit(curriculum: dict) -> dict[tuple[str, int], int]:
    mapping: dict[tuple[str, int], int] = {}
    for unit in curriculum["units"]:
        kind = unit.get("kind", "阅读")
        for item in unit.get("items", []):
            if item.get("type") == "lesson" and item.get("no") is not None:
                mapping[(kind, item["no"])] = unit["no"]
    return mapping


def collect_words(grade: int, term: str, units: list[int] | None, mode: str = "words") -> list[dict]:
    tables = load_tables(grade, term)
    curriculum = load_curriculum(grade, term)
    l2u = lesson_to_unit(curriculum)

    out = []
    for section in tables["tables"].get(mode, []):
        if section.get("garden"):
            continue
        unit = l2u.get((section.get("section"), section.get("no")))
        if unit is None:
            continue
        if units and unit not in units:
            continue
        for word in section.get("items", []):
            out.append({"text": word, "unit": unit})

    # dedup
    seen: set[str] = set()
    deduped = []
    for w in out:
        if w["text"] not in seen:
            seen.add(w["text"])
            deduped.append(w)
    return deduped


def collect_chars(grade: int, term: str, units: list[int] | None, mode: str = "writing") -> list[dict]:
    """收集写字表或识字表中的单字。"""
    tables = load_tables(grade, term)
    curriculum = load_curriculum(grade, term)
    l2u = lesson_to_unit(curriculum)

    out = []
    for section in tables["tables"].get(mode, []):
        if section.get("garden"):
            continue
        unit = l2u.get((section.get("section"), section.get("no")))
        if unit is None:
            continue
        if units and unit not in units:
            continue
        for ch in section.get("items", []):
            out.append({"text": ch, "unit": unit})

    seen: set[str] = set()
    deduped = []
    for c in out:
        if c["text"] not in seen:
            seen.add(c["text"])
            deduped.append(c)
    return deduped


def find_similar_chars(char: str, all_chars: list[dict], count: int, r: random.Random) -> list[str]:
    """从字库里选出 count 个与 char 形似/音似的候选字（简单策略：随机抽取池中其他字）。"""
    others = [c["text"] for c in all_chars if c["text"] != char]
    if len(others) < count:
        # 补充一些常见字
        fallback = list("木水火土日月山川人口手足心目")
        for fb in fallback:
            if fb not in others and fb != char:
                others.append(fb)
    r.shuffle(others)
    return others[:count]


def build_lianxian_items(words: list[dict], count: int, r: random.Random, unit_ref: int | None) -> list[dict]:
    """连线题：词语 ↔ 词语（同义词对 or 相关词对）。
    自动策略：从词语表里按对抽取，左列=原词，右列=乱序后的另一批同义/相关词（无法自动匹配时右列=每个词倒着写作演示）。
    真实使用时，模型应替换 right 列为准确对应的拼音/释义/近义词。"""
    if len(words) < count * 2:
        count = len(words) // 2
    if count < 2:
        raise ValueError("可用词语不足以生成连线题（至少需要 4 个词语）")

    r.shuffle(words)
    pairs = [(words[i * 2]["text"], words[i * 2 + 1]["text"]) for i in range(count)]

    items = []
    for i, (l, right_word) in enumerate(pairs, 1):
        unit = words[i * 2 - 2]["unit"] if i * 2 - 2 < len(words) else (unit_ref or 1)
        # 生成右列（乱序）
        left_col = ",".join(p[0] for p in pairs)
        right_col = ",".join(p[1] for p in pairs)
        stem = "{{lianxian left=\"%s\" right=\"%s\"}}" % (left_col, right_col)
        items.append({
            "id": f"lx{i}",
            "no": i,
            "stem": stem,
            "type": "连线",
            "points": 1,
            "unit": unit,
            "ability": "掌握",
            "tier": "基础",
            "answer": "见连线答案",
            "scoring_rules": f"每对连线正确得 {round(1/count, 2) if count else 1} 分，共 {count} 对，合计 1 分。",
            "hint": "读一读左边的词，再找到右边对应的词，用铅笔连一条线。",
            "knowledge_points": ["待归类"],
        })
        # 一道连线题只需一个 item（整个连线表是一道题）
        break

    # 返回时把 points 改为整题 count 分（count 对，每对 1 分）
    item = items[0]
    item["points"] = count
    item["scoring_rules"] = f"每条线正确得 1 分，共 {count} 条。"
    return [item]


def build_zhaopengyou_items(chars: list[dict], count: int, r: random.Random, all_chars: list[dict]) -> list[dict]:
    """找朋友：每题给一个核心字 + 若干候选字（含干扰字），圈出能组词的字。"""
    r.shuffle(chars)
    items = []
    used = set()
    for i, ch_entry in enumerate(chars):
        if len(items) >= count:
            break
        ch = ch_entry["text"]
        if ch in used:
            continue
        used.add(ch)
        # 答案字：同单元的另外 2-3 个字（能与 ch 组词，此处无法自动验证，标注"待确认"）
        same_unit = [c for c in chars if c["unit"] == ch_entry["unit"] and c["text"] != ch and c["text"] not in used]
        r.shuffle(same_unit)
        answer_chars = [c["text"] for c in same_unit[:2]]
        if not answer_chars:
            answer_chars = [ch]  # fallback
        # 干扰字：从其他字里取
        distractor_chars = find_similar_chars(ch, all_chars, 4, r)
        all_cands = answer_chars + distractor_chars
        r.shuffle(all_cands)
        all_cands = all_cands[:6]

        answers_str = ",".join(answer_chars)
        candidates_str = ",".join(all_cands)
        stem = "{{zhaopengyou char=\"%s\" candidates=\"%s\"}}" % (ch, candidates_str)

        items.append({
            "id": f"zpf{len(items)+1}",
            "no": len(items) + 1,
            "stem": stem,
            "type": "找朋友",
            "points": 1,
            "unit": ch_entry["unit"],
            "ability": "掌握",
            "tier": "基础",
            "answer": f"与「{ch}」能组词的字：{answers_str}（家长核对）",
            "scoring_rules": "全部圈对得 1 分；有漏圈或错圈不得分。",
            "hint": f"想一想「{ch}」能和哪些字组成词语？先读一读候选字，再圈出来。",
            "knowledge_points": ["待归类"],
        })
    return items


def build_caizimi_items(chars: list[dict], count: int, r: random.Random) -> list[dict]:
    """猜字谜：使用内置谜面（生产时由模型按实际字替换）。"""
    r.shuffle(chars)
    items = []
    riddles = list(zip(PLACEHOLDER_RIDDLES, PLACEHOLDER_RIDDLE_ANSWERS))
    r.shuffle(riddles)
    for i in range(min(count, len(riddles))):
        riddle_text, ans = riddles[i]
        unit = chars[i]["unit"] if i < len(chars) else 1
        stem = "{{caizimi riddle=\"%s\"}}" % riddle_text
        items.append({
            "id": f"czm{i+1}",
            "no": i + 1,
            "stem": stem,
            "type": "猜字谜",
            "points": 1,
            "unit": unit,
            "ability": "理解",
            "tier": "基础",
            "answer": ans,
            "scoring_rules": "猜对得 1 分。",
            "hint": f"把谜面分成几个部分，分别想想每部分像什么字，再组合起来。答案是「{ans}」。",
            "knowledge_points": ["待归类"],
        })
    return items


def build_tupian_xuanzi_items(words: list[dict], count: int, r: random.Random, all_chars: list[dict]) -> list[dict]:
    """看图选字：使用内置场景描述（生产时由模型替换为真实图意）。"""
    r.shuffle(words)
    items = []
    scenes = list(PLACEHOLDER_SCENE_DESCS)
    r.shuffle(scenes)
    for i in range(min(count, len(scenes))):
        entry = words[i] if i < len(words) else words[0]
        answer_char = entry["text"][0] if len(entry["text"]) >= 1 else "字"
        desc = scenes[i]
        # 候选字：答案字 + 2 个干扰字
        distractors = find_similar_chars(answer_char, all_chars, 2, r)
        cands = [answer_char] + distractors
        r.shuffle(cands)
        candidates_str = ",".join(cands)
        stem = "{{tupian_xuanzi desc=\"%s\" candidates=\"%s\"}}" % (desc, candidates_str)
        items.append({
            "id": f"txz{i+1}",
            "no": i + 1,
            "stem": stem,
            "type": "看图选字",
            "points": 1,
            "unit": entry["unit"],
            "ability": "理解",
            "tier": "基础",
            "answer": answer_char,
            "scoring_rules": "选对得 1 分。",
            "hint": f"看看图里画了什么，再想想哪个字放进括号里意思最通顺。答案是「{answer_char}」。",
            "knowledge_points": ["待归类"],
        })
    return items


def build_exam(args: argparse.Namespace) -> dict:
    units = parse_units(args.units)
    r = random.Random(args.seed)

    words = collect_words(args.grade, args.term, units)
    chars_writing = collect_chars(args.grade, args.term, units, "writing")
    chars_literacy = collect_chars(args.grade, args.term, units, "literacy")
    all_chars = chars_writing + [c for c in chars_literacy if c["text"] not in {x["text"] for x in chars_writing}]

    if not words:
        raise ValueError(f"没有找到符合条件的词语，请检查 --units 参数")

    exam_type = args.type
    sections: list[dict] = []
    total_points = 0

    def _add_section(sid: str, name: str, items: list[dict]) -> None:
        nonlocal total_points
        pts = sum(it["points"] for it in items)
        total_points += pts
        for i, it in enumerate(items, 1):
            it["id"] = f"{sid}{i}"
            it["no"] = i
        sections.append({
            "id": sid,
            "name": name,
            "points": pts,
            "instructions": _INSTRUCTIONS[sid],
            "items": items,
        })

    _INSTRUCTIONS = {
        "lianxian": "把左边的词语和右边正确的词语用线连起来。",
        "zhaopengyou": "找出能和中间的字组成词语的字，圈起来。",
        "caizimi": "读谜面，猜出谜底，把答案写在方框里。",
        "tupian_xuanzi": "读一读句子，从方框里选出正确的字填入括号。",
    }

    if exam_type == "lianxian" or exam_type == "mixed":
        items = build_lianxian_items(list(words), args.count if exam_type != "mixed" else max(1, args.count // 4), r, None)
        _add_section("lianxian", "连线", items)

    if exam_type == "zhaopengyou" or exam_type == "mixed":
        n = args.count if exam_type != "mixed" else max(1, args.count // 4)
        items = build_zhaopengyou_items(list(chars_writing), n, r, all_chars)
        if items:
            _add_section("zhaopengyou", "找朋友", items)

    if exam_type == "caizimi" or exam_type == "mixed":
        n = args.count if exam_type != "mixed" else max(1, args.count // 4)
        items = build_caizimi_items(list(all_chars), n, r)
        if items:
            _add_section("caizimi", "猜字谜", items)

    if exam_type == "tupian_xuanzi" or exam_type == "mixed":
        n = args.count if exam_type != "mixed" else max(1, args.count // 4)
        items = build_tupian_xuanzi_items(list(words), n, r, all_chars)
        if items:
            _add_section("tupian_xuanzi", "看图选字", items)

    if not sections:
        raise ValueError("没有生成任何题目，请检查参数")

    grade_cn = GRADE_CN.get(args.grade, str(args.grade))
    term_cn = "上" if args.term == "up" else "下"
    units_str = "、".join(str(u) for u in (units or [])) or "全册"
    title = args.title or f"{grade_cn}年级语文{term_cn}册 · 第 {units_str} 单元游戏识字练习"
    exam_id = args.exam_id or f"gamified-chinese-g{args.grade}-{args.term}-{date.today():%Y%m%d}"
    child = {}
    if args.child_id or args.child_nickname:
        child = {"id": args.child_id or "", "nickname": args.child_nickname or "", "grade": args.grade, "term": args.term}

    all_units = sorted({it["unit"] for sec in sections for it in sec["items"]})

    return {
        "schema": 1,
        "exam_id": exam_id,
        "created_at": args.created_at or date.today().isoformat(),
        "child": child,
        "subject": "chinese",
        "kind": "topic",
        "title": title,
        "scope": {
            "grade": args.grade,
            "term": args.term,
            "units": units or all_units,
            "textbook_edition": "统编版",
        },
        "difficulty_level": "basic",
        "total_points": total_points,
        "suggested_minutes": max(5, round(total_points / 5) * 5),
        "sections": sections,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--grade", type=int, required=True, choices=[2, 3])
    ap.add_argument("--term", required=True, choices=["up", "down"])
    ap.add_argument("--units", help="单元范围，如 1,2 或 1-3")
    ap.add_argument("--type", required=True,
                    choices=["lianxian", "zhaopengyou", "caizimi", "tupian_xuanzi", "mixed"],
                    help="题型（mixed 四种各出 count//4 题）")
    ap.add_argument("--count", type=int, default=4, help="题目数量（默认 4；lianxian 每题为一组连线，建议 3-5）")
    ap.add_argument("--seed", type=int, help="随机种子")
    ap.add_argument("--title")
    ap.add_argument("--exam-id")
    ap.add_argument("--child-id")
    ap.add_argument("--child-nickname")
    ap.add_argument("--created-at")
    ap.add_argument("-o", "--out", type=Path, required=True)
    args = ap.parse_args()

    try:
        data = build_exam(args)
    except (ValueError, FileNotFoundError) as e:
        ap.error(str(e))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    total = sum(len(s["items"]) for s in data["sections"])
    print(f"OK: {args.out}  {total} 题  {data['total_points']} 分")
    print("⚠️  caizimi/tupian_xuanzi 题目的谜面/图意为占位示例，模型使用前请按实际字义替换。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
