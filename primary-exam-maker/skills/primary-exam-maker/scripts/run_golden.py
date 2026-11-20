#!/usr/bin/env python3
"""黄金样例与功能回归测试：对 tests/golden/ 下每份样例跑完整链路并核对产物。

链路：validate_exam.py → verify_exam.py → render_exam.py（默认子目录 + 仅 PDF）→ 产物断言。
另外跑数据层校验（知识点目录、试卷模板、英语词表主词形）、生成器冒烟与核心功能回归测试。

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
import os
import re
import subprocess
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
SCRIPTS = SKILL_DIR / "scripts"
sys.path.insert(0, str(SCRIPTS))
import render_exam as render_exam_mod  # noqa: E402


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


def run(cmd: list[str], cwd: Path | None = None, env: dict[str, str] | None = None) -> tuple[int, str]:
    full_env = None
    if env is not None:
        full_env = os.environ.copy()
        full_env.update(env)
    proc = subprocess.run(
        cmd, cwd=str(cwd) if cwd else None, env=full_env,
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
        ("找朋友 g2up", [
            sys.executable, str(SCRIPTS / "generate_gamified_chinese.py"),
            "--grade", "2", "--term", "up", "--units", "1,2",
            "--type", "zhaopengyou", "--count", "4", "--seed", "42",
            "-o", str(tmp / "zhaopengyou.json"),
        ], "zhaopengyou.json"),
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
    if not with_pdf:
        cmd.append("--md-only")
    code, out = run(cmd)
    if code != 0:
        rep.add(prefix + "render", FAIL, out.strip().splitlines()[-1] if out.strip() else "渲染失败")
        return
    rep.add(prefix + "render", PASS, "已渲染")

    # 产物断言：默认落盘到独立子目录 <outdir>/<stem>/，归档 exam.json；PDF 模式下不残留 .md
    data = json.loads(exam.read_text(encoding="utf-8"))
    stem = data["exam_id"]
    exam_dir = outdir / stem
    if not exam_dir.is_dir():
        rep.add(prefix + "独立子目录", FAIL, str(exam_dir))
        return
    archived = exam_dir / "exam.json"
    rep.add(prefix + "exam.json 归档", PASS if archived.exists() else FAIL, str(archived))

    if with_pdf:
        student_pdf = exam_dir / f"{stem}_试卷.pdf"
        answer_pdf = exam_dir / f"{stem}_答案与评分.pdf"
        mds = list(exam_dir.glob("*.md"))
        ok_pdfs = student_pdf.exists() and answer_pdf.exists()
        rep.add(prefix + "PDF 产出", PASS if ok_pdfs else FAIL, f"{len(list(exam_dir.glob('*.pdf')))} 个 PDF")
        rep.add(prefix + "默认无残留 MD", PASS if not mds else FAIL, ", ".join(p.name for p in mds))
        s_text = render_exam_mod.build_student_md(data)
        a_text = render_exam_mod.build_answer_md(data)
    else:
        student = exam_dir / f"{stem}_试卷.md"
        answer = exam_dir / f"{stem}_答案与评分.md"
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


def check_regressions(rep: Report, tmp: Path, with_pdf: bool) -> None:
    """核心功能回归：子目录防重名、三种判分+错题同步、连续打卡、跨科单元隔离、报告 PDF。"""
    print("\n[功能回归]")
    reg_home = tmp / "pem-home"
    env = {"PRIMARY_EXAM_HOME": str(reg_home)}

    # 1) 建档
    code, out = run([
        sys.executable, str(SCRIPTS / "profile.py"), "add",
        "--id", "testbao", "--nickname", "测试宝", "--enrollment-year", "2024",
    ], env=env)
    rep.add("profile 建档", PASS if code == 0 else FAIL, out.strip().splitlines()[-1] if out.strip() else "")
    if code != 0:
        return
    child_id = "testbao"

    # 2) 构造一份含不同分值(4/5/6分)的数学试卷 JSON，测试 render_exam 子目录与防重名 + 判分
    sample_exam = {
        "schema": 1,
        "exam_id": "reg-math-01",
        "created_at": date.today().isoformat(),
        "child": {"id": child_id, "nickname": "测试宝", "grade": 2, "term": "up"},
        "subject": "math",
        "kind": "topic",
        "title": "二年级数学上册 · 回归测试卷",
        "scope": {"grade": 2, "term": "up", "units": [1, 2], "textbook_edition": "苏教版"},
        "difficulty_level": "standard",
        "total_points": 15,
        "suggested_minutes": 10,
        "sections": [{
            "id": "s1",
            "name": "计算与应用",
            "points": 15,
            "items": [
                {
                    "id": "q1", "no": 1, "stem": "3 × 4 = (   )", "type": "填空",
                    "points": 4, "unit": 1, "ability": "掌握", "tier": "基础",
                    "answer": "12", "scoring_rules": "填对得 4 分。",
                    "hint": "三四十二。", "knowledge_points": ["M2U-1-02"],
                },
                {
                    "id": "q2", "no": 2, "stem": "23 + 49 = (   )", "type": "填空",
                    "points": 5, "unit": 2, "ability": "掌握", "tier": "基础",
                    "answer": "72", "scoring_rules": "填对得 5 分。",
                    "hint": "个位满十向十位进一。", "knowledge_points": ["M2U-2-01"],
                },
                {
                    "id": "q3", "no": 3, "stem": "每行种 5 棵树，种了 6 行，一共种了多少棵树？", "type": "应用题",
                    "points": 6, "unit": 1, "ability": "运用", "tier": "基础",
                    "answer": "30 棵", "scoring_rules": "列式 5 × 6 = 30 得 4 分，答语得 2 分。",
                    "hint": "6 个 5 相加用乘法。", "knowledge_points": ["M2U-1-03"],
                },
            ],
        }],
    }
    exam_path = tmp / "reg-math-01.json"
    exam_path.write_text(json.dumps(sample_exam, ensure_ascii=False, indent=1), encoding="utf-8")

    # 2a) render_exam --child 自动子目录 + 同名碰撞自动 -2 + 原地重渲不建 -3
    base_cmd = [sys.executable, str(SCRIPTS / "render_exam.py"), str(exam_path), "--child", "测试宝"]
    if not with_pdf:
        base_cmd.append("--md-only")
    code1, out1 = run(base_cmd, env=env)
    code2, out2 = run(base_cmd, env=env)
    dir1 = reg_home / "children" / child_id / "exams" / "reg-math-01"
    dir2 = reg_home / "children" / child_id / "exams" / "reg-math-01-2"
    rep.add(
        "render --child 子目录与防重名(-2)",
        PASS if (code1 == 0 and code2 == 0 and dir1.is_dir() and dir2.is_dir()) else FAIL,
        f"code={code1},{code2}",
    )

    # 原地重渲 dir1/exam.json 不应创建 -3
    inplace_cmd = [sys.executable, str(SCRIPTS / "render_exam.py"), str(dir1 / "exam.json"), "--child", "测试宝"]
    if not with_pdf:
        inplace_cmd.append("--md-only")
    code3, _ = run(inplace_cmd, env=env)
    dir3 = reg_home / "children" / child_id / "exams" / "reg-math-01-3"
    rep.add("render 原地重渲不重复编号", PASS if (code3 == 0 and not dir3.exists()) else FAIL)

    # --flat + --md-only
    flat_dir = tmp / "flat-out"
    code_flat, _ = run([
        sys.executable, str(SCRIPTS / "render_exam.py"), str(exam_path),
        "-o", str(flat_dir), "--flat", "--md-only",
    ], env=env)
    rep.add(
        "render --flat 平铺模式",
        PASS if (code_flat == 0 and (flat_dir / "reg-math-01_试卷.md").exists() and not (flat_dir / "exam.json").exists()) else FAIL,
    )

    # 3) 三种判分口径 + 错题同步
    d_old1 = (date.today() - timedelta(days=10)).isoformat()
    d_old2 = (date.today() - timedelta(days=9)).isoformat()
    log_file = reg_home / "children" / child_id / "practice_log.json"
    bank_file = reg_home / "children" / child_id / "mistakes.json"

    # 3a) --wrong-nos "2" + --sync-mistakes (满分15，第2题5分错 → 得10分)
    c_wn, o_wn = run([
        sys.executable, str(SCRIPTS / "practice_log.py"), "record",
        "--child", "测试宝", "--exam-json", str(dir1 / "exam.json"),
        "--wrong-nos", "2", "--sync-mistakes", "--date", d_old1,
    ], env=env)
    ok_wn = False
    if c_wn == 0 and log_file.exists() and bank_file.exists():
        ent = json.loads(log_file.read_text(encoding="utf-8"))["entries"][-1]
        bank = json.loads(bank_file.read_text(encoding="utf-8"))["mistakes"]
        ok_wn = (
            ent["total"] == 15 and ent["score"] == 10
            and ent["correct_count"] == 2 and ent["item_count"] == 3
            and len(bank) == 1 and bank[0]["count"] == 1
        )
    rep.add("判分 --wrong-nos + 错题同步", PASS if ok_wn else FAIL, o_wn.strip().splitlines()[-1] if o_wn.strip() else "")

    # 3b) --scores 支持小数部分得分 (4, 2.5, 6 → 12.5/15，第2题未满分自动同步并去重合并)
    c_sc, o_sc = run([
        sys.executable, str(SCRIPTS / "practice_log.py"), "record",
        "--child", "测试宝", "--exam-json", str(dir1 / "exam.json"),
        "--scores", "4,2.5,6", "--sync-mistakes", "--date", d_old2,
    ], env=env)
    ok_sc = False
    if c_sc == 0 and log_file.exists() and bank_file.exists():
        ent = json.loads(log_file.read_text(encoding="utf-8"))["entries"][-1]
        bank = json.loads(bank_file.read_text(encoding="utf-8"))["mistakes"]
        ok_sc = (
            ent["total"] == 15 and ent["score"] == 12.5
            and len(bank) == 1 and bank[0]["count"] == 2
        )
    rep.add("判分 --scores 小数得分与同题合并", PASS if ok_sc else FAIL, o_sc.strip().splitlines()[-1] if o_sc.strip() else "")

    # 3c) 断签检测：最近练习在 9 天前，当前 streak 应归零，longest_streak 应为 2
    c_st, o_st = run([
        sys.executable, str(SCRIPTS / "practice_log.py"), "stats", "--child", "测试宝",
    ], env=env)
    ok_st = False
    if c_st == 0:
        st = json.loads(o_st)
        ok_st = (st.get("current_streak") == 0 and st.get("longest_streak") == 2)
    rep.add("连续打卡断签归零 + 历史最长保留", PASS if ok_st else FAIL)

    # 4) 跨学科单元隔离：再记一条今日语文 U1 记录，验证 weak-points 和报告分开展示数U1 / 语U1
    cn_exam = {
        "schema": 1,
        "exam_id": "reg-cn-01",
        "created_at": date.today().isoformat(),
        "child": {"id": child_id, "nickname": "测试宝", "grade": 2, "term": "up"},
        "subject": "chinese",
        "kind": "dictation",
        "title": "二年级语文上册 · 回归听写",
        "scope": {"grade": 2, "term": "up", "units": [1], "textbook_edition": "统编版"},
        "difficulty_level": "basic",
        "total_points": 2,
        "suggested_minutes": 5,
        "sections": [{
            "id": "d", "name": "听写", "points": 2,
            "items": [
                {"id": "d1", "no": 1, "stem": "{{tianzige n=2}}", "type": "听写", "points": 1, "unit": 1,
                 "ability": "掌握", "tier": "基础", "answer": "天空", "scoring_rules": "1分", "hint": "读两遍", "knowledge_points": ["待归类"]},
                {"id": "d2", "no": 2, "stem": "{{tianzige n=2}}", "type": "听写", "points": 1, "unit": 1,
                 "ability": "掌握", "tier": "基础", "answer": "傍晚", "scoring_rules": "1分", "hint": "读两遍", "knowledge_points": ["待归类"]},
            ],
        }],
    }
    cn_exam_path = tmp / "reg-cn-01.json"
    cn_exam_path.write_text(json.dumps(cn_exam, ensure_ascii=False, indent=1), encoding="utf-8")
    c_rs, o_rs = run([
        sys.executable, str(SCRIPTS / "practice_log.py"), "record",
        "--child", "测试宝", "--exam-json", str(cn_exam_path), "--results", "1,0",
    ], env=env)
    c_wp, o_wp = run([
        sys.executable, str(SCRIPTS / "practice_log.py"), "weak-points", "--child", "测试宝",
    ], env=env)
    ok_wp = False
    if c_rs == 0 and c_wp == 0:
        wp = json.loads(o_wp)
        all_u = wp.get("all_units", {})
        weak_pairs = {(w["subject"], w["unit"]) for w in wp.get("weak_units", [])}
        ok_wp = (
            "1" in all_u.get("math", {}) and "1" in all_u.get("chinese", {})
            and ("math", 2) in weak_pairs and ("chinese", 1) in weak_pairs
        )
    rep.add("跨学科单元统计隔离", PASS if ok_wp else FAIL)

    # 5) 错题本导出与进度报告默认落盘 reports/（PDF 或 --md-only）
    exp_cmd = [sys.executable, str(SCRIPTS / "mistake_bank.py"), "export", "--child", "测试宝"]
    rep_cmd = [sys.executable, str(SCRIPTS / "generate_progress_report.py"), "--child", "测试宝"]
    if not with_pdf:
        exp_cmd.append("--md-only")
        rep_cmd.append("--md-only")
    else:
        rep_cmd.append("--keep-md")
    c_exp, o_exp = run(exp_cmd, env=env)
    c_rep, o_rep = run(rep_cmd, env=env)
    reports_dir = reg_home / "children" / child_id / "reports"
    ext = "pdf" if with_pdf else "md"
    exp_file = reports_dir / f"{date.today():%Y%m%d}_错题本.{ext}"
    rep_file = reports_dir / f"{date.today():%Y%m%d}_学习进度报告.{ext}"
    rep.add("错题本默认导出到 reports/", PASS if (c_exp == 0 and exp_file.exists()) else FAIL, o_exp.strip())
    ok_rep = c_rep == 0 and rep_file.exists()
    if ok_rep:
        md_check = (reports_dir / f"{date.today():%Y%m%d}_学习进度报告.md").read_text(encoding="utf-8")
        ok_rep = ("数U1:" in md_check and "语U1:" in md_check)
    rep.add("进度报告默认导出与多科标签", PASS if ok_rep else FAIL, o_rep.strip())

    # 6) 找朋友真实组词质量检查（不得残留占位符）
    zpy_path = tmp / "zhaopengyou.json"
    if zpy_path.exists():
        zpy = json.loads(zpy_path.read_text(encoding="utf-8"))
        z_items = zpy["sections"][0]["items"]
        bad_z = [
            it["answer"] for it in z_items
            if not it.get("answer") or "示例" in it["answer"] or "待补" in it["answer"] or "字组" in it["answer"]
        ]
        rep.add("找朋友真实词表反推无占位", PASS if (z_items and not bad_z) else FAIL, ", ".join(bad_z))


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

    try:
        with tempfile.TemporaryDirectory(prefix="pem-golden-") as td:
            tmp = Path(td)
            clean_pycache()  # 清理上次运行残留
            check_data_layer(rep)
            check_planners(rep)
            check_golden(rep, tmp, with_pdf, args.keyword)
            if not args.keyword:
                check_generators(rep, tmp, with_pdf)
                check_regressions(rep, tmp, with_pdf)
    finally:
        clean_pycache()  # 无论成功或异常都清理，避免 .pyc 占用资源配额

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
