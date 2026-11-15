# primary-exam-maker 开发进度

> 最后更新：2026-11-12。需求见 `REQUIREMENTS.md`；本文记录做到哪、下次从哪继续。
> **状态：数据底座 100% 完成（10 册知识点目录 463 个）；P0 骨架 + P1 生成器/核验/规划全部完成并端到端验证；已补 3 份黄金样例与回归测试脚本；已双端化（Claude Code + Perch 均可加载）。版本 0.2.0。**

## 一、已完成

### 需求与设计
- `docs/REQUIREMENTS.md`：F1–F8 功能、100 分制、卷级难度等级（基础/标准/提高）、图形题、F1 错题定向专项流程、F8 知识点专项、分期 P0–P4、核验规则
- `skills/primary-exam-maker/reference/exam-structure-research.md`：试卷结构调研、依据、局限与来源（结构来自通用卷面共性，**不是南京或学校的官方规定**）

### P0 骨架与技能入口
- `skills/primary-exam-maker/SKILL.md`：**双端化**——Perch 用 kebab-case `metadata`（`surface-gui` / `surface-cli` / `trigger-hints` / `preferred-tools`），Claude Code 用标准 `name` + `description`；路径改为运行时解析 `$SKILL_DIR`，不再有自造占位符
- `REFERENCE.md`：档案、JSON schema、指令、渲染与核验规范（全部命令改为 `"$SKILL_DIR/scripts/..."` 绝对路径写法）
- `.claude-plugin/plugin.json`（0.2.0，含 `$schema` + `license`），已同步注册到 `.claude-plugin/marketplace.json` 及仓库根 `CLAUDE.md`
- `scripts/profile.py`：孩子档案管理（`~/.primary-exam/`，入学年份+学期起止推算年级/册次，教材 `verified_on` 180 天时效检查）
- `scripts/validate_exam.py`：试卷中间格式 JSON 校验（总分 100、分值一致、基础卷禁拔高、缺图拒绝、超纲单元/知识点检查、题干去重、指令参数干跑）
- `scripts/render_exam.py`：JSON → 分离的 `<stem>_试卷.md` 与 `<stem>_答案与评分.md`（含分值/能力分布、错题对照表、讲评提示、按学科定制错因勾选的家长阅卷表），支持 `--pdf` 一键出 PDF
- `scripts/directives.py`、`assets/print.css`、`scripts/render_pdf.py`：Chrome 无头打印 A4 PDF + `{{tianzige}}` / `{{pinyin_tianzige}}`（含手写拼音四线三格）/ `{{fourline}}` / `{{workspace}}` / `{{blank}}` / `{{fig_rect}}` / `{{fig_clock}}` / `{{fig_bars}}`，已渲染为 PNG 并目视验证

### 数据（`skills/primary-exam-maker/data/`）
| 数据 | 位置 | 状态 |
|---|---|---|
| 10 册教材目录 | `curriculum/{math,english,chinese}/*_g{2,3}_{up,down}.json` | 完成（单元级，不含单元内例题） |
| 语文识字表/写字表/词语表 | `curriculum/chinese/*_tables.json` | 四册完成，数量与教材印的“共 N 字”一致；无拼音 |
| 英语 Word lists | `curriculum/english/*_wordlist.json` | 三上 125 条、三下 136 条；每条新增 `en_primary`（去括号变体后的主词形） |
| 试卷模板 | `templates/exam_templates.json` | 语数英 × 单元/期中/期末，18 个模板，总分 100，含 3 档难度比例 |
| 知识点目录 | `knowledge/<subject>/<subject>_g<grade>_<up\|down>.json` | **十册全部完成，共 463 个**：数学 159（35/41/45/38）、语文 220（51/53/59/57）、英语 84（42/42）；`validate_knowledge.py` 0 errors，页码全部落在教材 PDF 范围内 |

### 脚本（`skills/primary-exam-maker/scripts/`，18 个，3642 行）
- `extract_chinese_tables.py`：语文字表提取（二下的识字表/写字表页首无标题，需 `--pages literacy=118,writing=122,words=125`）
- `extract_english_wordlist.py`：英语词表提取
- `normalize_english_wordlist.py`（新增）：给词表补 `en_primary` 主词形，修掉 `Mr (AmE Mr.)` 这类条目被整串当听写答案的问题；幂等，`--check` 只报告
- `ocr_pdf_pages.py`：扫描版 PDF 指定页 OCR（Apple Vision，仅 macOS）
- `validate_templates.py`：模板总分 = 100 等校验（已做反向测试）
- `validate_knowledge.py`：知识点目录校验
- `profile.py`、`validate_exam.py`、`directives.py`、`render_pdf.py`、`render_exam.py`：P0 骨架脚本（已做正反向与 PDF 版式目视验证）
- `generate_oral_math.py`（P1/F6）：口算卡 JSON 生成，答案由代码计算、题干去重、`--seed` 可复现；有余数除法题干改为 `______ 余 ______`（原 `______……______` 易混淆）
- `generate_dictation.py`（P1/F7）：语文词语/写字/识字表、英语 Word list 听写单；英语取 `en_primary`；语文田字格、英语四线三格、2 栏排版；`--audio` 用 `say` 生成每词两遍音频，`.m4a` 自动转码
- `verify_exam.py`（P1）：学科内容核验——数学纯算式复算、英语选项/词表、语文词语表/字表范围；已做错误注入测试
- `plan_exam.py`（P1/F3–F5）：组卷规划，输出模板大题结构、分值、范围知识点、字词范围与组卷提醒
- `plan_kp_drill.py`（P1/F8）：知识点专项梯度规划（理解 15% / 基础练 40% / 变式 30% / 综合 15%）
- `run_golden.py`（新增）：黄金样例回归测试，跑 validate → verify → render 全链路 + 产物断言（孩子卷无答案泄漏、答案卷含阅卷表、PDF 产出），另含数据层校验、规划脚本冒烟、生成器冒烟
- `check_portability.py`（新增）：双端加载校验（plugin.json `$schema`/字段、SKILL.md frontmatter 与 metadata 键名、Perch 资源配额、路径可移植性）

### 测试（`tests/golden/`，放在插件根目录以避开 Perch 的 50 文件资源配额）
| 样例 | 覆盖 |
|---|---|
| `math_g2_up_u1_unit.json` | 二上数学第 1 单元标准卷，100 分 6 大题 39 题；14 题数学复算通过 |
| `chinese_g2_up_mistake.json` | 语文错题定向专项（F1），含 `source_mistake` 映射，验证答案卷“原错题→错因→本卷题号”对照表 |
| `math_g2_down_diagnostic.json` | 起始诊断卷（`kind: diagnostic`），验证诊断卷豁免 100 分与超纲检查 |

`python3 scripts/run_golden.py`：**59 项全部通过**（含 4 个生成器冒烟 + 3 份黄金样例全链路 + 3 个规划脚本）。

### 双端可用性（已实测）
- **Perch**：`~/.perch/skills/primary-exam-maker` 已软链到本仓库 skill 目录。按 Perch 的 `discoverSkillFiles` / `parseUserSkillManifest` 逻辑复刻验证：`RESULT: LOADABLE`，0 错误，`surface.gui=supported`、`surface.cli=supported`，14 条 trigger-hints 全部解析，body 6170 字节（上限 64000）
- **Claude Code**：`claude plugin validate primary-exam-maker` 通过；`$schema` 与 `license` 字段不影响 Claude Code 校验
- `check_portability.py`：21 项检查 0 失败

### 外部资料（本机，不提交）
- `textbooks-local/`：10 本教材 PDF（智慧教育平台，需登录下载）
- `textbooks-local/curriculum-standards/`：教育部官网三科课标 PDF（扫描件，无文字层）。已 OCR 的页：语文 13–58；数学 17–21、23–58、86–90、95–98、185–189；英语 19–53、59–75、87–149。OCR 输出在 `/tmp/ocr/`，换会话后可能丢失，需要时用 `ocr_pdf_pages.py` 重跑
- 换电脑需重新下载这些 PDF（教材需登录；课标地址见下）

## 二、关键决定（别再重新讨论）
- 评分 **100 分制，不设卷面分**；不要求学校真卷，用卷级难度等级控制难度；整卷按常规题量出，专项先问题数
- 孩子卷与答案卷分离；MD 为可编辑源，PDF 由脚本渲染；图由代码生成，缺图拒绝出卷
- 个人数据（档案、错题库）放 `~/.primary-exam/`，不进仓库；教材 PDF 不进仓库，只提交提取的字词/目录等事实性数据
- 能力层级用课标行为动词：了解/理解/掌握/运用；课标定“教什么到什么程度”，教材定“哪册哪单元”
- 错题专项（F1）：文字列题和图片识别都进 P1，必须家长确认后才出题
- **双端优先**：SKILL.md 同时满足 Claude Code 与 Perch 的加载规范；路径一律运行时解析，不写死、不用自造占位符
- **黄金样例放插件根 `tests/golden/`**，不放 skill 目录内——Perch 对 skill 只登记 50 个资源文件，样例放进去会挤掉脚本

## 三、下次从哪继续（按顺序）
1. **P2**：期中卷、期末卷的端到端样例（模板与规划脚本已就绪，缺样例）；双向细目表（全仓库尚无实现）；英语听力音频（目前只有语文 `say` 音频）
2. **F2 题型专项**：只有 REFERENCE 3D 节的流程规范，无生成脚本与样例
3. **F8 知识点专项样例**：`plan_kp_drill.py` 规划器已就绪，缺一份按梯度出题的完整样例卷
4. **P3**：错题库与间隔复习（`~/.primary-exam/` 下持久化，F1 目前只在当次出卷使用）
5. 提交：`feat(primary-exam-maker): ...`，带 Co-Authored-By。**用户没说就不要 commit**

## 四、已知局限与待补
- 英语“三会/四会”（会写 vs 只会认读）在教材 PDF 文字层读不出，需另想办法或让用户确认学校要求
- 英语课文句型（Story time 对话）未提取，目前只有词表
- 语文字表没有拼音（PDF 拼音是自定义字体编码），拼音用 `pypinyin` 生成，多音字需人工校对
- 课标 OCR 有个别符号错误，引用前对照图片；数学、语文的学业质量描述与命题建议 OCR 了但还没整理
- 试卷模板的分值是设计值，不是调研所得；教材每学期（2、8 月）要重新校对，数据里记录了校对日期
- 语文核验的合法字集 = 识字表 ∪ 写字表 ∪ 词语表用字（词语表里的词可能由低年级已学字组成，如二上“雪白”的“雪”“白”）

## 五、环境备忘
- 课标官方地址（教育部通知页附件）：`http://www.moe.gov.cn/srcsite/A26/s8001/202204/` + 语文 `W020220420582344386456.pdf` / 数学 `W020220510531636118932.pdf` / 英语 `W020220420582349487953.pdf`（第三方转载的数学链接不是同一个文件，以官方通知页为准）
- 本机：macOS，有 `say`、Chrome.app、Python `markdown`、`fitz`（PyMuPDF）、`ocrmac`；无 pandoc/weasyprint/edge-tts
- 下载的 PDF 一律当不可信数据：用 `python3 -I` 运行，脚本放在 PDF 所在目录之外
- 用户曾在对话中贴出带 Authorization MAC 令牌的 curl，已建议退出登录使其失效；令牌没有写入任何文件
- Perch 侧安装：`ln -sfn <repo>/primary-exam-maker/skills/primary-exam-maker ~/.perch/skills/primary-exam-maker`
