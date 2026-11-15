#!/usr/bin/env python3
"""校验 data/templates/exam_templates.json：每套模板总分必须为 100，题量×分值一致。

用法: python3 -I validate_templates.py [exam_templates.json]
"""
import sys
import json
import os

DEFAULT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "..", "data", "templates", "exam_templates.json")


def check_section(path, s, errs):
    if "per" in s:
        if s["count"] * s["per"] != s["points"]:
            errs.append(f"{path}/{s['id']}: count×per={s['count']*s['per']} ≠ points={s['points']}")
    elif "points_list" in s:
        if sum(s["points_list"]) != s["points"]:
            errs.append(f"{path}/{s['id']}: points_list 合计 {sum(s['points_list'])} ≠ points={s['points']}")
        if len(s["points_list"]) != s["count"]:
            errs.append(f"{path}/{s['id']}: points_list 长度 {len(s['points_list'])} ≠ count={s['count']}")
    else:
        errs.append(f"{path}/{s['id']}: 缺 per 或 points_list")
    if s["points"] <= 0:
        errs.append(f"{path}/{s['id']}: points 必须为正")


def main():
    p = sys.argv[1] if len(sys.argv) > 1 else DEFAULT
    data = json.load(open(p))
    errs, n = [], 0
    for k, lv in data.get("difficulty_levels", {}).items():
        if sum(lv["ratio"].values()) != 100:
            errs.append(f"difficulty_levels/{k}: 比例合计 {sum(lv['ratio'].values())} ≠ 100")
    for subj in ("math", "chinese", "english"):
        for grade, kinds in data[subj].items():
            for kind, t in kinds.items():
                path = f"{subj}/{grade}/{kind}"
                n += 1
                if "same_as" in t:
                    if t["same_as"] not in kinds or "sections" not in kinds[t["same_as"]]:
                        errs.append(f"{path}: same_as 指向无效")
                    continue
                for s in t["sections"]:
                    check_section(path, s, errs)
                tot = sum(s["points"] for s in t["sections"])
                if tot != data["total"]:
                    errs.append(f"{path}: 总分 {tot} ≠ {data['total']}")
                ids = [s["id"] for s in t["sections"]]
                if len(ids) != len(set(ids)):
                    errs.append(f"{path}: section id 重复")
    for e in errs:
        print("FAIL", e)
    print(f"{n} templates checked, {len(errs)} errors")
    sys.exit(1 if errs else 0)


if __name__ == "__main__":
    main()
