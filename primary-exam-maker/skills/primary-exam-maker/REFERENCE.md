# primary-exam-maker 参考规范

> 路径约定：`$SKILL_DIR` 指本 SKILL.md 所在目录的**绝对路径**（见 SKILL.md「路径约定」一节）。
> 命令里请写成 `"$SKILL_DIR/scripts/xxx.py"` 并加引号，避免路径含空格时出错。

## 1. 孩子档案管理（`scripts/profile.py`）

个人数据存放在本机 `~/.primary-exam/`（绝不写入插件仓库；测试时可用 `PRIMARY_EXAM_HOME` 环境变量隔离）。

- `python3 "$SKILL_DIR/scripts/profile.py" list`：列出已建档孩子及按今天日期推算的年级/册次（`g2_up`、`g3_up` 等）。
- `python3 "$SKILL_DIR/scripts/profile.py" add --id child1 --nickname 老大 --enrollment-year 2024 --aliases 大宝`：新建档案。
- `python3 "$SKILL_DIR/scripts/profile.py" get 老大`：按 id、昵称或别名查询，返回 `current.grade`、`current.term`、`current.code` 与各科进度。
- `python3 "$SKILL_DIR/scripts/profile.py" update 老大 --subject math --current-unit 3 --difficulty standard`：更新学科进度或难度档位（`basic` / `standard` / `advanced`）。
- `python3 "$SKILL_DIR/scripts/profile.py" check-freshness`：检查 `data/curriculum/` 校对日期是否超过 180 天；超时必须提醒家长。

推算规则：每年 `09-01`（含）至次年 `02-14` 为上册（`up`），`02-15` 至 `08-31` 为下册（`down`）；`grade = school_year - enrollment_year + 1`。

## 2. 教材、模板与知识点数据

| 目录 | 内容 | 校验脚本 |
|---|---|---|
| `data/curriculum/{math,chinese,english}/` | 10 册单元目录 + 语文四册识字/写字/词语表 + 英语三上下 Word lists | — |
| `data/templates/exam_templates.json` | 语数英 × 单元/期中/期末 100 分结构与 `difficulty_levels` 比例 | `python3 -I "$SKILL_DIR/scripts/validate_templates.py"` |
| `data/knowledge/<subject>/<subject>_g<grade>_<up\|down>.json` | 分册知识点目录，**十册已全部建成**（语文 220 / 英语 84 / 数学 159，共 463 个知识点） | `python3 -I "$SKILL_DIR/scripts/validate_knowledge.py"` |
| `data/curriculum/english/*_wordlist.json` | 英语三上下 Word lists；每条含 `en`（教材原样）与 `en_primary`（去括号变体后的主词形，听写答案用它） | `python3 -I "$SKILL_DIR/scripts/normalize_english_wordlist.py" --check` |

分科约束：
- **数学**：苏教版，不超前使用未学单元知识点；能力层级使用 `了解 / 理解 / 掌握 / 运用`。
- **语文**：统编版，严格区分识字表（认读）与写字表（会写）；拼音与词语表核对。
- **英语**：译林版（三年级起），区分核心词（`core: true`）与非核心词（`core: false`）。

## 3. 试卷中间格式 JSON 规范（`scripts/validate_exam.py`）

出题必须先落 JSON，通过 `python3 -I "$SKILL_DIR/scripts/validate_exam.py" exam.json` 后才能渲染。

顶层字段：
```json
{
  "schema": 1,
  "exam_id": "20261108-child2-math-u1",
  "created_at": "2026-11-08",
  "child": {"id": "child2", "nickname": "老二", "grade": 2, "term": "上"},
  "subject": "math | chinese | english",
  "kind": "unit | midterm | final | oral_math | dictation | daily_practice | topic | type | mistake | diagnostic",
  "title": "二年级数学上册 · 第 1 单元测试卷",
  "scope": {"grade": 2, "term": "up", "units": [1], "textbook_edition": "苏教版"},
  "difficulty_level": "basic | standard | advanced",
  "total_points": 100,
  "suggested_minutes": 40,
  "sections": [ ... ]
}
```

大题（`sections[]`）字段：`id`、`name`、`points`、`items[]`，可选 `instructions`、`passage`（阅读短文）、`columns`（`2` 或 `3`，用于口算等分栏排版）。

小题（`items[]`）字段：
- 必填：`id`、`stem`、`type`、`points`、`unit`、`ability`（`了解|理解|掌握|运用`）、`tier`（`基础|中档|拔高`）、`answer`、`scoring_rules`（可执行细则：步骤分/单位/答句/错别字）、`hint`（不直接给答案的家长引导话术）。
- 可选：`no`、`options`（选择题选项列表）、`knowledge_points`（知识点 ID 列表，暂无目录可写 `["待归类"]`）、`figure`、`layout`、`requires_figure`、`rubric`（作文/看图写话量规 `[{criterion, points, detail}]`）、`source_mistake`（F1 错题映射 `{original, error_type, variant_kind}`）。

硬性规则：
- 整卷（`unit` / `midterm` / `final`）`total_points` 与各大题分值之和必须为 `100`，**不设卷面分**；`basic` 卷不允许 `拔高` 题。
- 视觉类题型（`看图列式`、`看图写话`、`听音选图`、`看图选词`、`看钟面`、`量长度`、`数一数`、`操作与作图` 等）或 `requires_figure: true` 必须提供有效 `figure` 或内联 `{{fig_...}}`，缺图或参数非法拒绝出卷。
- 当 `scope.units` 存在且非诊断卷时，所有题目 `unit` 与已建档知识点所属单元不得超过 `max(scope.units)`（禁止超纲）。

## 3A. 口算卡与听写单生成

两个脚本都输出上面同一种试卷 JSON（`kind` 分别为 `oral_math` / `dictation`），因此同样必须经过 `validate_exam.py` 校验和 `render_exam.py` 渲染，不能手写题目。

### 口算卡（`scripts/generate_oral_math.py`，F6）
```bash
python3 "$SKILL_DIR/scripts/generate_oral_math.py" --grade 2 --term up --count 50 -o oral.json
python3 "$SKILL_DIR/scripts/generate_oral_math.py" --grade 3 --term down --topics mul_2digit,fraction --count 30 -o oral.json
python3 "$SKILL_DIR/scripts/generate_oral_math.py" --grade 2 --term up --units 1,2 --count 20 -o oral.json
```
- 主题：`mul`（表内乘法）、`div`（表内除法）、`rem`（有余数除法）、`add100`、`add1000`、`mul_1digit`、`div_1digit`、`mul_2digit`、`fraction`、`mix`；各册可用主题由脚本内置的 `TOPIC_UNITS` 决定，`--units` 会过滤主题。
- 答案全部由代码计算；同卷题干去重；`--seed` 可复现。默认 3 栏、每题 1 分，`total_points = 题数`。
- 输出后照常：`validate_exam.py` → `render_exam.py --pdf`。

### 听写单（`scripts/generate_dictation.py`，F7）
```bash
python3 "$SKILL_DIR/scripts/generate_dictation.py" --subject chinese --grade 2 --term up --units 1,2 --count 20 -o dict.json
python3 "$SKILL_DIR/scripts/generate_dictation.py" --subject chinese --grade 2 --term up --mode writing --count 15 -o dict.json
python3 "$SKILL_DIR/scripts/generate_dictation.py" --subject english --grade 3 --term up --units 1-2 --count 10 --audio /tmp/dict.aiff -o dict.json
```
- 语文从 `*_tables.json` 的 `words`（词语表，默认）/`writing`（写字表）/`literacy`（识字表）取词，按课次映射到单元；`--mode mixed` 混合三表。
- 英语从 `*_wordlist.json` 取词，默认只取 `core: true`；`--include-noncore` 可含非核心词。
- 语文题干用田字格（按词长），英语用四线三格；孩子卷 2 栏排版，答案卷含家长读词顺序。
- `--created-at` 可指定 `created_at` 日期（默认今天），与 `generate_oral_math.py` 一致。
- `--audio` 用 macOS `say` 生成每词两遍的音频（语文用 Ting-Ting 语音，英语用 Samantha 语音）；路径写 `.m4a` 时会自动用 `afconvert` 转码（本机无 mp3 编码器，m4a 可直接播放）。
- 听写单的 `validate_exam.py` 去重按**答案**而不是题干（题干都是相同的作答格）。

## 3B. 学科内容核验（`scripts/verify_exam.py`）

`validate_exam.py` 管结构（分值、超纲、缺图、去重），`verify_exam.py` 管学科内容，两者都要在渲染前跑：

```bash
python3 -I "$SKILL_DIR/scripts/verify_exam.py" exam.json [--strict]
```

- **数学**：对纯算式题（口算、脱式、有余数除法、同分母分数加减）复算答案，不一致直接 FAIL；应用题/竖式/图形题跳过并计数，需出题时人工保证。
- **英语**：选择题答案必须在选项中（否则 FAIL）；答案与选项里的单词不在本册 Word list 时给 warning（专有名词/常见虚词白名单内不报）。
- **语文**：`看拼音写词语` 的答案须在本册词语表；答案用字不在识字/写字表时给 warning。
- 默认 warning 不阻断渲染；`--strict` 时 warning 也视为失败。

## 3C. 组卷规划（`scripts/plan_exam.py`）

单元/期中/期末卷出题前，先读取模板与范围数据，避免凭记忆编结构：

```bash
python3 -I "$SKILL_DIR/scripts/plan_exam.py" --subject math --grade 2 --term up --kind unit --units 1,2
python3 -I "$SKILL_DIR/scripts/plan_exam.py" --subject chinese --grade 3 --term down --kind final --json
```

输出：建议时长、难度比例、各大题题量/分值/默认档位、范围内知识点（含单元与能力层级）、语文/英语的字词范围统计，以及组卷提醒。`--json` 供脚本消费，默认输出 Markdown 供阅读。英语模板按 `g3_up`/`g3_down` 分册，数学/语文按 `g2`/`g3` 不分册，脚本会自动匹配。

## 3D. 知识点专项规划（`scripts/plan_kp_drill.py`）

F8 知识点专项按 `理解 15% / 基础练 40% / 变式 30% / 综合 15%` 分配题数，脚本会读出知识点详情、错因与可结合的相关知识点：

```bash
python3 -I "$SKILL_DIR/scripts/plan_kp_drill.py" --subject math --grade 2 --term up --kp M2U-1-05 --count 20
python3 -I "$SKILL_DIR/scripts/plan_kp_drill.py" --subject english --grade 3 --term up --kp E3U-1-01,E3U-1-03 --count 10 --json
```

- `--kp` 指定一个或多个知识点 ID；`--unit` 取整单元知识点（与 `--kp` 二选一）。
- 输出梯度题量、每个知识点的掌握标准/错因/适用题型、前置与同单元相关知识点。
- 出题时：理解层用判断/填空考概念与算理；基础练用核心题型；变式覆盖 `error_types`；综合与相关知识点结合，含 1 道中档/拔高题。

## 3E. 错题定向专项（F1）与起始诊断卷流程

### 错题定向（P1：文字列题 + 图片识别，不入库）
1. **识别**：图片/PDF/doc/MD 由 Claude 读图或读文件提取；红叉/红笔订正用来判断错题与孩子答案；辨认不清写“待确认”，不猜。
2. **家长确认（必须）**：先输出表格让家长核对——`题干 / 孩子错答 / 正确答案 / 错因 / 知识点 ID`；确认前不出题。照片中的姓名、班级、学校不写入任何产物。
3. **核对答案**：数学算式用 `verify_exam.py` 的复算逻辑核对；语文/英语对照本册字表/词表；与家长给的答案不一致时提示，不擅自判定。
4. **出题与去重**：先问总题数（默认 12–20，**不要硬凑 100 分大卷**）。原错题较少时每题生成同构变式 1–2 题、迁移变式 0–1 题；原错题较多（≥6 题）时每题 1 道核心变式即可，避免凑数。
   - 同构变式至少更换情境主角、数值或提问方向，不要只换一个动物名/数字；
   - **跨大题隔离**：同一原错题不要同时塞进填空/选择和解决问题；口算题不要与看图列式/填空题出现相同算式，也不要让同一个得数在口算中高频扎堆；
   - 每道题的 `hint` 须贴合该题实际做法，不要整组复制不匹配的通用模板。
5. **JSON**：变式题在原题对应处写 `source_mistake`：`{"original": "原题简述", "error_type": "进位错", "variant_kind": "同构"}`；渲染后答案卷会生成“原错题 → 错因 → 本卷题号”对照表（同一原错题自动合并题号）。
6. **入库**：P1 只在当次出卷使用，不写入 `~/.primary-exam/` 错题库；P3 再做错题库与间隔复习。

### 起始诊断卷（P1）
- `kind` 用 `diagnostic`，`scope.units` 可省略；`validate_exam.py` 对诊断卷不检查 100 分与单元超纲。
- 从 `data/knowledge/` 选覆盖前几册重点的知识点，每个知识点 1–2 题，答案卷按知识点汇总，供家长录入对错后形成掌握度清单。
- 诊断结果用于后续专项选题；不把掌握度写成对孩子的人格评价。

### 题型专项（F2，模型出题）

题型专项（如"看拼音写词语专项""解决问题专项"）没有独立的生成脚本，这是**有意设计**：题型专项的题目结构和知识点选择需要根据孩子学情判断，由模型按 JSON → `validate_exam.py` → `verify_exam.py` → `render_exam.py` 链路出题即可，不需要脚本自动化。

出题流程：
1. 与家长确认题型方向（如"看拼音写词语""解决问题""阅读理解"）和题数。
2. 从 `data/knowledge/` 和 `data/curriculum/` 取范围内的知识点与字词。
3. 按正常 JSON 规范落题，`kind` 用 `topic`。
4. 照常跑校验与渲染。

### 英语听力音频（当前限制）

`generate_dictation.py --audio` 可为英语**听写单**生成每词两遍的音频（Samantha 语音）。但英语试卷中的**完整听力题型**（听音选图、听音判断、听句选答语、听对话填关键词、听短文排序）暂无自动生成音频的脚本。

当前做法：听力题在 JSON 中正常出题（`type` 为听音选图等），家长口读或自行录音。如需自动生成听力音频，可参考 `generate_dictation.py` 的 `write_audio()` 实现，按题目内容生成句子级或短文级音频。

## 3F. 游戏化识字题型（`scripts/generate_gamified_chinese.py`）

四种适合低年级的游戏化识字题型，降低刷题疲劳、提升识字热情。题干通过 `{{指令}}` 渲染为 HTML，直接可打印。

```bash
# 连线（词语↔词语/拼音，4 对连线 = 1 道题 × N 分）
python3 "$SKILL_DIR/scripts/generate_gamified_chinese.py" --grade 2 --term up --units 1,2 --type lianxian --count 4 -o game.json

# 找朋友（单字 + 候选字，圈出能组词的字）
python3 "$SKILL_DIR/scripts/generate_gamified_chinese.py" --grade 2 --term up --units 1,2 --type zhaopengyou --count 4 -o game.json

# 猜字谜（谜面 + 大方格填字）
python3 "$SKILL_DIR/scripts/generate_gamified_chinese.py" --grade 2 --term up --type caizimi --count 3 -o game.json

# 看图选字（文字描述图意 + 候选字）
python3 "$SKILL_DIR/scripts/generate_gamified_chinese.py" --grade 2 --term up --units 1,2 --type tupian_xuanzi --count 3 -o game.json

# 混合四种题型
python3 "$SKILL_DIR/scripts/generate_gamified_chinese.py" --grade 2 --term up --units 1,2 --type mixed --count 8 -o game.json
```

- **连线（lianxian）**：整道题为一组多对连线，`count` 决定连线对数；词语对由词语表自动抽取，右列自动打乱顺序。生产时，模型可将右列替换为对应的拼音/释义/近义词以获得更准确的配对。
- **找朋友（zhaopengyou）**：每题给一个汉字 + 候选字列表，孩子圈出能与该字组词的候选字；候选字含干扰字；答案字为自动推荐，**使用前需模型根据字义核实**。
- **猜字谜（caizimi）**：内置常见字谜，可由模型按教材生字替换谜面。
- **看图选字（tupian_xuanzi）**：内置场景描述文字（取代实际图片），候选字含干扰字；**描述与答案字在生产时需由模型按教材内容填写**。
- 输出 `kind = "topic"`，走标准 `validate_exam.py → render_exam.py --pdf` 链路。

### 四种游戏指令用法（也可在手写 JSON 中使用）

```
{{lianxian left="妈妈,爸爸,哥哥" right="māma,bàba,gēge"}}
{{zhaopengyou char="青" candidates="清,请,蜻,山,水,风"}}
{{caizimi riddle="左边绿，右边红，左右相遇起凉风。" hint="（提示：与树木有关）"}}
{{tupian_xuanzi desc="图中画着一只小（  ）在荷叶上跳来跳去。" candidates="蛙,娃,洼"}}
```

- `lianxian`：`left`/`right` 逗号分隔，数量必须相同，最多 10 对；`shuffle=no` 可关闭右列打乱。
- `zhaopengyou`：答案写入 JSON 的 `answer` 字段，**不要写进孩子卷的 `stem`**（`render_exam.py` 渲染孩子卷时也会自动剥离误带的 `answers`）；`candidates` 最多 12 个。
- `caizimi`：`hint` 可选（灰色小字提示）；下方大方格供孩子填写答案。
- `tupian_xuanzi`：答案写入 JSON 的 `answer` 字段，**不要写进孩子卷的 `stem`**（渲染孩子卷时会自动剥离误带的 `answer`）；`candidates` 最多 6 个。

## 3G. 每日练习卡（`scripts/generate_daily_practice.py`）

小型混合练习卡（默认 10 题，5-15 分钟），按「当日新学 60% + 螺旋复习 40%」自动分配题量。适合每日固定练习、培养学习习惯。

```bash
python3 "$SKILL_DIR/scripts/generate_daily_practice.py" --subject math --grade 2 --term up --current-unit 3 --count 10 -o daily.json
python3 "$SKILL_DIR/scripts/generate_daily_practice.py" --subject chinese --grade 2 --term up --current-unit 3 --count 8 -o daily.json
python3 "$SKILL_DIR/scripts/generate_daily_practice.py" --subject english --grade 3 --term up --current-unit 2 --count 8 -o daily.json
```

- **数学**：复用 `generate_oral_math.py` 的题库，按 `--current-unit` 划分新学主题（当前单元涉及的主题）与复习主题（之前单元已学的主题）。
- **语文**：复用 `generate_dictation.py` 的词语库，`--mode` 默认 `words`（词语表），按单元划分新学词与复习词。
- **英语**：复用 `generate_dictation.py` 的英语词库，按单元划分新学词与复习词。
- 螺旋复习比例固定 40%；若当前单元没有可出口算的主题，全部做复习。
- 输出 `kind` 为 `daily_practice`，同样走 `validate_exam.py → render_exam.py --pdf` 链路。
- 语文/英语每日练习卡的 section id 为 `dictation`，渲染时自动使用田字格/四线三格排版。

## 3H. 练习记录与进度报告

### 练习记录（`scripts/practice_log.py`）

记录每次练习成绩，存入 `~/.primary-exam/children/<id>/practice_log.json`，用于间隔复习推荐与进度可视化。

```bash
# 详细记录（关联试卷 JSON，自动提取单元/题型/逐题对错）
python3 "$SKILL_DIR/scripts/practice_log.py" record --child 老大 --exam-json daily.json --scores "1,0,1,1,1,1,1,0,1,1"

# 简单记录（只记总分）
python3 "$SKILL_DIR/scripts/practice_log.py" record --child 老大 --subject math --total 10 --score 8

# 查看统计（总次数/平均正确率/连续打卡/分科目/分单元）
python3 "$SKILL_DIR/scripts/practice_log.py" stats --child 老大

# 查看薄弱单元（正确率低于阈值的单元）
python3 "$SKILL_DIR/scripts/practice_log.py" weak-points --child 老大 --threshold 70

# 查看历史记录
python3 "$SKILL_DIR/scripts/practice_log.py" history --child 老大 --last 7
```

- **详细模式**（`--exam-json`）：从试卷 JSON 提取每题的单元/分值，配合 `--scores` 逐题得分（0/1），自动按单元聚合正确率，支持后续薄弱单元分析与间隔复习。
- **简单模式**（`--subject --total --score`）：只记录总分，不记录逐题详情，适合快速记录。
- 连续打卡天数从最近一次记录开始倒推连续日期计算。

### 进度报告（`scripts/generate_progress_report.py`）

从练习记录生成含 `fig_bars` 图表的 Markdown 报告，支持渲染为 PDF。

```bash
python3 "$SKILL_DIR/scripts/generate_progress_report.py" --child 老大 -o report.md
python3 "$SKILL_DIR/scripts/generate_progress_report.py" --child 老大 --last 14 --subject math -o report.md
# 渲染为 PDF
python3 "$SKILL_DIR/scripts/render_pdf.py" report.md -o report.pdf
```

报告包含：
- **概况**：累计练习次数/题数、平均正确率、连续打卡天数、练习天数、练习科目。
- **最近练习正确率**：条形图展示最近 10 次练习的正确率趋势。
- **各单元掌握情况**：条形图展示各单元平均正确率（需详细模式记录）。
- **各学科表现**：条形图对比各学科平均正确率（多科目时显示）。
- **详细记录表**：最近 20 次练习的日期/科目/类型/得分/正确率。
- 报告末尾附鼓励语，按连续打卡天数分级。

## 3I. 故事化应用题（`scripts/story_themes.py`）

为数学应用题的情境参数提供趣味替换词库，降低「每行种 X 棵树」之类的枯燥感。

```bash
python3 "$SKILL_DIR/scripts/story_themes.py" list                      # 列出可用主题（恐龙/太空/海洋/农场/糖果/运动会）
python3 "$SKILL_DIR/scripts/story_themes.py" get 恐龙                  # 获取恐龙主题完整词汇表
python3 "$SKILL_DIR/scripts/story_themes.py" sample 恐龙 --seed 42     # 随机采样一组情境参数
python3 "$SKILL_DIR/scripts/story_themes.py" sample 太空 --template 除法_平分   # 附带情境模板示例
```

**使用流程（模型出题时）**：
1. 家长指定主题（或让孩子选），如「恐龙」。
2. 运行 `story_themes.py sample 恐龙 --seed 42` 获取情境参数（`character`/`place`/`object`/`unit`/`action`/`container`）和 `sample_stem`。
3. 模型把经典题型（乘法行列、加减合并、除法平分等）的通用词替换为主题词，填入 `{n1}` / `{n2}` 具体数值后写入 `stem` 字段。
4. 照常走 `validate_exam.py → render_exam.py --pdf` 链路。

**内置模板类型**（`--template`）：`乘法_行列`、`加减_合并`、`除法_平分`。

可用主题：`恐龙`、`太空`、`海洋`、`农场`、`糖果`、`运动会`。

## 3J. 听写音频语音鼓励（`generate_dictation.py --audio-score --audio-total`）

在生成听写单音频时，根据孩子上次的得分在所有词语读完后附加一段语音鼓励，让音频本身有激励效果。

```bash
# 普通听写音频（无得分，结尾读"听写完成，请对照答案自己检查"）
python3 "$SKILL_DIR/scripts/generate_dictation.py" --subject chinese --grade 2 --term up --count 10 --audio dict.m4a -o dict.json

# 带鼓励（上次得了 8/10）
python3 "$SKILL_DIR/scripts/generate_dictation.py" --subject chinese --grade 2 --term up --count 10 \
  --audio dict.m4a --audio-score 8 --audio-total 10 -o dict.json
```

- 得分率 ≥ 90%：「太棒了！你全都写对了，继续保持！」
- 得分率 ≥ 70%：「不错！这次对了 N 个，再加把劲，你一定能全对！」
- 得分率 < 70%：「这次对了 N 个，不要灰心，多练几遍就会越来越好！」
- 不传 `--audio-score/--audio-total` 时，结尾统一读「听写完成，请对照答案自己检查一下！」

## 4. 版式指令与渲染（`scripts/directives.py`、`scripts/render_exam.py`、`scripts/render_pdf.py`）

支持的 `{{指令}}`（也可通过 JSON 的 `figure` / `layout` 字段自动生成）：
- `{{blank n=4}}`：内联填空下划线。
- `{{workspace h=28 label="解："}}`：解答留白框（`h` 为毫米高度）。
- `{{tianzige n=8 chars="春风"}}`：一排 `n` 个田字格；`chars` 可选，印浅色范字供描红。
- `{{pinyin_tianzige py="chūn tiān"}}` 或 `{{pinyin_tianzige chars="春天"}}`：上拼音下田字格；给 `py` 时印拼音留空田字格（看拼音写词语），给 `chars` 时印汉字与四线三格（看字写拼音）。
- `{{fourline rows=3}}`：英语四线三格抄写行。
- `{{fig_rect w=8 h=5 unit="厘米"}}`：长方形几何图（`w`/`h` 可传 `?` 表示隐藏标注）。
- `{{fig_clock h=3 m=25}}`：精确指针时钟。
- `{{fig_bars data="苹果:5,香蕉:8,梨:3" title="喜欢的水果" step=2}}`：黑白条形统计图。`ymax` 缺省取数据最大值向上取到 step 的倍数；若 `ymax` 小于数据最大值会报错。
- `{{lianxian left="妈妈,爸爸" right="māma,bàba"}}`：连线题布局（词语↔拼音/释义），左右列逗号分隔；`shuffle=no` 可关闭右列打乱。
- `{{zhaopengyou char="青" candidates="清,请,蜻,山,水" answers="清,请,蜻"}}`：找朋友题（单字 + 候选字方块），`answers` 只在答案版加粗边框。
- `{{caizimi riddle="左边绿，右边红，左右相遇起凉风。" hint="（提示）"}}`：猜字谜（谜面 + 大方格），`hint` 可选。
- `{{tupian_xuanzi desc="图中画着一只小（  ）在荷叶上跳来跳去。" candidates="蛙,娃,洼" answer="蛙"}}`：看图选字（场景描述 + 候选字方块），`answer` 只在答案版加粗边框。

渲染命令：
```bash
python3 "$SKILL_DIR/scripts/render_exam.py" exam.json -o <输出目录> --pdf
```
产出分离的两套文件：
1. `<exam_id>_试卷.md` / `.pdf`（孩子用：不含任何答案、评分细则、提示或知识点编号；`拔高` 题带 `★ 拔高` 标记）
2. `<exam_id>_答案与评分.md` / `.pdf`（家长用：分值与能力分布、错题对照表、答案与细则、讲评话术、A4 家长阅卷表与错因勾选框）

家长手工修改 `.md` 后，可单独重打 PDF：
```bash
python3 "$SKILL_DIR/scripts/render_pdf.py" 试卷.md
```
