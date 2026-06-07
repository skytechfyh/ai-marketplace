# ai-marketplace

个人 Claude Code 插件市场，存放可跨项目、跨设备复用的 Skills、Agents 等插件。

## 项目结构

```
.claude-plugin/marketplace.json   # 市场注册表，列出所有插件及其版本
<plugin-name>/
  .claude-plugin/plugin.json      # 单插件元数据（name、version、description）
  skills/<skill-name>/
    SKILL.md                      # skill 主文件，Claude 读取并执行
    REFERENCE.md                  # 补充参考（可选）
    scripts/                      # 辅助脚本（Python 等）
```

## 版本管理规范

**每次修改插件内容后，必须同步 bump 版本号（两处都要改）：**

1. `<plugin-name>/.claude-plugin/plugin.json` → `"version"`
2. `.claude-plugin/marketplace.json` → 对应插件的 `"version"`

版本号规则（语义化）：
- `patch`（x.x.+1）：文字修正、说明优化、规则补充
- `minor`（x.+1.0）：新增功能、新增 script、流程重构
- `major`（+1.0.0）：破坏性变更、整体重写

> 版本不 bump，marketplace 无法感知更新，已安装的用户不会收到新版本。

## 提交规范

```
feat(<plugin-name>): 描述新功能
fix(<plugin-name>): 描述修复内容
docs(<plugin-name>): 说明/注释更新
```

## 当前插件列表

| 插件 | 当前版本 | 用途 |
|---|---|---|
| `doc-to-notes` | 见 plugin.json | .docx/.doc/.pdf 转 Obsidian 笔记 |
| `mhtml-refine-to-md` | 见 plugin.json | 极客时间 .mhtml 提炼为学习笔记 |
| `organize-course-package` | 见 plugin.json | 极客时间课程资料包整合为笔记 |
