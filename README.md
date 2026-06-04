# ai-marketplace

个人 AI 工具市场 —— 存放可跨项目、跨电脑复用的 Claude Code / 未来其他 AI 助手的 **skills、agents、plugins**。

---

## 目录结构

```
ai-marketplace/
├── install.sh                        # 一键安装脚本
├── skills/                           # Claude Code Skills
│   ├── doc-to-notes/                 # .docx/.doc/.pdf → Obsidian 笔记
│   │   ├── SKILL.md
│   │   ├── REFERENCE.md
│   │   └── scripts/
│   │       ├── extract_docx.py
│   │       ├── upload_oss.py
│   │       ├── ocr_image.py
│   │       └── suggest_diagrams.py
│   ├── mhtml-refine-to-md/           # 极客时间 .mhtml → Obsidian 笔记
│   │   ├── SKILL.md
│   │   └── scripts/
│   │       └── extract_images.py
│   └── organize-course-package/      # 极客时间资料包 → Obsidian 笔记
│       ├── SKILL.md
│       └── scripts/
│           └── organize.py
├── agents/                           # (预留) 自定义 Agent 定义
└── plugins/                          # (预留) 插件扩展
```

---

## 安装到项目

### 安装全部 skills

```bash
./install.sh /path/to/your-project
```

### 安装指定 skill

```bash
./install.sh /path/to/your-project doc-to-notes
./install.sh /path/to/your-project mhtml-refine-to-md organize-course-package
```

安装脚本会：
1. 将 skill 目录复制到 `<项目>/.claude/skills/<skill名称>/`
2. 自动将 `SKILL.md` 中的 `__SKILL_DIR__` 替换为实际安装路径
3. 给 Python 脚本添加可执行权限

### 安装后的手动配置

部分 skill 包含用户特定的路径占位符，安装后需手动编辑：

| Skill | 占位符 | 说明 |
|---|---|---|
| `organize-course-package` | `__SOURCE_DIR__` | 资料包所在目录 |
| `organize-course-package` | `__OUTPUT_DIR__` | 输出目标目录 |
| `mhtml-refine-to-md` | `Target_Directory` | 默认笔记输出目录 |
| `doc-to-notes` | Step 1 目标路径 | BigData/Middleware 等分支路径 |

---

## Skills 说明

### doc-to-notes
将 `.docx`/`.doc`/`.pdf` 培训文档转换为结构化 Obsidian Markdown 笔记。

- 逐章拆分、提炼内容为 Mermaid 图 + HTML 卡片 + Callout 结构
- 图片上传至阿里云 OSS，截图 OCR（Apple Vision）+ 视觉分析
- 内容自动升级到最新稳定版本（对 Flink/Spark 等技术版本变化处理）
- 需要安装：`pip install python-docx oss2 pymupdf pillow ocrmac`

### mhtml-refine-to-md
将极客时间专栏 `.mhtml` 文件提炼为高质量 Obsidian 笔记。

- 解析 Slate.js 富文本，提取正文/图片/思考题
- 图片按类型处理：架构图→Mermaid、信息图→HTML卡片、代码截图→代码块
- 包含质量核查 checklist（字数比、覆盖率、可视化块）
- 仅适用于 time.geekbang.org 站点

### organize-course-package
将极客时间课程资料包（md版本目录 + PDF 课件）合并为单一 Obsidian 笔记。

- 本地图片批量上传至阿里云 OSS
- PDF 课件自动提取，可选调用 Claude API 重排
- Mermaid 语法自动校验修复

---

## 依赖

```bash
# 所有 skills 共用的 Python 依赖
pip install oss2 pymupdf python-docx pillow ocrmac
```

OSS 配置（阿里云）已内置在脚本中，如需更换请修改 `upload_oss.py` 和 `organize.py` 中的常量。

---

## 扩展

后续添加新 skill：
1. 在 `skills/` 下创建新目录，包含 `SKILL.md` 和可选的 `scripts/`
2. `SKILL.md` 中的脚本路径使用 `__SKILL_DIR__` 占位符
3. `install.sh` 会自动处理，无需修改

添加 agent/plugin：参考 `agents/` 和 `plugins/` 目录（预留，待后续补充）。
