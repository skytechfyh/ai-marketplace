#!/usr/bin/env python3
"""校验 data/knowledge/**/*.json：id 唯一、前置知识点存在且不成环、层级与题型在词表内、单元号合法。

用法: python3 -I validate_knowledge.py [知识点目录]
"""
import os
import sys
import json
import glob

LEVELS = {"了解", "理解", "掌握", "运用"}      # 数学：课标附录2；语文/英语沿用同一套
DEFAULT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "knowledge")
REQUIRED = ("id", "name", "unit", "pages", "std", "level", "prereq", "mastery", "error_types", "item_types")


def has_cycle(graph):
    state = {}

    def visit(n):
        if state.get(n) == 1:
            return True
        if state.get(n) == 2:
            return False
        state[n] = 1
        if any(visit(m) for m in graph.get(n, [])):
            return True
        state[n] = 2
        return False
    return any(visit(n) for n in graph)


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else DEFAULT
    files = sorted(glob.glob(os.path.join(root, "**", "*.json"), recursive=True))
    errs, total = [], 0
    for f in files:
        d = json.load(open(f))
        kps = d["knowledge_points"]
        vocab = set(d.get("item_type_vocab", []))
        units = set(d.get("unit_goals", {}))
        ids = [k["id"] for k in kps]
        name = os.path.relpath(f, root)
        total += len(kps)
        if len(ids) != len(set(ids)):
            errs.append(f"{name}: id 重复")
        for k in kps:
            for r in REQUIRED:
                if r not in k:
                    errs.append(f"{name}/{k.get('id')}: 缺字段 {r}")
            if k.get("level") not in LEVELS:
                errs.append(f"{name}/{k['id']}: level={k.get('level')} 不在词表")
            for p in k.get("prereq", []):
                if p not in ids:
                    errs.append(f"{name}/{k['id']}: 前置 {p} 不存在")
            bad = set(k.get("item_types", [])) - vocab
            if bad:
                errs.append(f"{name}/{k['id']}: 题型不在词表 {sorted(bad)}")
            if units and str(k["unit"]) not in units:
                errs.append(f"{name}/{k['id']}: unit={k['unit']} 无对应 unit_goals")
        if has_cycle({k["id"]: k.get("prereq", []) for k in kps}):
            errs.append(f"{name}: 前置关系成环")
    for e in errs:
        print("FAIL", e)
    print(f"{len(files)} files, {total} knowledge points, {len(errs)} errors")
    sys.exit(1 if errs else 0)


if __name__ == "__main__":
    main()
