#!/usr/bin/env python3
"""生成语文/英语听写单中间格式 JSON（词语取自本册字表/词表，可选生成音频）。

用法:
  python3 generate_dictation.py --subject chinese --grade 2 --term up --units 1,2 --count 20 -o dict.json
  python3 generate_dictation.py --subject chinese --grade 2 --term up --mode writing --count 15 -o dict.json
  python3 generate_dictation.py --subject english --grade 3 --term up --units 1-2 --count 10 -o dict.json
  python3 generate_dictation.py --subject english --grade 3 --term up --count 10 --audio /tmp/dict.aiff -o dict.json

生成结果通过 validate_exam.py 校验后，用 render_exam.py 渲染为分离的孩子卷/答案卷。
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
SUBJECT_CN = {"chinese": "语文", "english": "英语"}
GRADE_CN = {2: "二", 3: "三"}
MODE_CN = {"words": "词语", "writing": "生字（写字表）", "literacy": "生字（识字表）"}


def parse_units(spec: str | None) -> list[int] | None:
    if not spec:
        return None
    units: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            units.extend(range(int(a), int(b) + 1))
        else:
            units.append(int(part))
    return sorted(set(units))


def load_chinese(grade: int, term: str) -> tuple[dict, dict]:
    base = CURRICULUM / "chinese" / f"chinese_g{grade}_{term}"
    tables = json.loads(Path(f"{base}_tables.json").read_text(encoding="utf-8"))
    curriculum = json.loads(Path(f"{base}.json").read_text(encoding="utf-8"))
    return tables, curriculum


def chinese_lesson_to_unit(curriculum: dict) -> dict:
    """(section, 课次) -> 单元号；语文园地按 after 课次归入同一单元。"""
    mapping: dict[tuple[str, int], int] = {}
    for unit in curriculum["units"]:
        kind = unit.get("kind", "阅读")
        for item in unit.get("items", []):
            if item.get("type") == "lesson" and item.get("no") is not None:
                mapping[(kind, item["no"])] = unit["no"]
    return mapping


def collect_chinese(args: argparse.Namespace) -> list[dict]:
    tables, curriculum = load_chinese(args.grade, args.term)
    lesson_unit = chinese_lesson_to_unit(curriculum)
    modes = ["words", "writing", "literacy"] if args.mode == "mixed" else [args.mode]
    out: list[dict] = []
    for mode in modes:
        for section in tables["tables"].get(mode, []):
            if section.get("garden"):
                continue  # 语文园地词语暂不入选，避免与课文词重复
            unit = lesson_unit.get((section.get("section"), section.get("no")))
            if unit is None:
                continue
            for word in section.get("items", []):
                out.append({"text": word, "unit": unit, "mode": mode})
    return out


def collect_english(args: argparse.Namespace) -> list[dict]:
    path = CURRICULUM / "english" / f"english_g{args.grade}_{args.term}_wordlist.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    out = []
    for unit in data["units"]:
        for w in unit.get("words", []):
            if not args.include_noncore and not w.get("core"):
                continue
            # en_primary 是去掉括号变体后的主词形（如 "Mr (AmE Mr.)" -> "Mr"），
            # 直接作为听写答案；缺失时退回教材原样 en。
            out.append({
                "text": w.get("en_primary") or w["en"],
                "unit": unit["unit"],
                "mode": "words",
            })
    return out


def build_exam(args: argparse.Namespace) -> dict:
    units = parse_units(args.units)
    candidates = collect_chinese(args) if args.subject == "chinese" else collect_english(args)
    if units:
        candidates = [c for c in candidates if c["unit"] in units]
    if not candidates:
        raise ValueError(f"没有找到符合条件的{'单元范围' if units else ''}听写词，请检查 --units/--mode")

    # 同一词语可能出现在多个课次，按词语去重并保留首次出现的单元
    uniq: dict[str, dict] = {}
    for c in candidates:
        uniq.setdefault(c["text"], c)
    pool = list(uniq.values())
    if args.count > len(pool):
        raise ValueError(f"可用词语只有 {len(pool)} 个，少于要求的 {args.count} 个")
    r = random.Random(args.seed)
    chosen = r.sample(pool, args.count)
    r.shuffle(chosen)

    items = []
    for qno, entry in enumerate(chosen, 1):
        text = entry["text"]
        if args.subject == "chinese":
            stem = "{{tianzige n=%d}}" % max(2, len(text))
            hint = "家长读两遍：先读整个词语，再逐字读，最后连起来读一遍。"
            rules = "写对得 1 分；错字、漏字、多字均不得分。"
        else:
            stem = "{{fourline rows=1}}"
            hint = "家长读两遍单词，孩子先听再写；注意字母占格与大小写。"
            rules = "拼写完全正确得 1 分；拼错、大小写错误不得分。"
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
            "scoring_rules": rules,
            "hint": hint,
            "knowledge_points": ["待归类"],
        })

    grade_cn = GRADE_CN.get(args.grade, str(args.grade))
    term_cn = "上" if args.term == "up" else "下"
    subj_cn = SUBJECT_CN[args.subject]
    mode_cn = MODE_CN.get(args.mode if args.subject == "chinese" else "words", "")
    title = args.title or f"{grade_cn}年级{subj_cn}{term_cn}册 · {mode_cn}听写单（{args.count} 个）"
    exam_id = args.exam_id or f"dictation-{args.subject}-g{args.grade}-{args.term}-{date.today():%Y%m%d}"
    child = {}
    if args.child_id or args.child_nickname:
        child = {"id": args.child_id or "", "nickname": args.child_nickname or "", "grade": args.grade, "term": args.term}

    audio = None
    if args.audio:
        audio = {"mp3_name": Path(args.audio).name, "script": "；".join(f"{i}. {e['text']}" for i, e in enumerate(chosen, 1))}

    return {
        "schema": 1,
        "exam_id": exam_id,
        "created_at": args.created_at or date.today().isoformat(),
        "child": child,
        "subject": args.subject,
        "kind": "dictation",
        "title": title,
        "scope": {
            "grade": args.grade,
            "term": args.term,
            "units": units or sorted({c["unit"] for c in chosen}),
            "textbook_edition": "统编版" if args.subject == "chinese" else "译林版",
        },
        "difficulty_level": "basic",
        "total_points": args.count,
        "suggested_minutes": max(5, args.count),
        "audio": audio,
        "sections": [{
            "id": "dictation",
            "name": "听写",
            "points": args.count,
            "columns": 2,
            "instructions": f"共 {args.count} 个，家长按题号读，孩子写。",
            "items": items,
        }],
    }


def write_audio(entries: list[dict], out: Path, subject: str = "chinese",
                score: int | None = None, total: int | None = None) -> None:
    """macOS say 生成音频：每词读两遍，词间停顿；结尾附语音鼓励；.m4a 用 afconvert 转码。

    语文用 Ting-Ting（中文语音），英语用 Samantha（英语语音）。
    score/total 非空时在词语读完后朗读对应的鼓励语。
    """
    import subprocess

    if subject == "english":
        voice, rate = "Samantha", 120
    else:
        voice, rate = "Ting-Ting", 135

    parts = []
    for entry in entries:
        text = entry["text"]
        parts.append(f"[[slnc 800]]{text}[[slnc 1200]]{text}[[slnc 2000]]")

    # 语音鼓励（结尾）
    if score is not None and total is not None and total > 0:
        rate_pct = round(score / total * 100)
        if rate_pct >= 90:
            encouragement = "太棒了！你全都写对了，继续保持！"
        elif rate_pct >= 70:
            encouragement = f"不错！这次对了{score}个，再加把劲，你一定能全对！"
        else:
            encouragement = f"这次对了{score}个，不要灰心，多练几遍就会越来越好！"
        parts.append(f"[[slnc 1500]]{encouragement}[[slnc 500]]")
    elif subject == "chinese":
        parts.append("[[slnc 1500]]听写完成，请对照答案自己检查一下！[[slnc 500]]")

    script = "".join(parts)
    aiff = out.with_suffix(".aiff") if out.suffix.lower() == ".m4a" else out
    subprocess.run(["say", "-v", voice, "-r", str(rate), "-o", str(aiff), script], check=True)
    if out.suffix.lower() == ".m4a":
        subprocess.run(["afconvert", "-f", "m4af", "-d", "aac", str(aiff), str(out)], check=True)
        aiff.unlink(missing_ok=True)
    print(f"AUDIO: {out}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--subject", required=True, choices=["chinese", "english"])
    ap.add_argument("--grade", type=int, required=True, choices=[2, 3])
    ap.add_argument("--term", required=True, choices=["up", "down"])
    ap.add_argument("--units", help="单元范围，如 1,2 或 1-3")
    ap.add_argument("--count", type=int, default=20, help="词语数量（默认 20）")
    ap.add_argument("--mode", choices=["words", "writing", "literacy", "mixed"], default="words", help="语文选词范围（默认词语表）")
    ap.add_argument("--include-noncore", action="store_true", help="英语是否包含非核心词")
    ap.add_argument("--seed", type=int)
    ap.add_argument("--title")
    ap.add_argument("--exam-id")
    ap.add_argument("--child-id")
    ap.add_argument("--child-nickname")
    ap.add_argument("--audio", type=Path, help="同时生成 aiff 音频（macOS say）")
    ap.add_argument("--audio-score", type=int, help="听写得分，用于在音频结尾生成鼓励语（需配合 --audio-total）")
    ap.add_argument("--audio-total", type=int, help="听写满分，用于在音频结尾生成鼓励语（需配合 --audio-score）")
    ap.add_argument("--created-at", help="指定 created_at 日期（默认今天）")
    ap.add_argument("-o", "--out", type=Path, required=True)
    args = ap.parse_args()

    if args.count <= 0:
        ap.error("--count 必须为正整数")
    try:
        data = build_exam(args)
    except ValueError as e:
        ap.error(str(e))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"OK: {args.out}  {args.count} 个")
    if args.audio:
        write_audio([{"text": it["answer"]} for it in data["sections"][0]["items"]], args.audio, args.subject,
                    score=args.audio_score, total=args.audio_total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
