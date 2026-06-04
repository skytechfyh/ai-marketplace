#!/usr/bin/env bash
# install.sh — 将 ai-marketplace 中的 skill/agent/plugin 安装到目标项目
#
# 用法：
#   ./install.sh <目标项目路径> [skill名称1 skill名称2 ...]
#
# 示例：
#   ./install.sh ~/SecondBrain                        # 安装全部 skills
#   ./install.sh ~/SecondBrain doc-to-notes           # 只安装指定 skill
#   ./install.sh ~/my-project mhtml-refine-to-md organize-course-package

set -euo pipefail

MARKETPLACE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── 参数解析 ─────────────────────────────────────────────────────────────────
if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <target-project-dir> [skill1 skill2 ...]"
  exit 1
fi

TARGET_DIR="$(cd "$1" && pwd)"
shift

# ── 确定要安装的 skills ───────────────────────────────────────────────────────
SKILLS_SRC="$MARKETPLACE_DIR/skills"
if [[ $# -gt 0 ]]; then
  SELECTED=("$@")
else
  # 默认安装所有 skills
  mapfile -t SELECTED < <(ls "$SKILLS_SRC")
fi

# ── 安装目标目录 ──────────────────────────────────────────────────────────────
DEST_SKILLS="$TARGET_DIR/.claude/skills"
mkdir -p "$DEST_SKILLS"

echo "🛒  ai-marketplace installer"
echo "    Marketplace : $MARKETPLACE_DIR"
echo "    Target      : $TARGET_DIR"
echo "    Skills      : ${SELECTED[*]}"
echo ""

# ── 安装每个 skill ────────────────────────────────────────────────────────────
for skill in "${SELECTED[@]}"; do
  SRC="$SKILLS_SRC/$skill"
  if [[ ! -d "$SRC" ]]; then
    echo "  ⚠️  Skill '$skill' not found in marketplace, skipping"
    continue
  fi

  DEST="$DEST_SKILLS/$skill"
  echo "  📦  Installing skill: $skill"

  # 覆盖式复制（保留已有的其他文件）
  cp -r "$SRC/." "$DEST/"

  # 将 SKILL.md 中的 __SKILL_DIR__ 替换为实际安装路径
  SKILL_MD="$DEST/SKILL.md"
  if [[ -f "$SKILL_MD" ]]; then
    # macOS sed 需要 -i '' 参数
    sed -i '' "s|__SKILL_DIR__|$DEST|g" "$SKILL_MD"
    echo "       ✓ SKILL.md path resolved → $DEST"
  fi

  # 给脚本加可执行权限
  if [[ -d "$DEST/scripts" ]]; then
    chmod +x "$DEST/scripts/"*.py 2>/dev/null || true
  fi

  echo "       ✓ Installed to $DEST"
done

echo ""
echo "✅  Done. Open the target project in Claude Code to use the installed skills."
echo ""
echo "⚠️  提醒：以下 skill 包含用户特定路径，安装后请手动编辑 SKILL.md 中的占位符："
echo "    • organize-course-package: __SOURCE_DIR__ / __OUTPUT_DIR__"
echo "    • mhtml-refine-to-md: Target_Directory 默认输出路径"
echo "    • doc-to-notes: Step 1 目标目录（BigData/Middleware 等分支路径）"
