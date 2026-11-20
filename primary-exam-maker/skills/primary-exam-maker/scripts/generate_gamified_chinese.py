#!/usr/bin/env python3
"""生成语文游戏化识字练习卡 JSON（找朋友、连线、猜字谜、看图选字）。

题目类型：
  zhaopengyou   — 找朋友（单字 + 候选字，圈出能组词的字；基于本册词语表全自动生成真实组词答案）
  lianxian      — 连线（词语 ↔ 拼音/近反义词/释义；脚本生成左列词框架，右列与答案须模型补全）
  caizimi       — 猜字谜（谜面 + 大方格填字；脚本生成框架，谜面与答案须模型按本册字义替换）
  tupian_xuanzi — 看图选字（图意描述 + 候选字；脚本生成框架，描述与答案须模型按本册内容替换）

用法:
  python3 generate_gamified_chinese.py --grade 2 --term up --units 1,2 --type zhaopengyou --count 4 -o game.json
  python3 generate_gamified_chinese.py --grade 2 --term up --units 1,2 --type lianxian --count 5 -o game.json
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
    """连线题框架：左列从本册词语表抽取，右列为占位项，出卷前须由模型替换为真实拼音/近反义词/释义。"""
    n_pairs = min(count, len(words), 10)
    if n_pairs < 2:
        raise ValueError("可用词语不足以生成连线题（至少需要 2 个词语）")

    pool = list(words)
    r.shuffle(pool)
    chosen = pool[:n_pairs]
    left_col = ",".join(w["text"] for w in chosen)
    right_col = ",".join(f"待补·{w['text']}" for w in chosen)
    stem = '{{lianxian left="%s" right="%s"}}' % (left_col, right_col)
    unit = chosen[0]["unit"] if chosen else (unit_ref or 1)

    return [{
        "id": "lx1",
        "no": 1,
        "stem": stem,
        "type": "连线",
        "points": n_pairs,
        "unit": unit,
        "ability": "掌握",
        "tier": "基础",
        "answer": "待模型补全真实配对（如词语↔拼音/近反义词/释义）后填写对应答案",
        "scoring_rules": f"每条线正确得 1 分，共 {n_pairs} 条。",
        "hint": "读一读左边的词，再找到右边对应的项，用铅笔连一条线。",
        "knowledge_points": ["待归类"],
    }]


def _build_word_partner_map(word_entries: list[dict]) -> dict[str, list[tuple[str, str, int]]]:
    """从教材二字词语表反推真实可组词映射：char -> [(partner_char, word, unit), ...]。"""
    partners: dict[str, dict[str, tuple[str, int]]] = {}
    for entry in word_entries:
        w = entry["text"].strip()
        if len(w) != 2 or w[0] == w[1]:
            continue
        a, b = w[0], w[1]
        u = entry["unit"]
        partners.setdefault(a, {}).setdefault(b, (w, u))
        partners.setdefault(b, {}).setdefault(a, (w, u))
    return {
        ch: [(p, wu[0], wu[1]) for p, wu in pmap.items()]
        for ch, pmap in partners.items()
    }


def build_zhaopengyou_items(
    chars: list[dict],
    count: int,
    r: random.Random,
    all_chars: list[dict],
    unit_words: list[dict],
    all_words: list[dict],
) -> list[dict]:
    """找朋友（全自动）：从本册词语表反推真实可组词的伙伴字，排除会误成词的干扰字。"""
    unit_map = _build_word_partner_map(unit_words)
    full_map = _build_word_partner_map(all_words)
    allowed_units = {w["unit"] for w in unit_words}
    unit_char_units = {c["text"]: c["unit"] for c in chars}

    # 优先选当前单元内有 >=2 个真实组词伙伴的字，其次放宽到全册词语表中能与本单元字组词的字
    tier1 = [ch for ch, ps in unit_map.items() if len(ps) >= 2]
    tier2 = [
        ch for ch, ps in full_map.items()
        if ch not in tier1 and (ch in unit_char_units or any(u in allowed_units for _, _, u in ps)) and len(ps) >= 2
    ]
    tier3 = [ch for ch, ps in unit_map.items() if ch not in tier1 and ch not in tier2 and len(ps) >= 1]
    r.shuffle(tier1)
    r.shuffle(tier2)
    r.shuffle(tier3)
    candidates_order = tier1 + tier2 + tier3

    items: list[dict] = []
    for ch in candidates_order:
        if len(items) >= count:
            break
        # 优先使用本单元词语表里的伙伴，不足再从全册词语表补
        u_partners = list(unit_map.get(ch, []))
        r.shuffle(u_partners)
        chosen_partners = list(u_partners[:3])
        if len(chosen_partners) < 2:
            seen_p = {p for p, _, _ in chosen_partners}
            extra = [x for x in full_map.get(ch, []) if x[0] not in seen_p]
            r.shuffle(extra)
            chosen_partners.extend(extra[: 2 - len(chosen_partners)])
        if not chosen_partners:
            continue

        answer_chars = [p for p, _, _ in chosen_partners]
        # 干扰字不得与 ch 在全册词语表中组成真实词语，也不得与 ch 或答案字重复
        forbidden = {ch} | {p for p, _, _ in full_map.get(ch, [])} | set(answer_chars)
        distractor_pool = [c["text"] for c in all_chars if c["text"] not in forbidden]
        r.shuffle(distractor_pool)
        n_distractors = max(2, 6 - len(answer_chars))
        distractors: list[str] = []
        for d in distractor_pool:
            if d not in distractors:
                distractors.append(d)
            if len(distractors) >= n_distractors:
                break
        if len(distractors) < 2:
            for fb in "木水火土日月山川人口手足心目":
                if fb not in forbidden and fb not in distractors:
                    distractors.append(fb)
                if len(distractors) >= n_distractors:
                    break

        all_cands = answer_chars + distractors
        r.shuffle(all_cands)

        pair_desc = "、".join(f"{p}（{w}）" for p, w, _ in chosen_partners)
        answers_str = "、".join(answer_chars)
        stem = '{{zhaopengyou char="%s" candidates="%s"}}' % (ch, ",".join(all_cands))
        item_unit = unit_char_units.get(ch) or chosen_partners[0][2]

        items.append({
            "id": f"zpf{len(items)+1}",
            "no": len(items) + 1,
            "stem": stem,
            "type": "找朋友",
            "points": 1,
            "unit": item_unit,
            "ability": "掌握",
            "tier": "基础",
            "answer": pair_desc,
            "scoring_rules": f"全部圈对（{answers_str}）得 1 分；有漏圈或错圈不得分。",
            "hint": f"想一想「{ch}」能和哪些字组成课本学过的词语？先读一读候选字，再圈出来。",
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
    all_words = collect_words(args.grade, args.term, None) if units else words
    chars_writing = collect_chars(args.grade, args.term, units, "writing")
    chars_literacy = collect_chars(args.grade, args.term, units, "literacy")
    all_chars = chars_writing + [c for c in chars_literacy if c["text"] not in {x["text"] for x in chars_writing}]

    if not words:
        raise ValueError("没有找到符合条件的词语，请检查 --units 参数")

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
        "lianxian": "把左边的词语和右边对应的项用线连起来。",
        "zhaopengyou": "找出能和中间的字组成课本词语的字，圈起来。",
        "caizimi": "读谜面，猜出谜底，把答案写在方框里。",
        "tupian_xuanzi": "读一读句子，从方框里选出正确的字填入括号。",
    }

    if exam_type == "lianxian" or exam_type == "mixed":
        n_lx = args.count if exam_type != "mixed" else max(2, args.count // 4)
        items = build_lianxian_items(list(words), n_lx, r, None)
        _add_section("lianxian", "连线", items)

    if exam_type == "zhaopengyou" or exam_type == "mixed":
        n = args.count if exam_type != "mixed" else max(1, args.count // 4)
        items = build_zhaopengyou_items(list(chars_writing), n, r, all_chars, words, all_words)
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
                    help="题型（zhaopengyou 全自动生成真实组词；其余题型生成框架需模型补全）")
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
    if args.type in ("lianxian", "caizimi", "tupian_xuanzi", "mixed"):
        print("⚠️  lianxian/caizimi/tupian_xuanzi 为占位框架，出卷前须由模型补全真实配对/谜面/图意与答案后再渲染。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
