#!/usr/bin/env python3
"""校验本插件在 Claude Code 与 Perch 两端都能被正确加载。

检查项：
  A. plugin.json —— Claude Code 与 Perch 共用的插件清单
     - 必填 name；Perch 额外要求 $schema 为 agent-plugins.org 1.0.0
     - Perch 只接受 name/version/description/homepage/repository/license/author/keywords/extensions
  B. SKILL.md frontmatter
     - name 必须与目录名一致（Perch 对插件内 skill 强制校验）
     - description 非空且 ≤1024 字符
     - metadata 用 kebab-case 键：surface-gui / surface-cli / trigger-hints / preferred-tools
     - surface 取值只能是 supported / limited / unsupported
     - body ≤64000 字节
  C. 资源配额（Perch 只登记 skill 目录下最多 50 个文件、深度 3、文本共 64KB）
  D. 路径可移植性：脚本不得依赖工作目录，文档不得残留 __SKILL_DIR__ 之类的自造占位符

用法:
    python3 "$SKILL_DIR/scripts/check_portability.py" [--json]

退出码：全部通过 0，否则 1。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
PLUGIN_DIR = SKILL_DIR.parent.parent

PERCH_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
SURFACE_VALUES = {"supported", "limited", "unsupported"}
MAX_DESCRIPTION = 1024
MAX_BODY_BYTES = 64_000
MAX_RESOURCES = 50
MAX_RESOURCE_DEPTH = 3
MAX_TEXT_BYTES = 64_000
TEXT_EXT = {".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".csv", ".tsv",
            ".xml", ".html", ".py", ".sh", ".bash", ".js", ".mjs", ".cjs",
            ".ts", ".sql", ".rb", ".ps1"}
SKIP_NAMES = {"SKILL.md", "node_modules", ".git", ".gitkeep", ".DS_Store"}
# Perch 允许的 plugin.json 字段
PERCH_PLUGIN_FIELDS = {"$schema", "name", "version", "description", "homepage",
                       "repository", "license", "author", "keywords", "extensions"}

results: list[tuple[str, str, str]] = []


def ok(name: str, detail: str = "") -> None:
    results.append(("PASS", name, detail))


def bad(name: str, detail: str) -> None:
    results.append(("FAIL", name, detail))


def warn(name: str, detail: str) -> None:
    results.append(("WARN", name, detail))


def load_yaml_frontmatter(text: str) -> dict | None:
    m = re.match(r"^---\r?\n([\s\S]*?)\r?\n---\r?\n?", text)
    if not m:
        return None
    try:
        import yaml
    except ImportError:
        return _mini_yaml(m.group(1))
    return yaml.safe_load(m.group(1))


def _mini_yaml(block: str) -> dict:
    """无 PyYAML 时的极简解析：只处理本 skill 用到的两层结构。"""
    out: dict = {}
    cur_key = None
    for raw in block.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if not raw.startswith((" ", "\t")):
            k, _, v = raw.partition(":")
            k, v = k.strip(), v.strip()
            if v:
                out[k] = v
                cur_key = None
            else:
                out[k] = {}
                cur_key = k
        elif cur_key:
            k, _, v = raw.strip().partition(":")
            out[cur_key][k.strip()] = v.strip()
    return out


def check_plugin_json() -> None:
    p = PLUGIN_DIR / ".claude-plugin" / "plugin.json"
    if not p.exists():
        bad("plugin.json 存在", str(p))
        return
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        bad("plugin.json 合法 JSON", str(e))
        return
    ok("plugin.json 合法 JSON")

    name = d.get("name")
    if not name:
        bad("plugin.json name", "缺少 name")
    elif not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", name) or len(name) > 64:
        bad("plugin.json name", f"{name!r} 不符合 Perch 插件名规则")
    else:
        ok("plugin.json name", name)

    if d.get("$schema") != PERCH_SCHEMA:
        bad("plugin.json $schema", f"Perch 要求 {PERCH_SCHEMA}，实际 {d.get('$schema')!r}")
    else:
        ok("plugin.json $schema")

    unknown = sorted(set(d) - PERCH_PLUGIN_FIELDS)
    if unknown:
        warn("plugin.json 字段", f"Perch 会忽略未知字段：{unknown}")
    else:
        ok("plugin.json 字段")

    if not d.get("license") and not (PLUGIN_DIR / "LICENSE").exists():
        warn("plugin.json license", "Claude Code 插件目录要求 license 或 LICENSE 文件")
    else:
        ok("plugin.json license")

    if not d.get("version"):
        warn("plugin.json version", "缺少 version，marketplace 无法感知更新")
    else:
        ok("plugin.json version", d["version"])


def check_skill_md() -> None:
    p = SKILL_DIR / "SKILL.md"
    if not p.exists():
        bad("SKILL.md 存在", str(p))
        return
    text = p.read_text(encoding="utf-8")
    fm = load_yaml_frontmatter(text)
    if not isinstance(fm, dict):
        bad("SKILL.md frontmatter", "缺少或无法解析 --- ... --- 块")
        return
    ok("SKILL.md frontmatter 可解析")

    dir_name = SKILL_DIR.name
    if fm.get("name") != dir_name:
        bad("SKILL.md name 与目录一致", f"name={fm.get('name')!r} 目录={dir_name!r}")
    else:
        ok("SKILL.md name 与目录一致", dir_name)

    desc = (fm.get("description") or "").strip()
    if not desc:
        bad("SKILL.md description", "为空")
    elif len(desc) > MAX_DESCRIPTION:
        bad("SKILL.md description 长度", f"{len(desc)} > {MAX_DESCRIPTION}")
    else:
        ok("SKILL.md description 长度", f"{len(desc)} 字符")

    meta = fm.get("metadata")
    if not isinstance(meta, dict):
        bad("SKILL.md metadata", "缺少 metadata 块（Perch 从 metadata 读 surface/trigger-hints）")
        return

    camel = [k for k in meta if "-" not in k and k not in ("name",)]
    if camel:
        warn("metadata 键名", f"Perch 只读 kebab-case 键，这些键会被忽略：{camel}")
    else:
        ok("metadata 键名 kebab-case")

    for key in ("surface-gui", "surface-cli"):
        v = meta.get(key)
        if v is None:
            warn(f"metadata {key}", "未声明，Perch 默认按 supported 处理")
        elif v not in SURFACE_VALUES:
            bad(f"metadata {key}", f"{v!r} 不在 {sorted(SURFACE_VALUES)}")
        else:
            ok(f"metadata {key}", v)

    hints = meta.get("trigger-hints")
    if hints:
        n = len(hints.split(",")) if isinstance(hints, str) else len(hints)
        ok("metadata trigger-hints", f"{n} 条")
    else:
        warn("metadata trigger-hints", "未声明，技能可能不会被自动激活")

    body = text[text.index("---", 3) + 3:] if text.count("---") >= 2 else ""
    body_bytes = len(body.encode("utf-8"))
    if body_bytes > MAX_BODY_BYTES:
        bad("SKILL.md body 大小", f"{body_bytes} > {MAX_BODY_BYTES} 字节，Perch 会截断")
    else:
        ok("SKILL.md body 大小", f"{body_bytes} 字节")


def check_resources() -> None:
    entries = 0
    text_bytes = 0
    too_deep: list[str] = []
    for p in sorted(SKILL_DIR.rglob("*")):
        if p.is_symlink() or not p.is_file():
            continue
        if p.name in SKIP_NAMES:
            continue
        rel = p.relative_to(SKILL_DIR)
        depth = len(rel.parts)
        if depth > MAX_RESOURCE_DEPTH:
            too_deep.append(str(rel))
            continue
        entries += 1
        if p.suffix.lower() in TEXT_EXT:
            sz = p.stat().st_size
            if sz <= 32_000 and text_bytes + sz <= MAX_TEXT_BYTES:
                text_bytes += sz

    if entries > MAX_RESOURCES:
        bad("资源文件数", f"{entries} > {MAX_RESOURCES}，Perch 会丢弃超出部分")
    elif entries >= MAX_RESOURCES:
        warn("资源文件数", f"{entries}/{MAX_RESOURCES}，已无余量")
    else:
        ok("资源文件数", f"{entries}/{MAX_RESOURCES}")

    # Perch 只把深度 ≤3 的文件登记为资源（内联给模型）；更深的文件不在资源清单里，
    # 但仍可通过 skill 目录路径用 bash / readLocalFile 读取，所以只是提示不是错误。
    if too_deep:
        warn("资源目录深度", f"{len(too_deep)} 个文件深于 {MAX_RESOURCE_DEPTH} 层，"
                              f"不会内联（仍可按路径读取）：{too_deep[:2]}")
    else:
        ok("资源目录深度")

    if text_bytes > MAX_TEXT_BYTES:
        bad("资源文本总量", f"{text_bytes} > {MAX_TEXT_BYTES} 字节")
    else:
        ok("资源文本总量", f"{text_bytes}/{MAX_TEXT_BYTES} 字节")

    pyc = [str(p.relative_to(SKILL_DIR)) for p in SKILL_DIR.rglob("*.pyc")]
    if pyc:
        warn("__pycache__ 残留", f"{len(pyc)} 个 .pyc 占用资源配额，建议清理")
    else:
        ok("无 .pyc 残留")


def check_portability() -> None:
    # 1) 文档里不得残留自造占位符
    placeholders = []
    for md in SKILL_DIR.glob("*.md"):
        txt = md.read_text(encoding="utf-8")
        for tok in ("__SKILL_DIR__", "{{SKILL_DIR}}", "${CLAUDE_PLUGIN_ROOT}"):
            if tok in txt:
                placeholders.append(f"{md.name}: {tok}")
    if placeholders:
        bad("无自造路径占位符", "；".join(placeholders))
    else:
        ok("无自造路径占位符")

    # 2) 脚本必须用 __file__ 定位，不能依赖 cwd
    # 只有需要自己定位 data/ 的脚本才必须用 __file__；纯生成器与接收路径参数的脚本不需要。
    cwd_dependent = []
    for py in (SKILL_DIR / "scripts").glob("*.py"):
        src = py.read_text(encoding="utf-8")
        needs_data = bool(re.search(r'["\'](?:data|curriculum|templates|knowledge)/', src))
        if not needs_data:
            continue
        if "__file__" not in src:
            cwd_dependent.append(py.name)
    if cwd_dependent:
        bad("脚本不依赖工作目录", f"读 data/ 但未用 __file__ 定位：{cwd_dependent}")
    else:
        ok("脚本不依赖工作目录")

    # 3) SKILL.md 必须说明如何解析 skill 目录
    skill_md = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    if "SKILL_DIR" not in skill_md:
        bad("SKILL.md 说明路径解析", "未提及 SKILL_DIR 解析方式")
    else:
        ok("SKILL.md 说明路径解析")


def main() -> int:
    as_json = "--json" in sys.argv[1:]
    check_plugin_json()
    check_skill_md()
    check_resources()
    check_portability()

    fails = [r for r in results if r[0] == "FAIL"]
    warns = [r for r in results if r[0] == "WARN"]

    if as_json:
        print(json.dumps(
            {"results": [{"status": s, "name": n, "detail": d} for s, n, d in results],
             "fails": len(fails), "warns": len(warns)},
            ensure_ascii=False, indent=1))
    else:
        for status, name, detail in results:
            if status == "PASS":
                continue
            print(f"{status} {name}" + (f" — {detail}" if detail else ""))
        print(f"{len(results)} 项检查：{len(fails)} 失败，{len(warns)} 警告")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
