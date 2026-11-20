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

### 1. 识别孩子与检查数据时效
- 运行 `python3 "$SKILL_DIR/scripts/profile.py" get <称呼>` 解析孩子档案与当前推算年级/学期。
- 若 `~/.primary-exam/profiles.json` 尚无该孩子档案，先向家长确认**昵称**和**小学入学年份**，再用 `profile.py add` 建档（不猜年份）。
- 运行 `python3 "$SKILL_DIR/scripts/profile.py" check-freshness`；若有教材数据校对超过 180 天，先提醒家长。

### 2. 确认出卷参数与组卷规划（缺项主动追问）
确认：**孩子 / 学科 / 卷种**（单元测验、期中、期末、口算卡、听写单、题型专项、知识点专项、错题专项）**/ 范围（单元） / 难度等级**（`basic` 基础卷、`standard` 标准卷默认、`advanced` 提高卷）。
- **整卷（单元/期中/期末）**：运行 `python3 "$SKILL_DIR/scripts/plan_exam.py" --subject <math|chinese|english> --grade <2|3> --term <up|down> --kind <unit|midterm|final> [--units 1,2] [--difficulty basic|standard|advanced]`，按输出的大题结构、分值、可用知识点与字词范围出题；不要凭记忆编模板。
- **专项练习（题型 / 知识点 / 错题）必须先向家长确认题数**，不要替家长决定。
- **知识点专项**：先运行 `python3 "$SKILL_DIR/scripts/plan_kp_drill.py" --subject ... --grade ... --term ... --kp <知识点ID> --count <题数>`，按输出的“理解→基础练→变式→综合”梯度与错因出题。
- **错题定向专项**：收到文字或图片错题后，先列出“题干 / 孩子错答 / 正确答案 / 错因”，**等家长确认后再出题**；确认后顺手用 `mistake_bank.py add` 写入该孩子的错题库（`~/.primary-exam/children/<id>/mistakes.json`）。
- **错题复习 / 错题本抽题**：先运行 `python3 "$SKILL_DIR/scripts/mistake_bank.py" due --child <称呼>` 查看到期错题再出变式。

### 3. 加载教材范围与结构模板
- 读取 `$SKILL_DIR/data/curriculum/<subject>/<subject>_g<grade>_<up|down>.json`（及语文字表 `*_tables.json`、英语词表 `*_wordlist.json`）确定合法字词与单元边界。
- 整卷（单元/期中/期末）对照 `$SKILL_DIR/data/templates/exam_templates.json` 的大题结构与 100 分分配（不设卷面分）。
- 知识点目录 `$SKILL_DIR/data/knowledge/<subject>/<subject>_g<grade>_<up|down>.json` 十册已全部建好，按知识点 ID 与能力层级选题。

### 4. 生成 JSON → 校验核验 → 渲染分离 PDF
1. 将题目落为结构化中间格式 JSON（含 `answer`、`scoring_rules`、`hint`、`tier`、`ability` 与必需的 `figure`/`layout`）。
2. 执行 `python3 -I "$SKILL_DIR/scripts/validate_exam.py" <exam.json>` 与 `python3 -I "$SKILL_DIR/scripts/verify_exam.py" <exam.json>` 检查结构、去重与学科内容；有 FAIL 必须修正，若出现近重复题干、同源错题重复、跨大题算式撞车或口算得数扎堆 warning，应先改题去重。
3. 执行渲染（内置再次执行 `validate_exam` + `verify_exam`，默认直接输出 PDF、不落盘 `.md`，并按当次出卷建独立子目录、归档 `exam.json`）：
   ```bash
   python3 "$SKILL_DIR/scripts/render_exam.py" <exam.json> --child <称呼>
   ```
   （也可传 `-o <自定义根目录>`；同名目录已存在时自动追加 `-2`、`-3` 防覆盖；仅在需手工修改 Markdown 时加 `--keep-md`）。
   输出目录 `~/.primary-exam/children/<id>/exams/<exam_id>/` 内含：
   - `exam.json`（结构化源，供后续记成绩、错题入库或重渲）
   - `<exam_id>_试卷.pdf`（给孩子，无任何答案、提示与知识点编号）
   - `<exam_id>_答案与评分.pdf`（给家长，含答案、评分细则、讲评话术与可打印阅卷表）
4. 若家长手工修改了保留的 `.md` 文件，可用 `python3 "$SKILL_DIR/scripts/render_pdf.py" <file.md>` 重新打印 PDF。

### 5. 口算卡与听写单（代码生成，答案绝对正确）
- **口算卡（F6）**：先向家长确认年级/学期、题数与范围（单元或主题），再运行
  `python3 "$SKILL_DIR/scripts/generate_oral_math.py" --grade <2|3> --term <up|down> [--units 1,2] [--topics mul,div,rem,add100,add1000,mul_1digit,div_1digit,mul_2digit,fraction,mix] --count <题数> [--seed 42] -o <exam.json>`；
  随后 `render_exam.py <exam.json> --child <称呼>`。题目与答案由代码生成，必须用脚本而不是手写。
- **听写单（F7）**：确认学科、年级/学期、单元范围与词数（语文可选 `--mode words|writing|literacy|mixed`），运行
  `python3 "$SKILL_DIR/scripts/generate_dictation.py" --subject <chinese|english> --grade <2|3> --term <up|down> [--units 1-2] [--count 20] [--mode words] [--include-noncore] [--audio <输出.m4a>] -o <exam.json>`；
  中英文均支持 `--audio` 用 macOS `say` 生成每词两遍音频（推荐 `.m4a` 便于手机播放，也支持 `.aiff`；语文 Ting-Ting、英语 Samantha，结尾鼓励语按语种自动匹配）。渲染后可将音频放在同一试卷子目录下。

### 6. 游戏化识字（语文专项）
- **游戏化识字练习**：四种趣味题型——找朋友、连线、猜字谜、看图选字，从本册字表/词语表抽取内容，`kind = "topic"`，走标准校验渲染链路。
  `python3 "$SKILL_DIR/scripts/generate_gamified_chinese.py" --grade <2|3> --term <up|down> [--units 1,2] --type <zhaopengyou|lianxian|caizimi|tupian_xuanzi|mixed> [--count 4] [--seed 42] -o <exam.json>`
  - `zhaopengyou`（找朋友）基于本册词语表反推真实二字词，**可全自动生成真实组词答案与干扰字**；
  - `lianxian`（连线）、`caizimi`（猜字谜）、`tupian_xuanzi`（看图选字）脚本只生成框架，**出卷前须由模型补全真实配对/谜面/图意与答案后再渲染**。
  - 四种指令也可在手写 JSON 的 stem 中直接使用（见 REFERENCE.md §3F）。

### 7. 故事化应用题与语音鼓励
- **故事化应用题**：出数学应用题时，先运行 `python3 "$SKILL_DIR/scripts/story_themes.py" sample <主题> [--seed N] [--template 乘法_行列|加减_合并|除法_平分]` 获取情境参数，把经典题干里的通用词（树/棵/行）替换为主题词（恐龙蛋/枚/窝），填入具体数值后写入 `stem`。可用主题：`恐龙`、`太空`、`海洋`、`农场`、`糖果`、`运动会`。
- **语音鼓励**：生成听写单音频时加 `--audio-score <得分> --audio-total <满分>`，音频结尾按学科语种与得分率自动朗读鼓励语（见 REFERENCE.md §3J）。

### 8. 每日练习卡、成绩记录、错题本与进度报告
- **每日练习卡**：根据孩子当前年级/学期/单元，自动生成小型混合练习（当日新学 60% + 螺旋复习 40%），默认 10 题、5-15 分钟完成。
  `python3 "$SKILL_DIR/scripts/generate_daily_practice.py" --subject <math|chinese|english> --grade <2|3> --term <up|down> --current-unit <N> [--count 10] [--mode words] [--seed 42] [--child-id <id> --child-nickname <称呼>] -o <exam.json>`；
  随后 `render_exam.py <exam.json> --child <称呼>`。
- **一步记成绩 + 同步错题入库**（推荐）：支持三种判分口径——`--wrong-nos`（只报做错题号，最省事）、`--results`（逐题对错 1/0）、`--scores`（逐题实得分，支持小数如 `2.5`），加 `--sync-mistakes` 同步将错题写入错题库：
  - 按错题题号：`python3 "$SKILL_DIR/scripts/practice_log.py" record --child <称呼> --exam-json <子目录/exam.json> --wrong-nos "2,5" --sync-mistakes`
  - 按逐题对错：`python3 "$SKILL_DIR/scripts/practice_log.py" record --child <称呼> --exam-json <子目录/exam.json> --results "1,0,1,1,0" --sync-mistakes`
  - 按逐题实得分：`python3 "$SKILL_DIR/scripts/practice_log.py" record --child <称呼> --exam-json <子目录/exam.json> --scores "4,0,5,6,2.5" --sync-mistakes`
  - 简单记录（只记总分）：`python3 "$SKILL_DIR/scripts/practice_log.py" record --child <称呼> --subject math --total 100 --score 92.5`
- **错题本与间隔复习**（统一保存在 `~/.primary-exam/children/<id>/mistakes.json`）：
  - 单题入库（同题自动合并计数）：`python3 "$SKILL_DIR/scripts/mistake_bank.py" add --child <称呼> --subject math --stem "..." --wrong-answer "..." --correct-answer "..." --error-type "..."`
  - 单独从试卷批量入库：`python3 "$SKILL_DIR/scripts/mistake_bank.py" add-from-exam --child <称呼> --exam-json <exam.json> --wrong-nos "2,5"`（也支持 `--results` / `--scores`）
  - 查看今日到期错题：`python3 "$SKILL_DIR/scripts/mistake_bank.py" due --child <称呼>`
  - 记录复习结果（3/7/14/30 天间隔）：`python3 "$SKILL_DIR/scripts/mistake_bank.py" review --child <称呼> --ids m_001 --passed`（或 `--failed`）
  - 导出可打印错题本 PDF：`python3 "$SKILL_DIR/scripts/mistake_bank.py" export --child <称呼>`（默认直接输出 `~/.primary-exam/children/<id>/reports/<日期>_错题本.pdf`）
- **查看学情**：`practice_log.py stats --child <称呼> [--subject math]`、`weak-points --child <称呼> [--subject math]`（按学科隔离单元，不跨科混淆）、`mistake_bank.py stats --child <称呼>`。
- **进度报告 PDF**：`python3 "$SKILL_DIR/scripts/generate_progress_report.py" --child <称呼> [--last 14] [--subject math]`，默认直接渲染含条形图的 PDF 到 `~/.primary-exam/children/<id>/reports/<日期>_学习进度报告.pdf`。

## 关键约束
- 个人数据与产物统一按孩子隔离存放在 `~/.primary-exam/children/<id>/`（**绝不写入插件仓库**）：
  - `exams/<exam_id>/`：每次出卷独立子目录（`exam.json` + `<exam_id>_试卷.pdf` + `<exam_id>_答案与评分.pdf`，听写音频同放此处）
  - `reports/`：错题本 PDF 与学习进度报告 PDF
  - `practice_log.json`、`mistakes.json`：学情与错题持久化记录
- 所有几何/钟表/统计图必须通过 `figure` 字段或 `{{fig_...}}` 指令由代码生成，禁止手写不准确的描述替代配图。
- 仅使用真实存在于 `scripts/` 和 `data/` 的脚本与数据；不要虚构命令。口算卡、听写单、每日练习卡、找朋友有代码生成脚本；其余专项由模型按 JSON → 校验核验 → 渲染链路出题。
- 运行环境：脚本兼容 `Python >= 3.9`；渲染 PDF 需安装 Python `markdown` 包及本地 Chrome / Chromium / Edge（无 Chrome 时可用 `--md-only`）。
- 详细 JSON schema、指令语法与脚本参数见同目录 [REFERENCE.md](REFERENCE.md)。

## 自检（改完脚本或数据后跑）
```bash
python3 -I "$SKILL_DIR/scripts/validate_knowledge.py"
python3 -I "$SKILL_DIR/scripts/validate_templates.py"
python3 -I "$SKILL_DIR/scripts/normalize_english_wordlist.py" --check
python3 "$SKILL_DIR/scripts/run_golden.py"
python3 "$SKILL_DIR/scripts/check_portability.py"
```
