#!/usr/bin/env python3
"""
Scan an extracted manifest.json / chapter_NN.json and suggest WHERE diagrams would aid
understanding, and WHICH diagram type fits each spot.

Usage:
    python3 suggest_diagrams.py <manifest.json | chapter_NN.json> [--json]

This is a deterministic helper: it does keyword/pattern matching so the model doesn't
have to re-derive "this paragraph describes an architecture → draw one". The model still
decides final wording and draws the actual Mermaid/HTML, but starts from these hints.

Output (default human-readable, or --json for machine use):
    Per matched section: chapter, section index, trigger, suggested diagram type,
    and a one-line Mermaid/HTML scaffold hint.
"""

import sys
import re
import json
import argparse

# Each rule: (label, compiled regex, diagram type, scaffold hint)
# Ordered by specificity — first match wins per section.
RULES = [
    ("状态/生命周期",
     re.compile(r"状态机|生命周期|状态转换|checkpoint|savepoint|状态后端|RUNNING|FINISHED|CANCELED|状态切换"),
     "stateDiagram-v2",
     "stateDiagram-v2: [*] --> 状态A: 触发条件 ; 状态A --> 状态B"),

    ("时序/交互",
     re.compile(r"时序|水位线|watermark|event\s*time|窗口触发|提交流程|握手|交互过程|请求.*响应|心跳"),
     "sequenceDiagram",
     "sequenceDiagram: 参与者A->>参与者B: 消息 ; Note over B: 关键说明"),

    ("架构/组件分层",
     re.compile(r"架构|体系结构|JobManager|TaskManager|ResourceManager|Dispatcher|Slot|槽位|"
                r"Master|Worker|集群组成|组件|节点角色|分层|层次结构"),
     "graph TD + subgraph",
     "graph TD: subgraph 层名 ... end ; 用 |label| 标注组件间调用关系，核心节点蓝色高亮"),

    ("数据流/管道",
     re.compile(r"Source.*Sink|数据流向|数据管道|pipeline|算子链|DataStream.*Transform|"
                r"流转过程|数据流转|上游.*下游|输入.*处理.*输出"),
     "graph LR",
     "graph LR: Source -->|数据流| 算子 -->|结果流| Sink ; 起点绿色、终点橙色"),

    ("流程/步骤",
     re.compile(r"流程|步骤|第[一二三四五1-9]步|首先.*然后|执行过程|启动过程|提交作业|"
                r"工作流程|处理流程|调用过程|步骤如下"),
     "graph TD (流程图)",
     "graph TD: 步骤1 -->|完成| 步骤2 ; 决策点用菱形 节点{条件?} -->|是| ..."),

    ("分类/层级树",
     re.compile(r"分为|可分成|包括以下|主要有|划分为|种类|分类|几大类|类型有|归为|"
                r"由.*组成|包含.*和.*以及"),
     "graph LR (树/分类)",
     "graph LR: 根概念 --> 分类A & 分类B & 分类C ; 每个分类再展开要点"),

    ("对比/差异",
     re.compile(r"对比|区别|相比|不同点|差异|vs\b|与.*的比较|批.*流|有界.*无界|"
                r"优缺点|两者.*不同"),
     "Markdown 表格 或 并排 subgraph",
     "优先用对比表格(维度|A|B)；若强调结构差异用两个并排 subgraph"),
]

# Sections shorter than this are unlikely to warrant a diagram on their own
MIN_TEXT_LEN = 12


def iter_sections(data):
    """Yield (index, chapter_heading, section) across manifest or single chapter."""
    if "sections" in data and "chapters" in data:  # full manifest
        chapter = data.get("title", "")
        clevel = data.get("chapter_level", 2)
        for i, s in enumerate(data["sections"]):
            if s.get("type") == "heading" and s.get("level") == clevel:
                chapter = s["text"]
            yield i, chapter, s
    else:  # single chapter file
        chapter = data.get("heading", "")
        for i, s in enumerate(data.get("sections", [])):
            yield i, chapter, s


def suggest(data):
    """Collapse to one suggestion per (chapter, diagram_type) to avoid noise; the model
    draws one diagram per concept, not one per matching sentence."""
    seen = {}      # (chapter, dtype) -> result dict
    for idx, chapter, s in iter_sections(data):
        if s.get("type") not in ("paragraph", "heading", "list_item"):
            continue
        text = s.get("text", "")
        if len(text) < MIN_TEXT_LEN:
            continue
        for label, rx, dtype, hint in RULES:
            if rx.search(text):
                key = (chapter, dtype)
                if key not in seen:
                    seen[key] = {
                        "section_index": idx,
                        "chapter": chapter,
                        "trigger": label,
                        "diagram_type": dtype,
                        "scaffold": hint,
                        "context": text[:80],
                        "match_count": 1,
                    }
                else:
                    seen[key]["match_count"] += 1
                break  # first (most specific) rule wins
    return list(seen.values())


def main():
    ap = argparse.ArgumentParser(description="Suggest diagram spots from extracted manifest")
    ap.add_argument("manifest", help="Path to manifest.json or chapter_NN.json")
    ap.add_argument("--json", action="store_true", help="Output JSON instead of text")
    args = ap.parse_args()

    with open(args.manifest, encoding="utf-8") as f:
        data = json.load(f)

    results = suggest(data)

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return

    if not results:
        print("未发现明显需要配图的内容（或文本过短）。")
        return

    print(f"发现 {len(results)} 处建议配图的位置：\n")
    cur_chapter = None
    for r in results:
        if r["chapter"] != cur_chapter:
            cur_chapter = r["chapter"]
            print(f"\n## {cur_chapter}")
        extra = f" (命中{r['match_count']}处)" if r.get("match_count", 1) > 1 else ""
        print(f"  · [section {r['section_index']}] {r['trigger']} → {r['diagram_type']}{extra}")
        print(f"      触发文本: {r['context']}")
        print(f"      脚手架  : {r['scaffold']}")

    # Summary by diagram type
    from collections import Counter
    by_type = Counter(r["diagram_type"] for r in results)
    print("\n按图类型汇总:")
    for t, c in by_type.most_common():
        print(f"  {c:2d} × {t}")


if __name__ == "__main__":
    main()
