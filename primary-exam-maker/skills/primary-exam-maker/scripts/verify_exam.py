#!/usr/bin/env python3
"""试卷内容的学科核验（在 validate_exam.py 之后运行）：

- 数学：复算口算/脱式/分数等纯算式题的答案；无法解析的题跳过并计数。
- 英语：检查选择题答案在选项中；答案/选项中的单词是否在本册词表范围内（warning）。
- 语文：检查“看拼音写词语”答案是否在词语表、答案用字是否在识字/写字表（warning）。

用法:
  python3 -I verify_exam.py exam.json [--strict]
退出码：有 FAIL（确定的错误）返回 1；--strict 时 warning 也返回 1。
"""
from __future__ import annotations

import argparse
import ast
import json
import operator
import re
import sys
from fractions import Fraction
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SUBJECT_NAMES = {"math": "数学", "chinese": "语文", "english": "英语"}

# 常见虚词/课堂用语：低年级教材允许出现但未必收进 Word list
COMMON_EN = {
    "a", "an", "the", "i", "you", "he", "she", "it", "we", "they", "my", "your", "his", "her",
    "our", "their", "this", "that", "these", "those", "is", "am", "are", "be", "yes", "no", "not",
    "and", "or", "but", "in", "on", "at", "to", "of", "for", "with", "can", "do", "does", "what",
    "how", "who", "where", "name", "class", "good", "morning", "afternoon", "hello", "hi",
}


def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        sys.exit(f"JSON 解析失败：{path}：{e}")
    except FileNotFoundError:
        sys.exit(f"文件不存在：{path}")


def flat_items(data: dict):
    for sec in data.get("sections", []):
        for it in sec.get("items", []):
            yield it


# ---------- 数学 ----------

_BIN_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
            ast.Div: operator.truediv, ast.Pow: operator.pow}


def _eval_node(node):
    if isinstance(node, ast.Expression):
        return _eval_node(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
        return _BIN_OPS[type(node.op)](_eval_node(node.left), _eval_node(node.right))
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -_eval_node(node.operand)
    raise ValueError("不支持的表达式")


def safe_eval(expr: str):
    return _eval_node(ast.parse(expr, mode="eval"))


def _norm_expr(s: str) -> str:
    s = (s.replace("×", "*").replace("÷", "/").replace("−", "-").replace("—", "-")
         .replace("＋", "+").replace("（", "(").replace("）", ")"))
    return re.sub(r"\s+", "", s)


def check_math_expr(stem: str, answer: str):
    """返回 (status, detail)。status: ok / mismatch / skip。"""
    ans = str(answer).strip()
    if "○" in stem or "〇" in stem:
        pairs = re.findall(r"([0-9+\-×÷*/().\s]+?)\s*[○〇]\s*([0-9+\-×÷*/().\s]+?)(?=[，。；,\s（(]|$)", stem)
        ans_syms = re.findall(r"[<>=]", ans)
        if pairs and len(pairs) == len(ans_syms):
            try:
                for (l_raw, r_raw), sym in zip(pairs, ans_syms):
                    lv = safe_eval(_norm_expr(l_raw))
                    rv = safe_eval(_norm_expr(r_raw))
                    expect_sym = "<" if lv < rv - 1e-9 else (">" if lv > rv + 1e-9 else "=")
                    if sym != expect_sym:
                        return "mismatch", f"{l_raw.strip()} ○ {r_raw.strip()} 应填 {expect_sym}，实际 {sym}"
                return "ok", ""
            except (ValueError, SyntaxError, ZeroDivisionError):
                return "skip", ""
    left = stem.split("=")[0].strip()
    expr = _norm_expr(left)
    # 分数：a/b + c/d
    m = re.fullmatch(r"(\d+)/(\d+)([+\-])(\d+)/(\d+)", expr)
    if m:
        try:
            v = Fraction(int(m[1]), int(m[2]))
            w = Fraction(int(m[4]), int(m[5]))
            expect = v + w if m[3] == "+" else v - w
            got = Fraction(ans)
        except (ValueError, ZeroDivisionError):
            return "mismatch", f"分数答案无法解析：{ans!r}"
        if expect != got:
            return "mismatch", f"应得 {expect.numerator}/{expect.denominator}，实际 {ans}"
        return "ok", ""
    # 除法与有余数除法：a ÷ b（归一化后为 a/b）
    m = re.fullmatch(r"(\d+)/(\d+)", expr)
    if m:
        a, b = int(m[1]), int(m[2])
        if b == 0:
            return "mismatch", "除数为 0"
        mm = re.match(r"^(\d+)\s*(?:……|\.\.\.|…)\s*(\d+)$", ans)
        if mm:
            q, r = int(mm[1]), int(mm[2])
            if (q, r) != divmod(a, b):
                return "mismatch", f"{a}÷{b} 应为 {divmod(a, b)[0]}……{divmod(a, b)[1]}，实际 {ans}"
            return "ok", ""
        if a % b != 0:
            return "mismatch", f"{a}÷{b} 不是整除，答案应带余数，实际 {ans}"
        if str(a // b) != ans:
            return "mismatch", f"{a}÷{b} 应得 {a // b}，实际 {ans}"
        return "ok", ""
    if not re.fullmatch(r"[0-9+\-*/().]+", expr):
        return "skip", ""
    try:
        got = safe_eval(expr)
        expect = float(ans)
    except (ValueError, SyntaxError, ZeroDivisionError):
        return "skip", ""
    if abs(got - expect) > 1e-9:
        return "mismatch", f"{left} 应得 {got:g}，实际 {ans}"
    return "ok", ""


# ---------- 英语 ----------

def load_english_words(grade: int, term: str) -> set[str]:
    path = DATA_DIR / "curriculum" / "english" / f"english_g{grade}_{term}_wordlist.json"
    if not path.exists():
        return set()
    data = load_json(path)
    words = set()
    for unit in data.get("units", []):
        for w in unit.get("words", []):
            # 词表条目可能是 "Mr (AmE Mr.)" 这类带括号变体的形式，也可能是一条短语。
            # 按单词拆开逐个入集合，否则整串会被当成一个"词"，永远匹配不上。
            for form in (w.get("en_primary"), w.get("en")):
                if not form:
                    continue
                for token in english_words(form):
                    words.add(token)
    return words


def english_words(text: str) -> set[str]:
    return {w.lower() for w in re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?", str(text))}


# ---------- 语文 ----------

def load_chinese_tables(grade: int, term: str) -> tuple[set[str], set[str], set[str]]:
    path = DATA_DIR / "curriculum" / "chinese" / f"chinese_g{grade}_{term}_tables.json"
    if not path.exists():
        return set(), set(), set()
    tables = load_json(path)["tables"]

    def chars(key):
        out = set()
        for sec in tables.get(key, []):
            out.update(sec.get("items", []))
        return out

    words = {w for w in chars("words")}
    return chars("literacy"), chars("writing"), words


def chinese_allowed_chars(literacy: set[str], writing: set[str], words: set[str]) -> set[str]:
    """本册可写的字集合。

    词语表里的词都是本册要求会写的，但组成它们的字可能是**低年级已学**的
    （例如二上词语表有“雪白”，而“雪”“白”是一年级学的，不在本册识字/写字表里）。
    因此合法字集 = 识字表 ∪ 写字表 ∪ 词语表里出现过的所有字。
    """
    allowed = set(literacy) | set(writing)
    for w in words:
        allowed.update(ch for ch in w if "一" <= ch <= "鿿")
    return allowed


def verify_exam_data(data: dict) -> tuple[list[str], list[str], str]:
    """对试卷 JSON 数据做学科核验，返回 (errors, warnings, summary)。"""
    subject = data.get("subject")
    scope = data.get("scope") or {}
    grade, term = scope.get("grade"), scope.get("term")
    errs: list[str] = []
    warns: list[str] = []
    checked = skipped = 0
    summary = ""

    if subject == "math":
        for it in flat_items(data):
            status, detail = check_math_expr(str(it.get("stem", "")), it.get("answer", ""))
            if status == "ok":
                checked += 1
            elif status == "mismatch":
                errs.append(f"{it.get('id')}: {detail}")
            else:
                skipped += 1
        summary = f"数学：复算通过 {checked} 题，跳过 {skipped} 题（应用题/竖式/图形题需人工或出题时保证）"

    elif subject == "english":
        words = load_english_words(grade, term) if isinstance(grade, int) and term else set()
        for it in flat_items(data):
            ans = str(it.get("answer", "")).strip()
            opts = it.get("options")
            if isinstance(opts, list) and opts:
                if ans not in [str(o).strip() for o in opts]:
                    errs.append(f"{it.get('id')}: 选择题答案 {ans!r} 不在选项中")
            if words:
                for w in english_words(" ".join([ans] + ([str(o) for o in opts] if isinstance(opts, list) else []))):
                    if w not in words and w not in COMMON_EN:
                        warns.append(f"{it.get('id')}: 单词 {w!r} 不在本册 Word list（可能是专有名词或超纲）")

    elif subject == "chinese":
        literacy, writing, words = load_chinese_tables(grade, term) if isinstance(grade, int) and term else (set(), set(), set())
        allowed = chinese_allowed_chars(literacy, writing, words) if (literacy or writing) else set()
        for it in flat_items(data):
            ans = str(it.get("answer", "")).strip()
            if not ans:
                continue
            if it.get("type") in ("看拼音写词语", "听写") and words:
                for w in re.findall(r"[一-鿿]{2,}", ans):
                    if w not in words:
                        warns.append(f"{it.get('id')}: 词语 {w!r} 不在本册词语表")
            if allowed:
                unknown = [c for c in ans if "一" <= c <= "鿿" and c not in allowed]
                if unknown and it.get("type") in ("看拼音写词语", "字词辨析", "书写", "填空", "听写"):
                    warns.append(f"{it.get('id')}: 答案含识字/写字/词语表外的字 {''.join(unknown)}")
    else:
        warns.append(f"未知学科 subject={subject!r}，跳过学科核验")

    return errs, warns, summary


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("exam_json", type=Path)
    ap.add_argument("--strict", action="store_true", help="warning 也视为失败")
    args = ap.parse_args()

    data = load_json(args.exam_json)
    errs, warns, summary = verify_exam_data(data)
    if summary:
        print(summary)
    for w in warns:
        print("WARN", w)
    for e in errs:
        print("FAIL", e)
    ok = not errs and not (args.strict and warns)
    print(f"{'PASS' if ok else 'FAIL'}: {len(errs)} errors, {len(warns)} warnings")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
