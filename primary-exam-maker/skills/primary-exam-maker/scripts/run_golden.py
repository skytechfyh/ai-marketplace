#!/usr/bin/env python3
"""黄金样例回归测试：对 tests/golden/ 下每份样例跑完整链路并核对产物。

链路：validate_exam.py → verify_exam.py → render_exam.py（含 --pdf）→ 产物断言。
另外跑数据层校验（知识点目录、试卷模板、英语词表主词形）与生成器冒烟测试。

用法:
    python3 "$SKILL_DIR/scripts/run_golden.py" [--no-pdf] [-k 关键字] [-v]

    --no-pdf   跳过 PDF 渲染（无 Chrome 的机器用；只验 MD 与 JSON 链路）
    -k         只跑文件名含该关键字的样例
    -v         打印每条断言的细节

退出码：全部通过 0，否则 1。
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
SCRIPTS = SKILL_DIR / "scripts"


def find_golden_dir() -> Path:
    """定位黄金样例目录。

    样例默认放在插件根目录的 tests/golden/（不占 skill 的资源配额——
    Perch 对 skill 目录只登记 50 个资源文件，样例放里面会挤掉脚本）。
    也兼容放在 skill 内的 tests/golden/。
    """
    candidates = [
        SKILL_DIR.parent.parent / "tests" / "golden",  # 插件根：<plugin>/tests/golden
        SKILL_DIR / "tests" / "golden",                # skill 内
    ]
    for c in candidates:
        if c.is_dir():
            return c
    return candidates[0]


GOLDEN = find_golden_dir()

PASS, FAIL = "PASS", "FAIL"


def clean_pycache() -> None:
    """清理 skill 目录下的 __pycache__，避免 .pyc 占用 Perch 资源配额。"""
    import shutil
    for d in SKILL_DIR.rglob("__pycache__"):
        shutil.rmtree(d, ignore_errors=True)


class Report:
    def __init__(self, verbose: bool = False):
        self.rows: list[tuple[str, str, str]] = []
        self.verbose = verbose

    def add(self, name: str, status: str, detail: str = "") -> None:
        self.rows.append((name, status, detail))
        if status == FAIL or self.verbose:
            print(f"  {status} {name}" + (f" — {detail}" if detail else ""))

    @property
    def failed(self) -> list[tuple[str, str, str]]:
        return [r for r in self.rows if r[1] == FAIL]


def run(cmd: list[str], cwd: Path | None = None) -> tuple[int, str]:
    proc = subprocess.run(
        cmd, cwd=str(cwd) if cwd else None,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def check_data_layer(rep: Report) -> None:
    """数据层校验：知识点目录、模板、英语词表。"""
    print("\n[数据层]")
    for label, cmd in [
        ("知识点目录", [sys.executable, "-I", str(SCRIPTS / "validate_knowledge.py")]),
        ("试卷模板", [sys.executable, "-I", str(SCRIPTS / "validate_templates.py")]),
        ("英语词表主词形", [sys.executable, "-I", str(SCRIPTS / "normalize_english_wordlist.py"), "--check"]),
    ]:
        code, out = run(cmd)
        tail = out.strip().splitlines()[-1] if out.strip() else ""
        rep.add(label, PASS if code == 0 else FAIL, tail)


def check_generators(rep: Report, tmp: Path, with_pdf: bool) -> None:
    """生成器冒烟：口算卡、语文听写、英语听写各出一份并走完整链路。"""
    print("\n[生成器冒烟]")
    cases = [
        ("口算卡 g2up", [
            sys.executable, str(SCRIPTS / "generate_oral_math.py"),
            "--grade", "2", "--term", "up", "--count", "20", "--seed", "42",
            "-o", str(tmp / "oral.json"),
        ], "oral.json"),
        ("口算卡·有余数", [
            sys.executable, str(SCRIPTS / "generate_oral_math.py"),
            "--grade", "2", "--term", "up", "--topics", "rem", "--count", "10", "--seed", "3",
            "-o", str(tmp / "rem.json"),
        ], "rem.json"),
        ("语文听写 g2up", [
            sys.executable, str(SCRIPTS / "generate_dictation.py"),
            "--subject", "chinese", "--grade", "2", "--term", "up",
            "--units", "1-2", "--count", "15", "--seed", "5",
            "-o", str(tmp / "dict_cn.json"),
        ], "dict_cn.json"),
        ("英语听写 g3up", [
            sys.executable, str(SCRIPTS / "generate_dictation.py"),
            "--subject", "english", "--grade", "3", "--term", "up",
            "--units", "1-2", "--count", "12", "--seed", "7",
            "-o", str(tmp / "dict_en.json"),
        ], "dict_en.json"),
    ]
    for label, cmd, out_name in cases:
        code, out = run(cmd)
        if code != 0:
            rep.add(label, FAIL, out.strip().splitlines()[-1] if out.strip() else "生成失败")
            continue
        rep.add(label, PASS, "已生成")
        exam = tmp / out_name
        run_chain(rep, exam, tmp / (out_name + ".out"), with_pdf, prefix=label + " · ")


def run_chain(rep: Report, exam: Path, outdir: Path, with_pdf: bool, prefix: str = "") -> None:
    """对一份 exam.json 跑 validate → verify → render，并断言产物。"""
    code, out = run([sys.executable, "-I", str(SCRIPTS / "validate_exam.py"), str(exam)])
    tail = out.strip().splitlines()[-1] if out.strip() else ""
    rep.add(prefix + "validate", PASS if code == 0 else FAIL, tail)
    if code != 0:
        return

    code, out = run([sys.executable, "-I", str(SCRIPTS / "verify_exam.py"), str(exam)])
    tail = out.strip().splitlines()[-1] if out.strip() else ""
    rep.add(prefix + "verify", PASS if code == 0 else FAIL, tail)
    if code != 0:
        return

    cmd = [sys.executable, str(SCRIPTS / "render_exam.py"), str(exam), "-o", str(outdir)]
    if with_pdf:
        cmd.append("--pdf")
    code, out = run(cmd)
    if code != 0:
        rep.add(prefix + "render", FAIL, out.strip().splitlines()[-1] if out.strip() else "渲染失败")
        return
    rep.add(prefix + "render", PASS, "已渲染")

    # 产物断言：孩子卷与答案卷必须分离，且孩子卷不含答案
    data = json.loads(exam.read_text(encoding="utf-8"))
    stem = data["exam_id"]
    student = outdir / f"{stem}_试卷.md"
    answer = outdir / f"{stem}_答案与评分.md"

    if not student.exists():
        rep.add(prefix + "孩子卷存在", FAIL, str(student))
        return
    if not answer.exists():
        rep.add(prefix + "答案卷存在", FAIL, str(answer))
        return
    rep.add(prefix + "两卷分离", PASS)

    s_text = student.read_text(encoding="utf-8")
    a_text = answer.read_text(encoding="utf-8")

    # 孩子卷绝不能出现评分细则、提示、知识点编号
    leaks = []
    for marker in ("得分要点", "评分细则", "讲评", "知识卡", "错因"):
        if marker in s_text:
            leaks.append(marker)
    for kp in re.findall(r"\b[A-Z]\d[UD]-\d+-\d+\b", s_text):
        leaks.append(f"知识点编号 {kp}")
    rep.add(prefix + "孩子卷无泄漏", PASS if not leaks else FAIL, "、".join(leaks))

    # 答案卷必须含答案与阅卷表
    must = ["答案", "阅卷"]
    missing = [m for m in must if m not in a_text]
    rep.add(prefix + "答案卷完整", PASS if not missing else FAIL, "缺 " + "、".join(missing) if missing else "")

    if with_pdf:
        pdfs = sorted(outdir.glob("*.pdf"))
        rep.add(prefix + "PDF 产出", PASS if len(pdfs) >= 2 else FAIL, f"{len(pdfs)} 个 PDF")


def check_golden(rep: Report, tmp: Path, with_pdf: bool, keyword: str | None) -> None:
    print("\n[黄金样例]")
    files = sorted(GOLDEN.glob("*.json"))
    if keyword:
        files = [f for f in files if keyword in f.name]
    if not files:
        rep.add("黄金样例存在", FAIL, f"{GOLDEN} 下没有匹配的样例")
        return
    for f in files:
        run_chain(rep, f, tmp / f.stem, with_pdf, prefix=f.stem + " · ")


def check_planners(rep: Report) -> None:
    """规划脚本冒烟：确认能跑通且输出非空。"""
    print("\n[规划脚本]")
    cases = [
        ("plan_exam 数学单元", [
            sys.executable, "-I", str(SCRIPTS / "plan_exam.py"),
            "--subject", "math", "--grade", "3", "--term", "up",
            "--kind", "unit", "--units", "1,2",
        ]),
        ("plan_exam 语文期末", [
            sys.executable, "-I", str(SCRIPTS / "plan_exam.py"),
            "--subject", "chinese", "--grade", "3", "--term", "down", "--kind", "final",
        ]),
        ("plan_kp_drill 知识点", [
            sys.executable, "-I", str(SCRIPTS / "plan_kp_drill.py"),
            "--subject", "math", "--grade", "2", "--term", "up",
            "--kp", "M2U-1-05", "--count", "20",
        ]),
    ]
    for label, cmd in cases:
        code, out = run(cmd)
        ok = code == 0 and len(out.strip()) > 100
        rep.add(label, PASS if ok else FAIL, f"{len(out)} 字符")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-pdf", action="store_true", help="跳过 PDF 渲染")
    ap.add_argument("-k", dest="keyword", help="只跑文件名含该关键字的样例")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    with_pdf = not args.no_pdf
    rep = Report(args.verbose)
    print(f"skill 目录：{SKILL_DIR}")
    print(f"PDF 渲染：{'开启' if with_pdf else '跳过'}")

    with tempfile.TemporaryDirectory(prefix="pem-golden-") as td:
        tmp = Path(td)
        clean_pycache()  # 清理上次运行残留
        check_data_layer(rep)
        check_planners(rep)
        check_golden(rep, tmp, with_pdf, args.keyword)
        if not args.keyword:
            check_generators(rep, tmp, with_pdf)
    clean_pycache()  # 运行后清理，避免 .pyc 占用资源配额

    total = len(rep.rows)
    failed = rep.failed
    print(f"\n{'='*60}")
    if failed:
        print(f"FAILED: {len(failed)}/{total} 项未通过")
        for name, _, detail in failed:
            print(f"  ✗ {name}" + (f" — {detail}" if detail else ""))
        return 1
    print(f"ALL PASS: {total} 项全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
