#!/usr/bin/env python3
"""故事化应用题主题词库——为数学应用题的情境参数提供趣味替换。

用法（供模型在出题时调用）:
  python3 story_themes.py list            # 列出所有可用主题
  python3 story_themes.py get <主题名>     # 返回主题的词汇表 JSON
  python3 story_themes.py sample <主题名> [--seed 42]  # 随机采样一组情境参数

主题词库提供以下字段（模型把这些值填入应用题的 stem 中替换通用词）:
  character   主角（如"恐龙小多"）
  place       场景（如"侏罗纪森林"）
  object      计数对象（如"恐龙蛋"）
  unit        单位（如"枚"）
  action      动作（如"找到了"）
  container   容器/集合（如"窝"）

示例（原始题干）:
  "每行种 7 棵树，种了 8 行，一共种了多少棵？"
  
替换后（恐龙主题）:
  "恐龙小多每窝找到 7 枚恐龙蛋，找了 8 窝，一共找到了多少枚？"
"""
from __future__ import annotations

import argparse
import json
import random
import sys

THEMES: dict[str, dict] = {
    "恐龙": {
        "desc": "侏罗纪恐龙世界",
        "characters": ["恐龙小多", "小雷龙", "迷你翼龙", "霸王龙宝宝"],
        "places": ["侏罗纪森林", "恐龙乐园", "化石山谷", "火山脚下"],
        "objects": ["恐龙蛋", "化石碎片", "恐龙脚印", "蕨类植物"],
        "units": ["枚", "块", "个", "片"],
        "actions": ["找到了", "收集了", "挖出了", "发现了"],
        "containers": ["窝", "箱", "堆", "处"],
    },
    "太空": {
        "desc": "星际探索宇宙主题",
        "characters": ["小宇航员", "星际机器人", "月球探测器", "火星小队长"],
        "places": ["月球基地", "太空站", "火星营地", "星云实验室"],
        "objects": ["月球石", "星星碎片", "太空豆", "陨石块"],
        "units": ["块", "颗", "袋", "个"],
        "actions": ["采集了", "发现了", "带回了", "运送了"],
        "containers": ["飞船", "舱", "箱", "托盘"],
    },
    "海洋": {
        "desc": "深海冒险海洋世界",
        "characters": ["小鱼泡泡", "章鱼队长", "海豚朵朵", "小螃蟹"],
        "places": ["珊瑚礁", "深海洞穴", "海草森林", "贝壳海湾"],
        "objects": ["珍珠", "贝壳", "海星", "小鱼"],
        "units": ["颗", "个", "条", "只"],
        "actions": ["找到了", "捡起了", "收集了", "看见了"],
        "containers": ["珊瑚丛", "礁石旁", "网里", "篮子里"],
    },
    "农场": {
        "desc": "快乐农场日常生活",
        "characters": ["农场小主人", "小农夫", "羊咩咩", "小鸡叽叽"],
        "places": ["苹果园", "菜地", "农场仓库", "草原上"],
        "objects": ["苹果", "胡萝卜", "鸡蛋", "玉米"],
        "units": ["个", "根", "枚", "根"],
        "actions": ["摘了", "收获了", "捡了", "种下了"],
        "containers": ["筐", "袋", "行", "排"],
    },
    "糖果": {
        "desc": "甜蜜糖果王国",
        "characters": ["糖果公主", "小糖人", "巧克力骑士", "棉花糖兔"],
        "places": ["糖果城堡", "巧克力工厂", "棉花糖云朵", "太妃糖街"],
        "objects": ["糖果", "巧克力", "棉花糖", "果冻"],
        "units": ["颗", "块", "个", "串"],
        "actions": ["分了", "吃了", "送出了", "装进了"],
        "containers": ["盒", "袋", "排", "层"],
    },
    "运动会": {
        "desc": "小学运动会竞技主题",
        "characters": ["短跑冠军", "跳绳小达人", "接力队员", "运动健将"],
        "places": ["操场", "跑道", "运动场", "比赛现场"],
        "objects": ["奖牌", "跳绳", "气球", "运动员"],
        "units": ["枚", "根", "个", "位"],
        "actions": ["获得了", "跳了", "放飞了", "参加了"],
        "containers": ["队", "组", "班", "轮"],
    },
}

# 情境模板：把经典题型套入主题情境
# {char} {place} {obj} {unit} {action} {container}
STEM_TEMPLATES: dict[str, list[str]] = {
    "乘法_行列": [
        "{char}每{container}种{n1}棵{obj}，种了{n2}{container}，一共种了多少棵？",
        "{char}每天{action}{n1}个{obj}，{n2}天一共{action}多少个？",
        "{place}里每排有{n1}只{obj}，共{n2}排，一共有多少只？",
    ],
    "加减_合并": [
        "{char}原来有{n1}个{obj}，又{action}{n2}个，现在有多少个？",
        "{place}里有{n1}只{obj}，跑走了{n2}只，还剩多少只？",
        "{char}和小伙伴共{action}{n1}+{n2}={total}个{obj}，{char}{action}了{n1}个，小伙伴{action}了多少个？",
    ],
    "除法_平分": [
        "{char}把{n1}个{obj}平均分给{n2}个小朋友，每人分几个？",
        "{place}里有{n1}只{obj}，每{container}放{n2}只，需要几个{container}？",
    ],
}


def get_theme(name: str) -> dict:
    if name not in THEMES:
        raise ValueError(f"未知主题：{name!r}，可用：{sorted(THEMES)}")
    return THEMES[name]


def sample_params(theme_name: str, r: random.Random) -> dict:
    """随机采样一组情境参数。"""
    t = get_theme(theme_name)
    return {
        "theme": theme_name,
        "character": r.choice(t["characters"]),
        "place": r.choice(t["places"]),
        "object": r.choice(t["objects"]),
        "unit": r.choice(t["units"]),
        "action": r.choice(t["actions"]),
        "container": r.choice(t["containers"]),
    }


def wrap_stem(original_stem: str, theme_name: str, seed: int | None = None) -> str:
    """把一道应用题的 stem 包裹上主题情境前缀。
    
    这是一个辅助函数，模型可以调用它为经典题干加上情境感：
    在原题干前加上 "[主题情境] " 的前缀标记，
    真正的改写由模型完成（此函数只提供词汇参考）。
    """
    r = random.Random(seed)
    params = sample_params(theme_name, r)
    prefix = f"【{params['theme']}主题 · {params['character']}在{params['place']}】"
    return f"{prefix}\n{original_stem}"


def cmd_list(args) -> int:
    out = {name: {"desc": t["desc"], "sample_object": t["objects"][0]} for name, t in THEMES.items()}
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def cmd_get(args) -> int:
    try:
        t = get_theme(args.theme)
    except ValueError as e:
        sys.exit(str(e))
    print(json.dumps({args.theme: t}, ensure_ascii=False, indent=2))
    return 0


def cmd_sample(args) -> int:
    r = random.Random(args.seed)
    try:
        params = sample_params(args.theme, r)
    except ValueError as e:
        sys.exit(str(e))
    # 也附上情境模板示例
    template_type = args.template or "乘法_行列"
    templates = STEM_TEMPLATES.get(template_type, [])
    if templates:
        tpl = r.choice(templates)
        # fill in placeholders that exist
        import re
        filled = re.sub(r"\{char\}", params["character"], tpl)
        filled = re.sub(r"\{place\}", params["place"], filled)
        filled = re.sub(r"\{obj\}", params["object"], filled)
        filled = re.sub(r"\{unit\}", params["unit"], filled)
        filled = re.sub(r"\{action\}", params["action"], filled)
        filled = re.sub(r"\{container\}", params["container"], filled)
        params["sample_stem"] = filled
    print(json.dumps(params, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="列出所有可用主题").set_defaults(func=cmd_list)

    p_get = sub.add_parser("get", help="获取指定主题词汇表")
    p_get.add_argument("theme")
    p_get.set_defaults(func=cmd_get)

    p_sam = sub.add_parser("sample", help="随机采样一组情境参数")
    p_sam.add_argument("theme")
    p_sam.add_argument("--seed", type=int)
    p_sam.add_argument("--template", help=f"情境模板类型（{', '.join(STEM_TEMPLATES)}）")
    p_sam.set_defaults(func=cmd_sample)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
