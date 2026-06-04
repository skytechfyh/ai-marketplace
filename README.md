# ai-marketplace

个人 AI 工具市场 —— 存放可跨项目、跨电脑复用的 **Plugins**，每个 Plugin 可包含 Skills、Agents、Commands、Hooks、MCP 配置。

遵循 Claude Code 官方 Plugin 规范，兼容未来其他 AI 助手的扩展体系。

---

## 目录结构

```
ai-marketplace/
├── marketplace.json                    # 私有市场索引
├── doc-to-notes/                       # Plugin：文档转笔记
│   ├── .claude-plugin/
│   │   └── plugin.json
│   ├── skills/
│   │   └── doc-to-notes/
│   │       ├── SKILL.md
│   │       ├── REFERENCE.md
│   │       └── scripts/
│   │           ├── extract_docx.py
│   │           ├── upload_oss.py
│   │           ├── ocr_image.py
│   │           └── suggest_diagrams.py
│   └── README.md
├── mhtml-refine-to-md/                 # Plugin：极客时间 mhtml 转笔记
│   ├── .claude-plugin/
│   │   └── plugin.json
│   ├── skills/
│   │   └── mhtml-refine-to-md/
│   │       ├── SKILL.md
│   │       └── scripts/
│   │           └── extract_images.py
│   └── README.md
└── organize-course-package/            # Plugin：极客时间资料包整合
    ├── .claude-plugin/
    │   └── plugin.json
    ├── skills/
    │   └── organize-course-package/
    │       ├── SKILL.md
    │       └── scripts/
    │           └── organize.py
    └── README.md
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
/plugin install doc-to-notes            # 安装单个
/plugin install mhtml-refine-to-md
/plugin install organize-course-package
```

## 更新 Plugin

```bash
/plugin update doc-to-notes
```

---

## 当前 Plugins

| Plugin | 描述 | 包含组件 |
|--------|------|---------|
| `doc-to-notes` | .docx/.doc/.pdf → Obsidian 笔记 | Skills + Scripts |
| `mhtml-refine-to-md` | 极客时间 .mhtml → Obsidian 笔记 | Skills + Scripts |
| `organize-course-package` | 极客时间资料包 → Obsidian 笔记 | Skills + Scripts |

---

## 扩展新 Plugin

1. 在根目录创建 `<plugin-name>/` 文件夹
2. 添加 `.claude-plugin/plugin.json`（参考已有示例）
3. 按需添加 `commands/`、`agents/`、`skills/`、`hooks/`、`.mcp.json`
4. 在 `marketplace.json` 中追加一条记录
5. `git commit + git tag vX.Y.Z`
