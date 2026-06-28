#!/usr/bin/env python3
"""
从 mhtml-refine-to-md 生成的 Obsidian 笔记中机械提取技术声明，供时效性复查（Step 7）使用。

与 doc-to-notes 版本的差异：
- 笔记 frontmatter 无 current_version 字段 → 从 tags / course / 标题推断技术名
- 有 date 字段（笔记写入日期）→ 报告中展示"笔记写于 XXXX-XX-XX"
- 有 course 字段 → 辅助推断技术领域

用法：
    python3 extract_note_claims.py <笔记.md> [--output json|text]

输出（JSON，打印到 stdout）：
{
  "title": "01-DataStream编程基础",
  "tech": "Apache Flink",
  "note_version": "",          # 无 current_version，留空
  "note_date": "2026-06-01",   # 来自 frontmatter date 字段
  "course": "Flink实战课",
  "tags": ["flink", "big-data"],
  "classes": [...],
  "methods": [...],
  "configs": [...],
  "imports": [...],
  "versions_mentioned": [...],
  "deprecated_warnings": [...],
  "code_languages": [...],
  "source_note_path": "/path/to/note.md",
  "source_note_dir": "/path/to/note/"
}
"""

import argparse
import json
import os
import re
import sys

# ── 技术关键词 → 官方文档搜索词映射 ────────────────────────────────────────────
TECH_KEYWORDS = {
    "flink": "Apache Flink",
    "spark": "Apache Spark",
    "kafka": "Apache Kafka",
    "hadoop": "Apache Hadoop",
    "hive": "Apache Hive",
    "hbase": "Apache HBase",
    "zookeeper": "Apache ZooKeeper",
    "redis": "Redis",
    "elasticsearch": "Elasticsearch",
    "rabbitmq": "RabbitMQ",
    "nginx": "Nginx",
    "kubernetes": "Kubernetes",
    "docker": "Docker",
    "spring": "Spring Framework",
    "springboot": "Spring Boot",
    "spring boot": "Spring Boot",
    "mybatis": "MyBatis",
    "mysql": "MySQL",
    "postgresql": "PostgreSQL",
    "dubbo": "Apache Dubbo",
    "pyflink": "Apache Flink",
    "pyspark": "Apache Spark",
    "claude": "Claude API",
    "openai": "OpenAI API",
    "langchain": "LangChain",
    "vue": "Vue.js",
    "react": "React",
    "golang": "Go",
    "python": "Python",
    "java": "Java",
}

# ── Frontmatter 解析 ───────────────────────────────────────────────────────────

def parse_frontmatter(md: str) -> dict:
    """提取 YAML frontmatter，返回 key→value 字典（不引入 pyyaml 依赖）。"""
    m = re.match(r'^---\n(.*?)\n---\n', md, re.DOTALL)
    if not m:
        return {}
    fm = {}
    block = m.group(1)
    current_key = None
    for line in block.splitlines():
        kv = re.match(r'^(\w[\w_-]*):\s*(.*)', line)
        if kv:
            current_key = kv.group(1)
            key, val = kv.group(1), kv.group(2).strip().strip('"').strip("'")
            fm[key] = val
        # 仅在当前活跃 key 为 tags 时收集列表项，避免其他 list key 的子项误入
        tag_item = re.match(r'^\s+-\s+(.*)', line)
        if tag_item and current_key == 'tags':
            if not isinstance(fm['tags'], list):
                fm['tags'] = []
            fm['tags'].append(tag_item.group(1).strip().strip('"').strip("'"))

    tags_inline = re.search(r'^tags:\s*\[(.*?)\]', block, re.MULTILINE)
    if tags_inline:
        fm['tags'] = [t.strip().strip('"').strip("'") for t in tags_inline.group(1).split(',') if t.strip()]

    return fm


def strip_frontmatter(md: str) -> str:
    return re.sub(r'^---\n.*?\n---\n', '', md, count=1, flags=re.DOTALL)


# ── 技术名推断 ─────────────────────────────────────────────────────────────────

def infer_tech(title: str, tags: list, course: str) -> str:
    """从 tags / course / 标题中推断技术名。"""
    combined = ' '.join([title.lower(), course.lower()] + [t.lower() for t in tags])
    for kw, official in TECH_KEYWORDS.items():
        if kw in combined:
            return official
    return ""


# ── 围栏代码块提取 ─────────────────────────────────────────────────────────────

def extract_fenced_blocks(body: str) -> list:
    """返回 [(language, content), ...] 列表。"""
    blocks = []
    pattern = re.compile(r'```(\w*)\n(.*?)```', re.DOTALL)
    for m in pattern.finditer(body):
        lang = m.group(1).lower().strip()
        content = m.group(2)
        blocks.append((lang, content))
    return blocks


# ── 技术声明提取 ───────────────────────────────────────────────────────────────

IMPORT_RE = re.compile(r'^import\s+([\w\.]+(?:\.\*)?)\s*;?', re.MULTILINE)
NEW_CLASS_RE = re.compile(r'\bnew\s+([A-Z][A-Za-z0-9_]+)\s*[(<]')
METHOD_CALL_RE = re.compile(r'\.([a-z][A-Za-z0-9_]+)\s*\(')
STATIC_CALL_RE = re.compile(r'\b([A-Z][A-Za-z0-9_]+)\.([a-zA-Z][A-Za-z0-9_]+)\s*[\(<]')
YAML_KEY_RE = re.compile(r'^([a-z][a-z0-9_.\-]+)\s*[:=]', re.MULTILINE)
VERSION_TEXT_RE = re.compile(r'\b([A-Z][A-Za-z]+(?:\s[A-Za-z]+)?)\s+(\d+\.\d+[\.\d]*)\b')
WARNING_CALLOUT_RE = re.compile(r'>\s*\[!WARNING\][^\n]*\n((?:>[^\n]*\n?)*)', re.IGNORECASE)
INLINE_CODE_RE = re.compile(r'`([A-Z][A-Za-z0-9_]+(?:\.[A-Za-z][A-Za-z0-9_]*)*)`')


def extract_claims(body: str) -> dict:
    blocks = extract_fenced_blocks(body)
    code_languages = sorted({lang for lang, _ in blocks if lang})

    imports, classes, methods, configs = set(), set(), set(), set()

    for lang, content in blocks:
        if lang in ('java', 'scala', 'kotlin', 'groovy', ''):
            for m in IMPORT_RE.finditer(content):
                imports.add(m.group(1))
            for m in NEW_CLASS_RE.finditer(content):
                classes.add(m.group(1))
            for m in STATIC_CALL_RE.finditer(content):
                classes.add(m.group(1))
                methods.add(m.group(2))
            for m in METHOD_CALL_RE.finditer(content):
                methods.add(m.group(1))
        elif lang in ('yaml', 'yml', 'properties', 'ini', 'conf', 'toml'):
            for m in YAML_KEY_RE.finditer(content):
                key = m.group(1)
                if '.' in key or '_' in key:
                    configs.add(key)
        elif lang == 'python':
            for m in re.finditer(r'^(?:from|import)\s+([\w\.]+)', content, re.MULTILINE):
                imports.add(m.group(1))
            for m in STATIC_CALL_RE.finditer(content):
                classes.add(m.group(1))
                methods.add(m.group(2))
            for m in METHOD_CALL_RE.finditer(content):
                methods.add(m.group(1))

    for m in INLINE_CODE_RE.finditer(body):
        classes.add(m.group(1))

    versions_mentioned = []
    seen_v = set()
    for m in VERSION_TEXT_RE.finditer(body):
        label = f"{m.group(1)} {m.group(2)}"
        if label not in seen_v:
            versions_mentioned.append(label)
            seen_v.add(label)

    deprecated_warnings = []
    for m in WARNING_CALLOUT_RE.finditer(body):
        callout_text = re.sub(r'^>\s*', '', m.group(1), flags=re.MULTILINE)
        for id_m in re.finditer(r'`([A-Za-z][A-Za-z0-9_\.]+)`|([A-Z][A-Za-z0-9_]+)', callout_text):
            name = id_m.group(1) or id_m.group(2)
            if name and name not in deprecated_warnings:
                deprecated_warnings.append(name)

    NOISE = {'get', 'set', 'add', 'put', 'run', 'main', 'new', 'for', 'map',
              'on', 'of', 'at', 'to', 'is', 'in', 'it', 'by', 'do', 'if'}
    methods = {m for m in methods if len(m) > 2 and m not in NOISE}
    classes = {c for c in classes if len(c) > 2}

    return {
        'classes': sorted(classes),
        'methods': sorted(methods),
        'configs': sorted(configs),
        'imports': sorted(imports),
        'versions_mentioned': versions_mentioned,
        'deprecated_warnings': deprecated_warnings,
        'code_languages': code_languages,
    }


# ── 主程序 ─────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(
        description="从 mhtml-refine-to-md 生成的笔记中提取技术声明，供时效性复查（Step 7）使用"
    )
    ap.add_argument('note', help='笔记 .md 文件路径')
    ap.add_argument('--output', choices=['json', 'text'], default='json',
                    help='输出格式（默认 json）')
    args = ap.parse_args()

    note_path = os.path.abspath(args.note)
    if not os.path.isfile(note_path):
        print(f"[ERROR] 文件不存在: {note_path}", file=sys.stderr)
        return 1

    try:
        content = open(note_path, encoding='utf-8').read()
    except OSError as e:
        print(f"[ERROR] 读取失败: {e}", file=sys.stderr)
        return 1

    fm = parse_frontmatter(content)
    body = strip_frontmatter(content)

    title = fm.get('title', os.path.splitext(os.path.basename(note_path))[0])
    tags = fm.get('tags', []) if isinstance(fm.get('tags'), list) else []
    course = fm.get('course', '')
    note_date = fm.get('date', '')

    tech = infer_tech(title, tags, course)
    claims = extract_claims(body)

    result = {
        'title': title,
        'tech': tech,
        'note_version': '',       # mhtml 笔记无 current_version 字段
        'note_date': note_date,
        'course': course,
        'tags': tags,
        **claims,
        'source_note_path': note_path,
        'source_note_dir': os.path.dirname(note_path) + os.sep,
    }

    if args.output == 'json':
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"标题    : {result['title']}")
        print(f"课程    : {result['course'] or '(未知)'}")
        print(f"技术栈  : {result['tech'] or '(未识别)'}")
        print(f"写入日期: {result['note_date'] or '(未知)'}")
        print(f"标签    : {', '.join(result['tags']) or '(无)'}")
        print(f"类名    : {', '.join(result['classes'][:20]) or '(无)'}")
        print(f"方法名  : {', '.join(result['methods'][:20]) or '(无)'}")
        print(f"配置项  : {', '.join(result['configs'][:20]) or '(无)'}")
        print(f"版本号  : {', '.join(result['versions_mentioned'][:10]) or '(无)'}")
        print(f"已废弃  : {', '.join(result['deprecated_warnings'][:10]) or '(无)'}")
        print(f"代码语言: {', '.join(result['code_languages']) or '(无)'}")

    return 0


if __name__ == '__main__':
    sys.exit(main())
