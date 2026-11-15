#!/usr/bin/env python3
"""给英语 Word list 补 `en_primary`（去掉括号变体后的主词形），供听写出题与核验使用。

教材 Word lists 里部分条目带括号变体或复数说明，例如：
    Mr (AmE Mr.)      -> en_primary: Mr
    mum (AmE mom)     -> en_primary: mum
    child (pl. children) -> en_primary: child
    Yes, please.      -> en_primary: Yes, please.   （短语，原样保留）

`en` 保留教材印刷原样（可追溯），`en_primary` 是可直接作为听写答案的形式。
本脚本幂等：重复运行结果一致。

用法:
    python3 -I normalize_english_wordlist.py [--check] [wordlist.json ...]

    --check  只报告问题，不写文件；有需要修正的条目时退出码 1。
    不带参数时处理 data/curriculum/english/ 下全部 *_wordlist.json。
"""
import glob
import json
import re
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
WORDLIST_DIR = SKILL_DIR / "data" / "curriculum" / "english"

# 括号及其内容：半角/全角都处理
PAREN = re.compile(r"[（(][^）)]*[）)]")


def primary_form(en: str) -> str:
    """取括号前的主词形；括号前为空时退回原文。"""
    text = PAREN.sub("", str(en)).strip()
    text = re.sub(r"\s+", " ", text)
    return text or str(en).strip()


def normalize_file(path: Path, check_only: bool) -> list[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    problems: list[str] = []
    changed = 0
    for unit in data.get("units", []):
        for w in unit.get("words", []):
            en = str(w.get("en", ""))
            want = primary_form(en)
            if not want:
                problems.append(f"{path.name} U{unit.get('unit')}: 主词形为空 {en!r}")
                continue
            if w.get("en_primary") != want:
                changed += 1
                if not check_only:
                    w["en_primary"] = want
    if changed and not check_only:
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
        )
    if changed:
        problems.append(
            f"{path.name}: {changed} 条 en_primary {'待补' if check_only else '已补'}"
        )
    return problems


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    check_only = "--check" in sys.argv[1:]
    files = [Path(a) for a in args] or sorted(
        Path(p) for p in glob.glob(str(WORDLIST_DIR / "*_wordlist.json"))
    )
    if not files:
        print("没有找到 wordlist 文件")
        return 1
    all_problems: list[str] = []
    for f in files:
        all_problems.extend(normalize_file(f, check_only))
    for p in all_problems:
        print(("FAIL " if "为空" in p else "") + p)
    hard = [p for p in all_problems if "为空" in p]
    if check_only:
        pending = [p for p in all_problems if "待补" in p]
        print(f"{len(files)} files, {len(pending)} 待修正, {len(hard)} 错误")
        return 1 if (pending or hard) else 0
    print(f"{len(files)} files, {len(hard)} 错误")
    return 1 if hard else 0


if __name__ == "__main__":
    sys.exit(main())
