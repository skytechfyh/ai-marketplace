"""试卷 MD 中的版式指令：`{{名称 key=value ...}}` → HTML/SVG。

家长可直接编辑 MD 里的指令行；渲染时由 render_pdf.py 展开。
所有图形都由代码生成（纯 SVG，无第三方依赖），缺参数直接报错，不画“差不多”的图。
"""
import base64
import math
import re
import shlex
from html import escape

# ---- 田字格 / 拼音格 -------------------------------------------------------


def _svg_data_uri(svg: str) -> str:
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode("ascii")


_CROSS = _svg_data_uri(
    "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100' preserveAspectRatio='none'>"
    "<g stroke='#999' stroke-width='1.5' stroke-dasharray='6,5' fill='none'>"
    "<line x1='50' y1='0' x2='50' y2='100'/><line x1='0' y1='50' x2='100' y2='50'/></g></svg>"
)
# 四线三格：四条横线等分上中下三格，供手写拼音（看字写拼音）
_PINYIN_LINES = _svg_data_uri(
    "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 90' preserveAspectRatio='none'>"
    "<line x1='0' y1='2' x2='100' y2='2' stroke='#666' stroke-width='1.5'/>"
    "<line x1='0' y1='31' x2='100' y2='31' stroke='#999' stroke-width='1.2' stroke-dasharray='5,4'/>"
    "<line x1='0' y1='60' x2='100' y2='60' stroke='#555' stroke-width='1.5'/>"
    "<line x1='0' y1='88' x2='100' y2='88' stroke='#666' stroke-width='1.5'/></svg>"
)


def tianzige(n="8", chars=""):
    """一行 n 个田字格；chars 非空时依次印出浅色范字（描红/抄写用）。"""
    n = int(n)
    cells = []
    for i in range(n):
        ch = escape(chars[i]) if i < len(chars) else ""
        cells.append(f"<span class='tzg'>{ch}</span>")
    return f"<span class='gridrow'>{''.join(cells)}</span>"


def pinyin_tianzige(py="", chars=""):
    """拼音格 + 田字格。py 给拼音（空格分隔音节）则印拼音、田字格留白（看拼音写词语）；
    chars 给汉字则印汉字、拼音格印四线三格留白（看字写拼音）。两者音节/字数必须一致。"""
    syll = py.split()
    if syll and chars and len(syll) != len(chars):
        raise ValueError(f"拼音音节数 {len(syll)} 与汉字数 {len(chars)} 不一致")
    n = len(syll) or len(chars)
    if n == 0:
        raise ValueError("pinyin_tianzige 需要 py 或 chars")
    py_cls = "pyg" if syll else "pyg pyg-empty"
    units = []
    for i in range(n):
        p = escape(syll[i]) if syll else ""
        c = escape(chars[i]) if chars else ""
        units.append(
            f"<span class='pzu'><span class='{py_cls}'>{p}</span><span class='tzg'>{c}</span></span>"
        )
    return f"<span class='pzword'>{''.join(units)}</span>"


def fourline(rows="2"):
    """英语四线三格，rows 行。基线（第三条线）加粗。"""
    rows = int(rows)
    h = 12  # 每行 12mm，三格各 4mm
    parts = []
    for r in range(rows):
        y0 = r * (h + 4)
        parts.append(
            f"<line x1='0' y1='{y0}' x2='178' y2='{y0}' stroke='#888' stroke-width='0.3'/>"
            f"<line x1='0' y1='{y0 + 4}' x2='178' y2='{y0 + 4}' stroke='#888' stroke-width='0.3' stroke-dasharray='1.5,1'/>"
            f"<line x1='0' y1='{y0 + 8}' x2='178' y2='{y0 + 8}' stroke='#000' stroke-width='0.5'/>"
            f"<line x1='0' y1='{y0 + 12}' x2='178' y2='{y0 + 12}' stroke='#888' stroke-width='0.3'/>"
        )
    total = rows * (h + 4) - 4
    return (
        f"<div class='fourline'><svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 178 {total}' "
        f"width='100%' style='height:{total}mm'>{''.join(parts)}</svg></div>"
    )


def workspace(h="30", label="解："):
    return f"<div class='workspace' style='height:{int(h)}mm'><span>{escape(label)}</span></div>"


def blank(n="4"):
    return f"<span class='blank' style='min-width:{float(n)}em'>&nbsp;</span>"


# ---- 数学图形 -------------------------------------------------------------

def _num(v, name):
    try:
        x = float(v)
    except ValueError:
        raise ValueError(f"参数 {name}={v!r} 不是数字")
    if x <= 0:
        raise ValueError(f"参数 {name} 必须大于 0")
    return x


def _fmt(x):
    return str(int(x)) if float(x).is_integer() else str(x)


def fig_rect(w=None, h=None, unit="厘米"):
    """长方形，标注长和宽；比例按真实数值缩放。w/h 传 ? 表示不标数值。"""
    if w is None or h is None:
        raise ValueError("fig_rect 需要 w 和 h")
    wv, hv = (None if w == "?" else _num(w, "w")), (None if h == "?" else _num(h, "h"))
    rw, rh = _num(w if wv else "1", "w"), _num(h if hv else "1", "h")
    scale = min(60 / rw, 36 / rh)
    pw, ph = max(rw * scale, 18), max(rh * scale, 12)
    x0, y0 = 14, 6
    wl = f"{_fmt(wv)}{escape(unit)}" if wv else "?"
    hl = f"{_fmt(hv)}{escape(unit)}" if hv else "?"
    svg = (
        f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 {pw + 34} {ph + 20}' "
        f"style='width:{pw + 34}mm;height:{ph + 20}mm'>"
        f"<rect x='{x0}' y='{y0}' width='{pw}' height='{ph}' fill='none' stroke='#000' stroke-width='0.5'/>"
        f"<text x='{x0 + pw / 2}' y='{y0 + ph + 7}' text-anchor='middle' font-size='4'>{wl}</text>"
        f"<text x='{x0 - 2}' y='{y0 + ph / 2 + 1.5}' text-anchor='end' font-size='4'>{hl}</text></svg>"
    )
    return f"<div class='fig'>{svg}</div>"


def fig_clock(h=None, m=None):
    """钟面：整点/几时几分。时针按分钟连续偏移，和真实钟表一致。"""
    if h is None or m is None:
        raise ValueError("fig_clock 需要 h 和 m")
    hh, mm = int(h), int(m)
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        raise ValueError(f"时间 {hh}:{mm} 不合法")
    r, cx, cy = 22, 25, 25
    parts = [f"<circle cx='{cx}' cy='{cy}' r='{r}' fill='none' stroke='#000' stroke-width='0.7'/>"]
    for i in range(60):
        a = math.radians(i * 6)
        long_ = i % 5 == 0
        r1 = r - (3 if long_ else 1.5)
        parts.append(
            f"<line x1='{cx + r * math.sin(a):.2f}' y1='{cy - r * math.cos(a):.2f}' "
            f"x2='{cx + r1 * math.sin(a):.2f}' y2='{cy - r1 * math.cos(a):.2f}' "
            f"stroke='#000' stroke-width='{0.5 if long_ else 0.2}'/>"
        )
    for i in range(1, 13):
        a = math.radians(i * 30)
        tx, ty = cx + (r - 5.6) * math.sin(a), cy - (r - 5.6) * math.cos(a)
        parts.append(
            f"<text x='{tx:.2f}' y='{ty + 1.4:.2f}' text-anchor='middle' font-size='3.8'>{i}</text>"
        )
    ha = math.radians(((hh % 12) + mm / 60) * 30)
    ma = math.radians(mm * 6)
    parts.append(
        f"<line x1='{cx}' y1='{cy}' x2='{cx + 9.5 * math.sin(ha):.2f}' y2='{cy - 9.5 * math.cos(ha):.2f}' "
        f"stroke='#000' stroke-width='1.2' stroke-linecap='round'/>"
        f"<line x1='{cx}' y1='{cy}' x2='{cx + 13.8 * math.sin(ma):.2f}' y2='{cy - 13.8 * math.cos(ma):.2f}' "
        f"stroke='#000' stroke-width='0.7' stroke-linecap='round'/>"
        f"<circle cx='{cx}' cy='{cy}' r='1' fill='#000'/>"
    )
    svg = (
        f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 50 50' style='width:42mm;height:42mm'>"
        f"{''.join(parts)}</svg>"
    )
    return f"<div class='fig'>{svg}</div>"


def fig_bars(data=None, title="", ymax=None, step="1"):
    """条形统计图。data='苹果:5,香蕉:8,梨:3'；ymax 缺省取数据最大值向上取到 step 的倍数。"""
    if not data:
        raise ValueError("fig_bars 需要 data，如 data='苹果:5,香蕉:8'")
    items = []
    for kv in data.split(","):
        k, _, v = kv.partition(":")
        if not k.strip() or not v.strip():
            raise ValueError(f"data 项格式应为 名称:数值，实际 {kv!r}")
        items.append((k.strip(), _num(v, k)))
    st = _num(step, "step")
    data_max = max(v for _, v in items)
    top = _num(ymax, "ymax") if ymax else math.ceil(data_max / st) * st
    if top < data_max:
        raise ValueError(f"ymax={_fmt(top)} 小于数据最大值 {_fmt(data_max)}，柱形会超出图表区域")
    W, H, L, B = 90, 55, 12, 10  # 画布宽高、左边距、底边距
    ph = H - B - 6
    pw = W - L - 4
    parts = []
    t = 0.0
    while t <= top + 1e-9:
        y = H - B - t / top * ph
        parts.append(
            f"<line x1='{L}' y1='{y:.2f}' x2='{L + pw}' y2='{y:.2f}' stroke='#bbb' stroke-width='0.2'/>"
            f"<text x='{L - 1.5}' y='{y + 1.2:.2f}' text-anchor='end' font-size='3.2'>{_fmt(t)}</text>"
        )
        t += st
    bw = pw / len(items) * 0.5
    for i, (k, v) in enumerate(items):
        cx = L + pw / len(items) * (i + 0.5)
        bh = v / top * ph
        parts.append(
            f"<rect x='{cx - bw / 2:.2f}' y='{H - B - bh:.2f}' width='{bw:.2f}' height='{bh:.2f}' "
            f"fill='#ddd' stroke='#000' stroke-width='0.3'/>"
            f"<text x='{cx:.2f}' y='{H - B + 4.5}' text-anchor='middle' font-size='3.4'>{escape(k)}</text>"
        )
    parts.append(
        f"<line x1='{L}' y1='{H - B}' x2='{L + pw}' y2='{H - B}' stroke='#000' stroke-width='0.4'/>"
        f"<line x1='{L}' y1='{H - B}' x2='{L}' y2='{H - B - ph - 2}' stroke='#000' stroke-width='0.4'/>"
    )
    if title:
        parts.append(f"<text x='{W / 2}' y='4' text-anchor='middle' font-size='3.8'>{escape(title)}</text>")
    svg = (
        f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 {W} {H}' "
        f"style='width:{W}mm;height:{H}mm'>{''.join(parts)}</svg>"
    )
    return f"<div class='fig'>{svg}</div>"


def _flt(v, name, lo=None, hi=None):
    """解析浮点参数，可限定闭区间 [lo, hi]；可为 0 或负数（_num 要求必须 > 0）。"""
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise ValueError(f"参数 {name}={v!r} 不是数字")
    if lo is not None and x < lo:
        raise ValueError(f"参数 {name}={_fmt(x)} 不能小于 {_fmt(lo)}")
    if hi is not None and x > hi:
        raise ValueError(f"参数 {name}={_fmt(x)} 不能大于 {_fmt(hi)}")
    return x


def _int(v, name, lo=None, hi=None):
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise ValueError(f"参数 {name}={v!r} 不是整数")
    if not x.is_integer():
        raise ValueError(f"参数 {name}={v!r} 必须是整数")
    return int(_flt(x, name, lo, hi))


def _fmt6(x):
    return _fmt(round(float(x), 6) + 0.0)


def _yesno(v, name):
    if v not in ("yes", "no"):
        raise ValueError(f"参数 {name} 只能是 yes 或 no，实际 {v!r}")
    return v == "yes"


def _svg(vb_w, vb_h, body, w_mm=None, h_mm=None):
    w_mm = vb_w if w_mm is None else w_mm
    h_mm = vb_h if h_mm is None else h_mm
    return (
        f"<div class='fig'><svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 {vb_w:.2f} {vb_h:.2f}' "
        f"style='width:{w_mm:.2f}mm;height:{h_mm:.2f}mm'>{body}</svg></div>"
    )


def fig_ruler(a=None, b=None, length=None, show="no"):
    """直尺量物：物体（铅笔条）从刻度 a 画到 b，尺面印厘米/毫米刻度；a、b 单位为厘米，可带小数（精确到 0.1）。
    length 为尺长（厘米，缺省取 ceil(b)+1，至多 20）。show=yes 时在物体上方标出长度（讲评用，题面默认 no）。"""
    if a is None or b is None:
        raise ValueError("fig_ruler 需要 a 和 b（物体左右端对应的刻度，单位厘米）")
    av, bv = _flt(a, "a", 0), _flt(b, "b", 0)
    if abs(av * 10 - round(av * 10)) > 1e-6 or abs(bv * 10 - round(bv * 10)) > 1e-6:
        raise ValueError("a、b 只能精确到 0.1 厘米（即整毫米）")
    if bv <= av:
        raise ValueError(f"需要 b > a，实际 a={_fmt6(av)} b={_fmt6(bv)}")
    L = _int(length, "length", 2, 20) if length is not None else max(3, math.ceil(bv) + 1)
    if bv > L:
        raise ValueError(f"物体右端 b={_fmt6(bv)} 超出尺长 {L} 厘米")
    u, x0 = 9.0, 6.0  # 每厘米 9 单位
    W = L * u + 2 * x0
    parts = [f"<rect x='{x0 + av * u:.2f}' y='4' width='{(bv - av) * u:.2f}' height='7' fill='#ddd' stroke='#000' stroke-width='0.4'/>"]
    if _yesno(show, "show"):
        parts.append(
            f"<text x='{x0 + (av + bv) / 2 * u:.2f}' y='3' text-anchor='middle' font-size='3.4'>{_fmt6(bv - av)}厘米</text>"
        )
    parts.append(f"<rect x='{x0 - 3}' y='12' width='{L * u + 6:.2f}' height='17' fill='none' stroke='#000' stroke-width='0.5'/>")
    for i in range(L * 10 + 1):
        x = x0 + i * u / 10
        tl, sw = (6, 0.5) if i % 10 == 0 else (4.2, 0.35) if i % 5 == 0 else (2.5, 0.25)
        parts.append(f"<line x1='{x:.2f}' y1='12' x2='{x:.2f}' y2='{12 + tl}' stroke='#000' stroke-width='{sw}'/>")
        if i % 10 == 0:
            parts.append(f"<text x='{x:.2f}' y='22' text-anchor='middle' font-size='3.6'>{i // 10}</text>")
    parts.append(f"<text x='{W - x0 + 1:.2f}' y='27.5' text-anchor='end' font-size='3'>cm</text>")
    return _svg(W, 31, "".join(parts))


def fig_angle(deg=None, show="no", label=""):
    """角：顶点处一条水平射线，另一条逆时针转 deg 度（1~359）；90° 画直角标记，其余画小弧。
    show=yes 时标出度数；label 非空时在角内标出该文字（如 ∠1 或 ?），优先于度数。"""
    if deg is None:
        raise ValueError("fig_angle 需要 deg（角度数，1~359）")
    d = _flt(deg, "deg", 1, 359)
    R, V = 28.0, (0.0, 0.0)
    rad = math.radians(d)
    tip = (R * math.cos(rad), -R * math.sin(rad))
    xs, ys = [0.0, R, tip[0]], [0.0, tip[1]]
    if d > 180:
        ys.append(R * 0.0 + 0.0)
    r = 8.0
    if abs(d - 90) < 1e-9:
        arc = f"<path d='M {r} 0 L {r} {-r} L 0 {-r}' fill='none' stroke='#000' stroke-width='0.4'/>"
    else:
        large = 1 if d > 180 else 0
        arc = (
            f"<path d='M {r} 0 A {r} {r} 0 {large} 0 {r * math.cos(rad):.3f} {-r * math.sin(rad):.3f}' "
            f"fill='none' stroke='#000' stroke-width='0.4'/>"
        )
    text = label if label else (f"{_fmt6(d)}°" if _yesno(show, "show") else "")
    lab = ""
    if text:
        mid = rad / 2
        lab = (
            f"<text x='{15 * math.cos(mid):.2f}' y='{-15 * math.sin(mid) + 1.2:.2f}' "
            f"text-anchor='middle' font-size='3.6'>{escape(text)}</text>"
        )
    body = (
        f"<line x1='0' y1='0' x2='{R}' y2='0' stroke='#000' stroke-width='0.6'/>"
        f"<line x1='0' y1='0' x2='{tip[0]:.3f}' y2='{tip[1]:.3f}' stroke='#000' stroke-width='0.6'/>"
        f"<circle cx='0' cy='0' r='0.9' fill='#000'/>{arc}{lab}"
    )
    # 视口：包住两条射线、整个小弧与文字，四周留白
    minx = min(xs) - 7
    maxx = max(xs) + 5
    miny = min(min(ys), -r) - 6 if d <= 180 else -R - 6
    maxy = 6 if d <= 180 else R + 6
    w, h = maxx - minx, maxy - miny
    svg = (
        f"<div class='fig'><svg xmlns='http://www.w3.org/2000/svg' viewBox='{minx:.2f} {miny:.2f} {w:.2f} {h:.2f}' "
        f"style='width:{w:.2f}mm;height:{h:.2f}mm'>{body}</svg></div>"
    )
    return svg


def fig_grid(rows=None, cols=None, cell="5", shade="", axis="", haxis=""):
    """方格纸（对称/平移/面积用）。shade='r,c;r,c' 涂灰指定方格（行列均从 0 起，自上而下、自左而右）；
    axis=n 在第 n 列右侧画竖虚线（对称轴，可为 2.5 等整格以外的位置不被允许，仅整数）；haxis=n 同理画横虚线。"""
    if rows is None or cols is None:
        raise ValueError("fig_grid 需要 rows 和 cols")
    R, C = _int(rows, "rows", 1, 20), _int(cols, "cols", 1, 20)
    cs = _num(cell, "cell")
    if cs > 12:
        raise ValueError("cell 不能超过 12 毫米")
    parts = []
    seen = set()
    for tok in [t for t in shade.split(";") if t.strip()]:
        rr, _, cc = tok.partition(",")
        ri, ci = _int(rr, "shade.行", 0, R - 1), _int(cc, "shade.列", 0, C - 1)
        if (ri, ci) in seen:
            raise ValueError(f"shade 中方格 {ri},{ci} 重复")
        seen.add((ri, ci))
        parts.append(f"<rect x='{ci * cs}' y='{ri * cs}' width='{cs}' height='{cs}' fill='#bbb'/>")
    for i in range(R + 1):
        parts.append(f"<line x1='0' y1='{i * cs}' x2='{C * cs}' y2='{i * cs}' stroke='#555' stroke-width='0.25'/>")
    for j in range(C + 1):
        parts.append(f"<line x1='{j * cs}' y1='0' x2='{j * cs}' y2='{R * cs}' stroke='#555' stroke-width='0.25'/>")
    dash = "stroke='#000' stroke-width='0.5' stroke-dasharray='2,1.2'"
    if axis != "":
        n = _int(axis, "axis", 0, C)
        parts.append(f"<line x1='{n * cs}' y1='-2' x2='{n * cs}' y2='{R * cs + 2}' {dash}/>")
    if haxis != "":
        n = _int(haxis, "haxis", 0, R)
        parts.append(f"<line x1='-2' y1='{n * cs}' x2='{C * cs + 2}' y2='{n * cs}' {dash}/>")
    pad = 3
    body = f"<g transform='translate({pad},{pad})'>{''.join(parts)}</g>"
    return _svg(C * cs + 2 * pad, R * cs + 2 * pad, body)


def fig_fraction(n=None, d=None, shape="circle", show="no"):
    """分数图：整体平均分成 d 份，涂灰其中 n 份（圆或长条）。show=yes 时在图下印出分数 n/d（讲评用）。"""
    if n is None or d is None:
        raise ValueError("fig_fraction 需要 n（涂色份数）和 d（总份数）")
    dv = _int(d, "d", 1, 12)
    nv = _int(n, "n", 0, dv)
    if shape not in ("circle", "rect"):
        raise ValueError(f"shape 只能是 circle 或 rect，实际 {shape!r}")
    parts = []
    if shape == "circle":
        cx = cy = 16.0
        r = 14.0
        if dv == 1:
            parts.append(f"<circle cx='{cx}' cy='{cy}' r='{r}' fill='{'#bbb' if nv else 'none'}' stroke='#000' stroke-width='0.5'/>")
        else:
            for k in range(dv):
                a0, a1 = math.radians(k * 360 / dv), math.radians((k + 1) * 360 / dv)
                p0 = (cx + r * math.sin(a0), cy - r * math.cos(a0))
                p1 = (cx + r * math.sin(a1), cy - r * math.cos(a1))
                large = 1 if 360 / dv > 180 else 0
                parts.append(
                    f"<path d='M {cx} {cy} L {p0[0]:.3f} {p0[1]:.3f} A {r} {r} 0 {large} 1 {p1[0]:.3f} {p1[1]:.3f} Z' "
                    f"fill='{'#bbb' if k < nv else 'none'}' stroke='#000' stroke-width='0.5'/>"
                )
        w, h = 32.0, 32.0
    else:
        bw, bh, x0 = 54.0, 12.0, 3.0
        seg = bw / dv
        for k in range(dv):
            parts.append(
                f"<rect x='{x0 + k * seg:.3f}' y='3' width='{seg:.3f}' height='{bh}' "
                f"fill='{'#bbb' if k < nv else 'none'}' stroke='#000' stroke-width='0.5'/>"
            )
        w, h = bw + 2 * x0, bh + 6
    if _yesno(show, "show"):
        parts.append(f"<text x='{w / 2}' y='{h + 4.5}' text-anchor='middle' font-size='4'>{nv}/{dv}</text>")
        h += 6
    return _svg(w, h, "".join(parts))


def fig_numline(min=None, max=None, step="1", marks="", labels="all", hide=""):
    """数射线/数轴：[min,max] 按 step 画刻度。marks='A:3,B:7.5' 在对应位置画点并标字母；
    labels=all|ends|none 控制刻度数字；hide='3,5' 把这些刻度的数字换成空格子（填数用）。"""
    if min is None or max is None:
        raise ValueError("fig_numline 需要 min 和 max")
    lo, hi, st = _flt(min, "min"), _flt(max, "max"), _num(step, "step")
    if hi <= lo:
        raise ValueError(f"需要 max > min，实际 min={_fmt6(lo)} max={_fmt6(hi)}")
    cnt_f = (hi - lo) / st
    cnt = round(cnt_f)
    if abs(cnt_f - cnt) > 1e-6:
        raise ValueError(f"(max-min) 必须是 step 的整数倍：({_fmt6(hi)}-{_fmt6(lo)})/{_fmt6(st)}={cnt_f:.4f}")
    if cnt > 40:
        raise ValueError(f"刻度过多（{cnt} 段），请增大 step（最多 40 段）")
    if labels not in ("all", "ends", "none"):
        raise ValueError(f"labels 只能是 all/ends/none，实际 {labels!r}")
    hidden = set()
    for t in [t for t in hide.split(",") if t.strip()]:
        v = _flt(t, "hide", lo, hi)
        k = (v - lo) / st
        if abs(k - round(k)) > 1e-6:
            raise ValueError(f"hide 中的 {t.strip()} 不在刻度上")
        hidden.add(round(k))
    W, m, y0 = 170.0, 8.0, 10.0
    unit = (W - 2 * m - 6) / cnt
    parts = [
        f"<line x1='{m - 3}' y1='{y0}' x2='{W - m + 3}' y2='{y0}' stroke='#000' stroke-width='0.5'/>"
        f"<path d='M {W - m + 3} {y0} l -2.5 -1.2 M {W - m + 3} {y0} l -2.5 1.2' stroke='#000' stroke-width='0.5' fill='none'/>"
    ]
    for k in range(cnt + 1):
        x = m + k * unit
        parts.append(f"<line x1='{x:.2f}' y1='{y0 - 1.8}' x2='{x:.2f}' y2='{y0 + 1.8}' stroke='#000' stroke-width='0.4'/>")
        show_lab = labels == "all" or (labels == "ends" and k in (0, cnt))
        if not show_lab:
            continue
        if k in hidden:
            parts.append(
                f"<rect x='{x - 3:.2f}' y='{y0 + 3.5}' width='6' height='4.6' fill='none' stroke='#000' stroke-width='0.35'/>"
            )
        else:
            parts.append(f"<text x='{x:.2f}' y='{y0 + 7.2}' text-anchor='middle' font-size='3.4'>{_fmt6(lo + k * st)}</text>")
    for tok in [t for t in marks.split(",") if t.strip()]:
        nm, _, val = tok.partition(":")
        if not nm.strip() or not val.strip():
            raise ValueError(f"marks 项格式应为 字母:数值，实际 {tok!r}")
        v = _flt(val, nm.strip(), lo, hi)
        x = m + (v - lo) / st * unit
        parts.append(
            f"<circle cx='{x:.2f}' cy='{y0}' r='1.3' fill='#000'/>"
            f"<text x='{x:.2f}' y='{y0 - 3.6}' text-anchor='middle' font-size='3.8'>{escape(nm.strip())}</text>"
        )
    return _svg(W, 20, "".join(parts))


# ---- 游戏化识字题型 -------------------------------------------------------

def lianxian(left=None, right=None, shuffle="yes"):
    """连线题：左列与右列一一对应，中间画虚线连接区。
    left='妈妈,爸爸,哥哥' right='māma,bàba,gēge'（逗号分隔，数量必须相同）。
    shuffle=yes 时右列自动随机打乱顺序（默认 yes）。
    渲染为两列文字 + 中间空白留给孩子画线。"""
    if left is None or right is None:
        raise ValueError("lianxian 需要 left 和 right（逗号分隔）")
    lefts = [x.strip() for x in left.split(",") if x.strip()]
    rights = [x.strip() for x in right.split(",") if x.strip()]
    if not lefts:
        raise ValueError("lianxian left 不能为空")
    if len(lefts) != len(rights):
        raise ValueError(f"lianxian left 有 {len(lefts)} 项，right 有 {len(rights)} 项，数量必须相同")
    if len(lefts) > 10:
        raise ValueError("lianxian 最多 10 对")
    # shuffle right column in a deterministic way (sort by hash) for display
    if _yesno(shuffle, "shuffle"):
        import hashlib
        rights = sorted(rights, key=lambda x: hashlib.md5(x.encode()).hexdigest())

    rows = []
    for i, (l, r) in enumerate(zip(lefts, rights)):
        rows.append(
            f"<tr>"
            f"<td class='lx-left'>{escape(l)}</td>"
            f"<td class='lx-mid'></td>"
            f"<td class='lx-right'>{escape(r)}</td>"
            f"</tr>"
        )
    return (
        "<div class='lianxian'>"
        "<table class='lx-table'>"
        "<colgroup><col class='lx-col-l'/><col class='lx-col-m'/><col class='lx-col-r'/></colgroup>"
        f"{''.join(rows)}"
        "</table></div>"
    )


def zhaopengyou(char=None, candidates=None, answers=None):
    """找朋友：给出一个汉字，从候选字中找出能与之组词的字，圈出来。
    char='青' candidates='清,请,蜻,山,水,风' answers='清,请,蜻'（answers 仅出现在答案版，题面不显示）。"""
    if char is None or candidates is None:
        raise ValueError("zhaopengyou 需要 char 和 candidates（逗号分隔）")
    cands = [x.strip() for x in candidates.split(",") if x.strip()]
    if not cands:
        raise ValueError("zhaopengyou candidates 不能为空")
    if len(cands) > 12:
        raise ValueError("zhaopengyou candidates 最多 12 个")
    # answers 参数存在时在答案框里加标记（仅供 build_answer_md 用，题面忽略）
    ans_set: set[str] = set()
    if answers:
        ans_set = {x.strip() for x in answers.split(",") if x.strip()}

    boxes = []
    for c in cands:
        mark = " zpf-answer" if c in ans_set else ""
        boxes.append(f"<span class='zpf-box{mark}'>{escape(c)}</span>")

    return (
        "<div class='zhaopengyou'>"
        f"<span class='zpf-char'>{escape(char)}</span>"
        "<span class='zpf-plus'>＋</span>"
        f"<span class='zpf-cands'>{''.join(boxes)}</span>"
        "</div>"
    )


def caizimi(riddle=None, hint=""):
    """猜字谜：显示谜面文字，下方留一个大方格供孩子填写答案。
    riddle='左边绿，右边红，左右相遇起凉风。' hint='（提示：与树木有关）'（可选）。"""
    if not riddle:
        raise ValueError("caizimi 需要 riddle（谜面文字）")
    hint_html = f"<div class='czm-hint'>{escape(hint)}</div>" if hint else ""
    return (
        "<div class='caizimi'>"
        f"<div class='czm-riddle'>{escape(riddle)}</div>"
        f"{hint_html}"
        "<div class='czm-answer'><span class='czm-box'></span></div>"
        "</div>"
    )


def tupian_xuanzi(desc=None, candidates=None, answer=""):
    """看图选字：用文字描述图意（取代实际图片），候选字用方框展示，孩子圈出正确的字填入括号。
    desc='图中画着一只小（  ）在荷叶上跳来跳去。' candidates='蛙,娃,洼' answer='蛙'（answer 仅供答案版）。"""
    if not desc or not candidates:
        raise ValueError("tupian_xuanzi 需要 desc（图意描述）和 candidates（候选字，逗号分隔）")
    cands = [x.strip() for x in candidates.split(",") if x.strip()]
    if not cands:
        raise ValueError("tupian_xuanzi candidates 不能为空")
    if len(cands) > 6:
        raise ValueError("tupian_xuanzi candidates 最多 6 个")

    ans = answer.strip()
    boxes = []
    for c in cands:
        mark = " txz-answer" if c == ans else ""
        boxes.append(f"<span class='txz-box{mark}'>{escape(c)}</span>")

    return (
        "<div class='tupian-xuanzi'>"
        f"<div class='txz-desc'>{escape(desc)}</div>"
        f"<div class='txz-cands'>{''.join(boxes)}</div>"
        "</div>"
    )


def fig_cubes(layout=None, size="5"):
    """正方体搭的立体图（等轴测）：layout='2,1;1,3' 用 ; 分行（自后向前）、, 分列（自左向右），
    数字是该位置叠放的层数（0 表示空）。至多 4 行 × 5 列、每摞 5 层。用于数一数/观察物体。"""
    if not layout:
        raise ValueError("fig_cubes 需要 layout，如 layout='2,1;1,3'")
    s = _num(size, "size")
    if s > 8:
        raise ValueError("size 不能超过 8 毫米")
    rows = []
    for ri, row in enumerate(layout.split(";")):
        cells = [c for c in row.split(",")]
        if not all(c.strip() for c in cells):
            raise ValueError(f"layout 第 {ri + 1} 行含空项：{row!r}")
        rows.append([_int(c, "layout", 0, 5) for c in cells])
    if len(rows) > 4:
        raise ValueError("layout 至多 4 行")
    ncol = len(rows[0])
    if ncol > 5 or any(len(r) != ncol for r in rows):
        raise ValueError("layout 每行列数必须相同，且至多 5 列")
    if not any(h for r in rows for h in r):
        raise ValueError("layout 至少要有一个方块")
    a = s * math.sqrt(3) / 2
    polys = []  # (depth, [(points, fill)])
    for r, row in enumerate(rows):
        for c, h in enumerate(row):
            for k in range(h):
                X, Y = (c - r) * a, (c + r) * s / 2 - (k + 1) * s
                top = [(X, Y), (X + a, Y + s / 2), (X, Y + s), (X - a, Y + s / 2)]
                left = [(X - a, Y + s / 2), (X, Y + s), (X, Y + 2 * s), (X - a, Y + 1.5 * s)]
                right = [(X, Y + s), (X + a, Y + s / 2), (X + a, Y + 1.5 * s), (X, Y + 2 * s)]
                polys.append(((r + c, k), [(top, "#fff"), (left, "#ccc"), (right, "#999")]))
    polys.sort(key=lambda p: p[0])  # 先画远的、低的
    all_pts = [pt for _, faces in polys for pts, _ in faces for pt in pts]
    minx, maxx = min(p[0] for p in all_pts) - 3, max(p[0] for p in all_pts) + 3
    miny, maxy = min(p[1] for p in all_pts) - 3, max(p[1] for p in all_pts) + 3
    body = "".join(
        f"<polygon points='{' '.join(f'{x - minx:.2f},{y - miny:.2f}' for x, y in pts)}' "
        f"fill='{fill}' stroke='#000' stroke-width='0.35' stroke-linejoin='round'/>"
        for _, faces in polys
        for pts, fill in faces
    )
    return _svg(maxx - minx, maxy - miny, body)


# ---- 展开 -----------------------------------------------------------------

DIRECTIVES = {
    "tianzige": tianzige,
    "pinyin_tianzige": pinyin_tianzige,
    "fourline": fourline,
    "workspace": workspace,
    "blank": blank,
    "fig_rect": fig_rect,
    "fig_clock": fig_clock,
    "fig_bars": fig_bars,
    "fig_ruler": fig_ruler,
    "fig_angle": fig_angle,
    "fig_grid": fig_grid,
    "fig_fraction": fig_fraction,
    "fig_numline": fig_numline,
    "fig_cubes": fig_cubes,
    "lianxian": lianxian,
    "zhaopengyou": zhaopengyou,
    "caizimi": caizimi,
    "tupian_xuanzi": tupian_xuanzi,
}
INLINE = {"pinyin_tianzige", "blank"}  # 其余为块级，前后补空行以便 Markdown 透传 HTML

_PAT = re.compile(r"(^[ \t]*)?\{\{\s*(\w+)([^{}]*)\}\}", re.MULTILINE)


def expand(text):
    """展开全文指令。未知指令名、未知参数、参数非法都抛 ValueError（带行号）。"""

    def repl(m):
        indent, name, argstr = m.group(1) or "", m.group(2), m.group(3)
        line = text.count("\n", 0, m.start()) + 1
        if name not in DIRECTIVES:
            raise ValueError(f"第 {line} 行：未知指令 {{{{{name}}}}}，可用：{', '.join(DIRECTIVES)}")
        kwargs = {}
        for tok in shlex.split(argstr):
            k, eq, v = tok.partition("=")
            if not eq:
                raise ValueError(f"第 {line} 行：参数 {tok!r} 应为 key=value")
            kwargs[k] = v
        try:
            html = DIRECTIVES[name](**kwargs)
        except TypeError as e:
            raise ValueError(f"第 {line} 行：{name} 参数错误：{e}") from None
        except ValueError as e:
            raise ValueError(f"第 {line} 行：{name}：{e}") from None
        if name in INLINE:
            return f"{indent}{html}"
        if indent:
            return f"{indent}{html}"
        return f"\n\n{html}\n\n"

    return _PAT.sub(repl, text)


CROSS_URI = _CROSS
PINYIN_URI = _PINYIN_LINES
