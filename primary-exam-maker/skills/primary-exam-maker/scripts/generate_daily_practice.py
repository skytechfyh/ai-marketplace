#!/usr/bin/env python3
"""生成每日练习卡 JSON——小型混合练习（当日新学 60% + 螺旋复习 40%），5-15 分钟完成。

数学：复用口算题生成器，按当前单元划分新学/复习主题。
语文：复用听写词库，按当前单元划分新学/复习词语。
英语：复用英语词库，按当前单元划分新学/复习单词。

用法:
  python3 generate_daily_practice.py --subject math --grade 2 --term up --current-unit 3 --count 10 -o daily.json
  python3 generate_daily_practice.py --subject chinese --grade 2 --term up --current-unit 3 --count 8 -o daily.json
  python3 generate_daily_practice.py --subject english --grade 3 --term up --current-unit 2 --count 8 -o daily.json
  python3 generate_daily_practice.py --subject math --grade 2 --term up --current-unit 3 --count 10 --child-id child1 --child-nickname 老大 -o daily.json

生成结果通过 validate_exam.py 校验后，用 render_exam.py 渲染为分离的孩子卷/答案卷。
"""
import argparse
import json
import random
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import generate_oral_math as oral
import generate_dictation as dic

SUBJECT_CN = {"math": "数学", "chinese": "语文", "english": "英语"}
GRADE_CN = {2: "二", 3: "三"}
REVIEW_RATIO = 0.4  # 复习题占比


def _gen_math_items(r, topics, count, grade, seen, start_no, force_unit=None):
    """从给定主题字典中生成指定数量的不重复口算题目。"""
    items = []
    topic_list = list(topics)
    counts = {t: count // len(topic_list) for t in topic_list}
    for i in range(count % len(topic_list)):
        counts[topic_list[i]] += 1
    qno = start_no
    for topic in topic_list:
        gen = oral.GENERATORS[topic]
        made, attempts = 0, 0
        while made < counts[topic]:
            attempts += 1
            if attempts > 20000:
                raise ValueError(f"主题 {topic} 无法生成足够不重复题目（需 {counts[topic]} 题）")
            stem, answer = gen(r, grade)
            if stem in seen:
                continue
            seen.add(stem)
            unit = force_unit if force_unit is not None else topics[topic][0]
            items.append({
                "id": f"q{qno}",
                "no": qno,
                "stem": stem,
                "type": "口算",
                "points": 1,
                "unit": unit,
                "ability": "运用" if topic == "mix" else "掌握",
                "tier": "基础",
                "answer": answer,
                "scoring_rules": "答案正确得 1 分；写错、漏写或余数不小于除数不得分。",
                "hint": oral.TOPIC_HINTS[topic],
                "knowledge_points": ["待归类"],
            })
            qno += 1
            made += 1
    return items


def build_math_items(args, r):
    """数学每日练习：新学 60% + 复习 40%。"""
    catalog = oral.TOPIC_UNITS.get((args.grade, args.term))
    if catalog is None:
        raise ValueError(f"暂不支持 {args.grade} 年级{'上' if args.term == 'up' else '下'}册的口算练习")

    cu = args.current_unit
    # 新学主题：当前单元在主题的单元列表中
    current_topics = {t: us for t, us in catalog.items() if cu in us}
    # 复习主题：当前单元不在列表中，但有单元在当前单元之前已学过
    review_topics = {t: us for t, us in catalog.items() if cu not in us and min(us) < cu}

    if not current_topics and not review_topics:
        raise ValueError(f"第 {cu} 单元没有可出口算练习的主题；本册可用：{sorted(catalog)}")

    if not current_topics:
        # 没有新学主题时全部做复习
        current_topics, review_topics = review_topics, {}

    if review_topics:
        n_current = max(1, round(args.count * (1 - REVIEW_RATIO)))
        n_review = args.count - n_current
    else:
        n_current, n_review = args.count, 0

    seen: set[str] = set()
    items = _gen_math_items(r, current_topics, n_current, args.grade, seen, 1, force_unit=args.current_unit)
    if review_topics and n_review > 0:
        items.extend(_gen_math_items(r, review_topics, n_review, args.grade, seen, len(items) + 1))

    r.shuffle(items)
    for i, it in enumerate(items, 1):
        it["id"] = f"q{i}"
        it["no"] = i

    return items


def _dedup_words(words: list[dict]) -> list[dict]:
    """按 text 去重，保留首次出现。"""
    seen: set[str] = set()
    out = []
    for w in words:
        if w["text"] not in seen:
            seen.add(w["text"])
            out.append(w)
    return out


def build_chinese_items(args, r):
    """语文每日练习：新学 60% + 复习 40%。"""
    ns = argparse.Namespace(grade=args.grade, term=args.term, mode=args.mode)
    all_words = dic.collect_chinese(ns)
    if not all_words:
        raise ValueError(f"没有找到 {args.grade} 年级{'上' if args.term == 'up' else '下'}册的听写词")

    cu = args.current_unit
    deduped = _dedup_words(all_words)
    current_pool = [w for w in deduped if w["unit"] == cu]
    review_pool = [w for w in deduped if w["unit"] < cu]

    if not current_pool and not review_pool:
        raise ValueError(f"第 {cu} 单元及之前没有听写词可用")

    if not current_pool:
        current_pool, review_pool = review_pool, []

    if review_pool:
        n_current = max(1, round(args.count * (1 - REVIEW_RATIO)))
        n_review = args.count - n_current
    else:
        n_current, n_review = args.count, 0

    chosen = []
    if len(current_pool) >= n_current:
        chosen.extend(r.sample(current_pool, n_current))
    else:
        chosen.extend(current_pool)
    if review_pool and n_review > 0:
        n_review = min(n_review, len(review_pool))
        chosen.extend(r.sample(review_pool, n_review))

    r.shuffle(chosen)

    items = []
    for qno, entry in enumerate(chosen, 1):
        text = entry["text"]
        stem = "{{tianzige n=%d}}" % max(2, len(text))
        items.append({
            "id": f"d{qno}",
            "no": qno,
            "stem": stem,
            "type": "听写",
            "points": 1,
            "unit": entry["unit"],
            "ability": "掌握",
            "tier": "基础",
            "answer": text,
            "scoring_rules": "写对得 1 分；错字、漏字、多字均不得分。",
            "hint": "家长读两遍：先读整个词语，再逐字读，最后连起来读一遍。",
            "knowledge_points": ["待归类"],
        })

    return items


def build_english_items(args, r):
    """英语每日练习：新学 60% + 复习 40%。"""
    ns = argparse.Namespace(grade=args.grade, term=args.term, include_noncore=False)
    all_words = dic.collect_english(ns)
    if not all_words:
        raise ValueError(f"没有找到 {args.grade} 年级{'上' if args.term == 'up' else '下'}册的英语单词")

    cu = args.current_unit
    deduped = _dedup_words(all_words)
    current_pool = [w for w in deduped if w["unit"] == cu]
    review_pool = [w for w in deduped if w["unit"] < cu]

    if not current_pool and not review_pool:
        raise ValueError(f"第 {cu} 单元及之前没有英语单词可用")

    if not current_pool:
        current_pool, review_pool = review_pool, []

    if review_pool:
        n_current = max(1, round(args.count * (1 - REVIEW_RATIO)))
        n_review = args.count - n_current
    else:
        n_current, n_review = args.count, 0

    chosen = []
    if len(current_pool) >= n_current:
        chosen.extend(r.sample(current_pool, n_current))
    else:
        chosen.extend(current_pool)
    if review_pool and n_review > 0:
        n_review = min(n_review, len(review_pool))
        chosen.extend(r.sample(review_pool, n_review))

    r.shuffle(chosen)

    items = []
    for qno, entry in enumerate(chosen, 1):
        stem = "{{fourline rows=1}}"
        items.append({
            "id": f"d{qno}",
            "no": qno,
            "stem": stem,
            "type": "听写",
            "points": 1,
            "unit": entry["unit"],
            "ability": "掌握",
            "tier": "基础",
            "answer": entry["text"],
            "scoring_rules": "拼写完全正确得 1 分；拼错、大小写错误不得分。",
            "hint": "家长读两遍单词，孩子先听再写；注意字母占格与大小写。",
            "knowledge_points": ["待归类"],
        })

    return items


def build_exam(args: argparse.Namespace) -> dict:
    r = random.Random(args.seed)

    if args.subject == "math":
        items = build_math_items(args, r)
        section_name = "口算"
        section_id = "oral"
        columns = args.columns
        instructions = f"直接写出得数，共 {len(items)} 题，限时 {max(5, round(len(items) / 10) * 5)} 分钟。"
        textbook = "苏教版"
    elif args.subject == "chinese":
        items = build_chinese_items(args, r)
        section_name = "听写"
        section_id = "dictation"
        columns = 2
        instructions = f"共 {len(items)} 个，家长按题号读，孩子写。"
        textbook = "统编版"
    else:  # english
        items = build_english_items(args, r)
        section_name = "听写"
        section_id = "dictation"
        columns = 2
        instructions = f"共 {len(items)} 个，家长按题号读，孩子写。"
        textbook = "译林版"

    grade_cn = GRADE_CN.get(args.grade, str(args.grade))
    term_cn = "上" if args.term == "up" else "下"
    subj_cn = SUBJECT_CN[args.subject]
    title = args.title or f"{grade_cn}年级{subj_cn}{term_cn}册 · 每日练习卡（{len(items)} 题）"
    exam_id = args.exam_id or f"daily-practice-{args.subject}-g{args.grade}-{args.term}-{date.today():%Y%m%d}"
    child = {}
    if args.child_id or args.child_nickname:
        child = {"id": args.child_id or "", "nickname": args.child_nickname or "", "grade": args.grade, "term": args.term}

    units = sorted({it["unit"] for it in items})
    total = len(items)

    return {
        "schema": 1,
        "exam_id": exam_id,
        "created_at": args.created_at or date.today().isoformat(),
        "child": child,
        "subject": args.subject,
        "kind": "daily_practice",
        "title": title,
        "scope": {
            "grade": args.grade,
            "term": args.term,
            "units": units,
            "textbook_edition": textbook,
        },
        "difficulty_level": "basic",
        "total_points": total,
        "suggested_minutes": max(5, round(total / 10) * 5),
        "sections": [{
            "id": section_id,
            "name": section_name,
            "points": total,
            "columns": columns,
            "instructions": instructions,
            "items": items,
        }],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--subject", required=True, choices=["math", "chinese", "english"])
    ap.add_argument("--grade", type=int, required=True, choices=[2, 3])
    ap.add_argument("--term", required=True, choices=["up", "down"])
    ap.add_argument("--current-unit", type=int, required=True, help="孩子当前学习到的单元号")
    ap.add_argument("--count", type=int, default=10, help="题目数量（默认 10）")
    ap.add_argument("--columns", type=int, default=3, choices=[2, 3], help="数学分栏数（默认 3）")
    ap.add_argument("--mode", choices=["words", "writing", "literacy", "mixed"], default="words", help="语文选词范围（默认词语表）")
    ap.add_argument("--seed", type=int, help="随机种子；相同种子生成相同题目")
    ap.add_argument("--title")
    ap.add_argument("--exam-id")
    ap.add_argument("--child-id")
    ap.add_argument("--child-nickname")
    ap.add_argument("--created-at", help="指定 created_at 日期（默认今天）")
    ap.add_argument("-o", "--out", type=Path, required=True, help="输出 JSON 路径")
    args = ap.parse_args()

    if args.count <= 0:
        ap.error("--count 必须为正整数")

    try:
        data = build_exam(args)
    except ValueError as e:
        ap.error(str(e))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    n = len(data["sections"][0]["items"])
    units = data["scope"]["units"]
    print(f"OK: {args.out}  {n} 题  单元：{','.join(str(u) for u in units)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
