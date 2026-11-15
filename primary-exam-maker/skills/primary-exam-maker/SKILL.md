---
name: primary-exam-maker
description: Generate printable primary school practice sheets, unit/midterm/final exams, oral math cards, dictations, and separated parent answer keys with grading tables in Chinese, Math, and English (Grades 2-3). Use when the user asks to create exams, oral math sheets, dictations, mistake-targeted practice, knowledge-point drills, or manage child study profiles.
metadata:
  surface-gui: supported
  surface-cli: supported
  trigger-hints: 出试卷, 出题, 单元测验, 期中卷, 期末卷, 口算卡, 听写单, 错题专项, 知识点专项, 打印练习卷, 孩子档案, primary exam, printable worksheet, dictation sheet
  preferred-tools: bash, readLocalFile, writeLocalFile, glob, grep, read_document, visionInspect
---

# Primary Exam Maker

为家庭日常出可打印的小学练习卷与测试卷（语文统编版、数学苏教版、英语译林版，优先覆盖二、三年级），孩子试卷与家长答案/阅卷表严格分离。

## 路径约定（先读这一条）

本 skill 的所有脚本与数据都在**本 SKILL.md 所在目录**下。执行任何命令前，先把该目录解析成绝对路径，后续命令一律用它，不要用相对路径（工作目录不一定是 skill 目录）：

```bash
SKILL_DIR="$(cd "$(dirname "<本 SKILL.md 的绝对路径>")" && pwd)"
```

- 在 Perch Desktop / CLI 中：skill 目录由运行时给出（`Skill directory:` 一行），直接使用。
- 在 Claude Code 中：插件安装在 `~/.claude/plugins/cache/<marketplace>/primary-exam-maker/<version>/skills/primary-exam-maker`，用 `ls` 确认版本目录后再拼路径。
- 下文所有 `$SKILL_DIR/scripts/...` 都指这个绝对路径。

## 工作流程

### 0. 整卷先做组卷规划
- 单元/期中/期末卷先运行 `python3 "$SKILL_DIR/scripts/plan_exam.py" --subject <math|chinese|english> --grade <2|3> --term <up|down> --kind <unit|midterm|final> [--units 1,2] [--difficulty basic|standard|advanced]`，按输出的大题结构、分值、可用知识点与字词范围出题；不要凭记忆编模板。
- 专项练习（题型/知识点/错题）不走此脚本，按第 2 步确认参数后直接出题。

### 1. 识别孩子与检查数据时效
- 运行 `python3 "$SKILL_DIR/scripts/profile.py" get <称呼>` 解析孩子档案与当前推算年级/学期。
- 若 `~/.primary-exam/profiles.json` 尚无该孩子档案，先向家长确认**昵称**和**小学入学年份**，再用 `profile.py add` 建档（不猜年份）。
- 运行 `python3 "$SKILL_DIR/scripts/profile.py" check-freshness`；若有教材数据校对超过 180 天，先提醒家长。

### 2. 确认出卷参数（缺项主动追问）
确认：**孩子 / 学科 / 卷种**（单元测验、期中、期末、口算卡、听写单、题型专项、知识点专项、错题专项）**/ 范围（单元） / 难度等级**（`basic` 基础卷、`standard` 标准卷默认、`advanced` 提高卷）。
- 专项练习（题型 / 知识点 / 错题）**必须先向家长确认题数**，不要替家长决定。
- 知识点专项先运行 `python3 "$SKILL_DIR/scripts/plan_kp_drill.py" --subject ... --grade ... --term ... --kp <知识点ID> --count <题数>`，按输出的“理解→基础练→变式→综合”梯度与错因出题。
- 错题定向输入（文字或图片）必须先列出“题干 / 孩子错答 / 正确答案 / 错因”，**等家长确认后再出题**。

### 3. 加载教材范围与结构模板
- 读取 `$SKILL_DIR/data/curriculum/<subject>/<subject>_g<grade>_<up|down>.json`（及语文字表 `*_tables.json`、英语词表 `*_wordlist.json`）确定合法字词与单元边界。
- 整卷（单元/期中/期末）对照 `$SKILL_DIR/data/templates/exam_templates.json` 的大题结构与 100 分分配（不设卷面分）。
- 知识点目录 `$SKILL_DIR/data/knowledge/<subject>/<subject>_g<grade>_<up|down>.json` 十册已全部建好，按知识点 ID 与能力层级选题。

### 4. 生成 JSON → 机械校验 → 渲染分离产物
1. 将题目落为结构化中间格式 JSON（含 `answer`、`scoring_rules`、`hint`、`tier`、`ability` 与必需的 `figure`/`layout`）。
2. 执行 `python3 -I "$SKILL_DIR/scripts/validate_exam.py" <exam.json>`；**校验不通过（如总分≠100、缺图、超纲、基础卷含拔高题）不得渲染**。若出现近重复题干、同源错题重复、跨大题算式撞车或口算得数扎堆 warning，应先改题去重。
3. 执行 `python3 -I "$SKILL_DIR/scripts/verify_exam.py" <exam.json>` 做学科内容核验（数学复算纯算式、英语选项与词表范围、语文词语表/字表范围）；有 FAIL 必须修正后才能渲染，warning 需人工确认。
4. 执行 `python3 "$SKILL_DIR/scripts/render_exam.py" <exam.json> -o <输出目录> --pdf` 生成分离的：
   - `<stem>_试卷.md` / `.pdf`（给孩子，无任何答案与提示）
   - `<stem>_答案与评分.md` / `.pdf`（给家长，含答案、评分细则、讲评话术与可打印阅卷表）
5. 若家长修改了 `.md` 文件，使用 `python3 "$SKILL_DIR/scripts/render_pdf.py" <file.md>` 重新打印 PDF。

### 5. 口算卡与听写单（代码生成，答案绝对正确）
- **口算卡（F6）**：先向家长确认年级/学期、题数与范围（单元或主题），再运行
  `python3 "$SKILL_DIR/scripts/generate_oral_math.py" --grade <2|3> --term <up|down> [--units 1,2] [--topics mul,div,rem,add100,add1000,mul_1digit,div_1digit,mul_2digit,fraction,mix] --count <题数> [--seed 42] -o <exam.json>`；
  随后照常 `validate_exam.py` → `render_exam.py --pdf`。题目与答案由代码生成，必须用脚本而不是手写。
- **听写单（F7）**：确认学科、年级/学期、单元范围与词数（语文可选 `--mode words|writing|literacy|mixed`），运行
  `python3 "$SKILL_DIR/scripts/generate_dictation.py" --subject <chinese|english> --grade <2|3> --term <up|down> [--units 1-2] [--count 20] [--mode words] [--include-noncore] -o <exam.json>`；
  语文可加 `--audio <输出.aiff>` 用 macOS `say` 生成朗读音频（每词两遍，语文用 Ting-Ting 语音，英语用 Samantha 语音）。之后同样走校验与渲染。

### 6. 游戏化识字（语文专项）
- **游戏化识字练习**：四种趣味题型——连线、找朋友、猜字谜、看图选字，从写字表/词语表自动抽取内容，`kind = "topic"`，走标准校验渲染链路。
  `python3 "$SKILL_DIR/scripts/generate_gamified_chinese.py" --grade <2|3> --term <up|down> [--units 1,2] --type <lianxian|zhaopengyou|caizimi|tupian_xuanzi|mixed> [--count 4] [--seed 42] -o <exam.json>`
  - `lianxian`（连线）和 `zhaopengyou`（找朋友）可全自动生成；
  - `caizimi`（猜字谜）和 `tupian_xuanzi`（看图选字）脚本生成框架，**谜面/图意描述需模型按教材字义替换后再出卷**。
  - 四种指令也可在手写 JSON 的 stem 中直接使用（见 REFERENCE.md §3F）。

### 7. 故事化应用题与语音鼓励
- **故事化应用题**：出数学应用题时，先运行 `python3 "$SKILL_DIR/scripts/story_themes.py" sample <主题> [--seed N] [--template 乘法_行列|加减_合并|除法_平分]` 获取情境参数，把经典题干里的通用词（树/棵/行）替换为主题词（恐龙蛋/枚/窝），填入具体数值后写入 `stem`。可用主题：`恐龙`、`太空`、`海洋`、`农场`、`糖果`、`运动会`。
- **语音鼓励**：生成听写单音频时加 `--audio-score <得分> --audio-total <满分>`，音频结尾自动按得分率朗读鼓励语（见 REFERENCE.md §3J）。

### 8. 每日练习卡与进度跟踪
- **每日练习卡**：根据孩子当前年级/学期/单元，自动生成小型混合练习（当日新学 60% + 螺旋复习 40%），默认 10 题、5-15 分钟完成。
  `python3 "$SKILL_DIR/scripts/generate_daily_practice.py" --subject <math|chinese|english> --grade <2|3> --term <up|down> --current-unit <N> [--count 10] [--mode words] [--seed 42] [--child-id <id> --child-nickname <称呼>] -o <exam.json>`；
  随后照常 `validate_exam.py` → `render_exam.py --pdf`。适合每日固定练习、培养学习习惯。
- **记录成绩**：孩子完成后，家长用 `practice_log.py` 记录成绩。
  - 详细记录（推荐，自动提取单元/逐题对错）：`python3 "$SKILL_DIR/scripts/practice_log.py" record --child <称呼> --exam-json <exam.json> --scores "1,0,1,1,1,1,1,0,1,1"`
  - 简单记录（只记总分）：`python3 "$SKILL_DIR/scripts/practice_log.py" record --child <称呼> --subject math --total 10 --score 8`
- **查看学情**：`python3 "$SKILL_DIR/scripts/practice_log.py" stats --child <称呼>`（总次数/正确率/连续打卡/分单元），`weak-points --child <称呼>`（薄弱单元推荐重点复习）。
- **进度报告**：`python3 "$SKILL_DIR/scripts/generate_progress_report.py" --child <称呼> [-o report.md] [--last 14] [--subject math]`，生成含条形图的 Markdown 报告，再 `python3 "$SKILL_DIR/scripts/render_pdf.py" report.md -o report.pdf` 渲染为可打印 PDF。

## 关键约束
- 个人档案与产出默认放在 `~/.primary-exam/children/<id>/` 或用户指定目录，**绝不写入插件仓库**。
- 所有几何/钟表/统计图必须通过 `figure` 字段或 `{{fig_...}}` 指令由代码生成，禁止手写不准确的描述替代配图。
- 仅使用真实存在于 `scripts/` 和 `data/` 的脚本与数据；不要虚构命令。口算卡与听写单已提供代码生成脚本；其余专项（错题、题型、知识点）由模型按 JSON → 校验 → 渲染链路出题。
- 运行环境：脚本兼容 `Python >= 3.9`；使用 `--pdf` 或 `render_pdf.py` 需安装 Python `markdown` 包及本地 Chrome / Chromium / Edge。
- 详细 JSON schema、指令语法与脚本参数见同目录 [REFERENCE.md](REFERENCE.md)。

## 自检（改完脚本或数据后跑）
```bash
python3 -I "$SKILL_DIR/scripts/validate_knowledge.py"
python3 -I "$SKILL_DIR/scripts/validate_templates.py"
python3 -I "$SKILL_DIR/scripts/normalize_english_wordlist.py" --check
python3 "$SKILL_DIR/scripts/run_golden.py"
```
