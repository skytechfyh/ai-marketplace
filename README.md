# ai-marketplace

个人 AI 工具市场 —— 存放可跨项目、跨电脑复用的 **Plugins**，每个 Plugin 可包含 Skills、Agents、Commands、Hooks、MCP 配置。

遵循 Claude Code 官方 Plugin 规范，兼容未来其他 AI 助手的扩展体系。

---

## 目录结构

```
ai-marketplace/
├── .claude-plugin/
│   └── marketplace.json                # 私有市场索引
└── notes-from-docs/                    # Plugin：学习/培训资料转 Obsidian 笔记
    ├── .claude-plugin/
    │   └── plugin.json
    └── skills/
        └── notes-from-docs/
            ├── SKILL.md                 # 编排骨架：格式检测路由、全局硬规则
            ├── reference/                # 按格式/主题分文件的详细规则
            │   ├── extract-docx-pdf.md   # .docx/.doc/.pdf/.html/.htm 共用主流程
            │   ├── extract-html.md       # html 专属提取细节（复用上面主流程）
            │   ├── extract-mhtml.md      # 极客时间专栏 .mhtml
            │   ├── organize-course-package.md  # 极客时间课程资料包目录
            │   ├── visualization.md      # Mermaid/HTML卡片可视化规则（共享）
            │   ├── verification.md       # 核查脚本用法（共享）
            │   ├── math-latex.md         # 数学公式规范
            │   └── freshness-check.md    # 时效性复查流程
            └── scripts/                  # 提取/上传/核验脚本
                ├── extract_docx.py
                ├── extract_html.py
                ├── extract_batch.py
                ├── extract_mhtml_images.py
                ├── organize.py
                ├── upload_oss.py
                ├── ocr_image.py
                ├── suggest_diagrams.py
                ├── verify_content.py
                ├── check_mermaid.py
                ├── check_links.py
                └── extract_note_claims.py
```

---

## Plugin 规范（Claude Code）

每个 Plugin 遵循以下约定：

```
<plugin-name>/
├── .claude-plugin/
│   └── plugin.json     # 唯一必需文件（身份证）
├── commands/           # 斜杠命令（可选）
├── agents/             # 子代理（可选）
├── skills/             # Skills（可选）
│   └── <skill-name>/
│       └── SKILL.md
├── hooks/              # Hooks 配置（可选）
│   └── hooks.json
├── .mcp.json           # MCP 服务器配置（可选）
└── README.md
```

---

## 添加为私有市场

```bash
/plugin marketplace add https://github.com/fengyuhao/ai-marketplace
```

## 安装 Plugin

```bash
/plugin install notes-from-docs
```

## 更新 Plugin

```bash
/plugin update notes-from-docs
```

---

## 当前 Plugins

| Plugin | 描述 | 包含组件 |
|--------|------|---------|
| `notes-from-docs` | .docx/.doc/.pdf/.html/.htm 培训文档、极客时间 .mhtml 专栏、极客时间课程资料包目录 → Obsidian 笔记（合并自原 doc-to-notes + mhtml-refine-to-md + organize-course-package） | Skills + Scripts |

---

## 扩展新 Plugin

1. 在根目录创建 `<plugin-name>/` 文件夹
2. 添加 `.claude-plugin/plugin.json`（参考已有示例）
3. 按需添加 `commands/`、`agents/`、`skills/`、`hooks/`、`.mcp.json`
4. 在 `marketplace.json` 中追加一条记录
5. `git commit + git tag vX.Y.Z`
