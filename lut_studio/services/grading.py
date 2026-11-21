"""调色参数解析与 ffmpeg 滤镜生成（一级调色 + 色轮 + 曲线 + HSL + 分离色调 + 校准）。"""

import json
import math
import os

from helper import to_ffmpeg_lut_path

from ..config import GRADING_CACHE_DIR
from ..utils import _cache_key, _clamp

CURVE_CHANNELS = ("master", "r", "g", "b")

HSL_KEYS = ("reds", "oranges", "yellows", "greens", "aquas", "blues", "purples", "magentas")
HSL_CENTERS = {"reds": 0.0, "oranges": 30.0, "yellows": 60.0, "greens": 120.0,
               "aquas": 180.0, "blues": 240.0, "purples": 280.0, "magentas": 320.0}


def _parse_curve_regions(raw):
    """曲线区域滑块：暗部 / 中间调 / 高光（-100 ~ 100）"""
    raw = raw if isinstance(raw, dict) else {}
    return {
        k: _clamp(float(raw.get(k, 0) or 0), -100, 100)
        for k in ("shadows", "midtones", "highlights")
    }


def parse_grading(data):
    """从请求中解析调色参数：白平衡/曝光/对比/饱和/锐化 + 色轮 + 曲线 + HSL + 分离色调 + 校准"""
    raw = data.get("grading") or {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            raw = {}
    if not isinstance(raw, dict):
        raw = {}
    g = {
        "temperature": _clamp(float(raw.get("temperature", 0) or 0), -100, 100),
        "tint": _clamp(float(raw.get("tint", 0) or 0), -100, 100),
        "exposure": _clamp(float(raw.get("exposure", 0) or 0), -3, 3),
        "contrast": _clamp(float(raw.get("contrast", 0) or 0), -100, 100),
        "highlights": _clamp(float(raw.get("highlights", 0) or 0), -100, 100),
        "shadows": _clamp(float(raw.get("shadows", 0) or 0), -100, 100),
        "whites": _clamp(float(raw.get("whites", 0) or 0), -100, 100),
        "blacks": _clamp(float(raw.get("blacks", 0) or 0), -100, 100),
        "saturation": _clamp(float(raw.get("saturation", 0) or 0), -100, 100),
        "vibrance": _clamp(float(raw.get("vibrance", 0) or 0), -100, 100),
        "sharpness": _clamp(float(raw.get("sharpness", 0) or 0), 0, 100),
    }
    g["curve_regions"] = _parse_curve_regions(raw.get("curve_regions"))
    for key in ("lift", "gamma", "gain"):
        w = raw.get(key) or {}
        if not isinstance(w, dict):
            w = {}
        g[key] = {
            "x": _clamp(float(w.get("x", 0) or 0), -1, 1),
            "y": _clamp(float(w.get("y", 0) or 0), -1, 1),
        }
    g["curve"] = _parse_curve(raw.get("curve"))
    g["hsl"] = _parse_hsl(raw.get("hsl"))
    sp = raw.get("split") or {}
    if not isinstance(sp, dict):
        sp = {}
    g["split"] = {
        "shadow_hue": float(sp.get("shadow_hue", 40) or 0) % 360,
        "shadow_sat": _clamp(float(sp.get("shadow_sat", 0) or 0), 0, 100),
        "highlight_hue": float(sp.get("highlight_hue", 210) or 0) % 360,
        "highlight_sat": _clamp(float(sp.get("highlight_sat", 0) or 0), 0, 100),
        "balance": _clamp(float(sp.get("balance", 0) or 0), -100, 100),
    }
    cal = raw.get("calibration") or {}
    if not isinstance(cal, dict):
        cal = {}
    g["calibration"] = {
        k: _clamp(float(cal.get(k, 0) or 0), -100, 100)
        for k in ("red_hue", "red_sat", "green_hue", "green_sat", "blue_hue", "blue_sat")
    }
    return g


def _parse_curve(raw):
    """曲线控制点 → {通道: [(x, y), ...]}；少于两点视为未启用"""
    out = {}
    raw = raw if isinstance(raw, dict) else {}
    for ch in CURVE_CHANNELS:
        pts = raw.get(ch)
        clean = []
        if isinstance(pts, list):
            for p in pts[:16]:
                if not isinstance(p, dict):
                    continue
                try:
                    x = _clamp(float(p.get("x", 0) or 0), 0, 1)
                    y = _clamp(float(p.get("y", 0) or 0), 0, 1)
                except (TypeError, ValueError):
                    continue
                clean.append((x, y))
        clean.sort()
        # 相同 x 的控制点只保留最后一个
        dedup = []
        for x, y in clean:
            if dedup and abs(dedup[-1][0] - x) < 1e-4:
                dedup[-1] = (x, y)
            else:
                dedup.append((x, y))
        out[ch] = dedup if len(dedup) >= 2 else []
    return out


def _parse_hsl(raw):
    raw = raw if isinstance(raw, dict) else {}
    out = {}
    for k in HSL_KEYS:
        w = raw.get(k)
        w = w if isinstance(w, dict) else {}
        out[k] = {
            "h": _clamp(float(w.get("h", 0) or 0), -100, 100),
            "s": _clamp(float(w.get("s", 0) or 0), -100, 100),
            "l": _clamp(float(w.get("l", 0) or 0), -100, 100),
        }
    return out


def _curve_is_linear(pts):
    return all(abs(x - y) < 0.005 for x, y in pts)


def is_neutral_grading(g):
    """调色参数是否全部为默认值（此时可以完全跳过滤镜）"""
    if not g:
        return True
    wheels_zero = all(abs(g[k]["x"]) < 0.02 and abs(g[k]["y"]) < 0.02
                      for k in ("lift", "gamma", "gain"))
    curve_used = any(pts and not _curve_is_linear(pts) for pts in g["curve"].values())
    regions_used = any(abs(v) >= 1 for v in g["curve_regions"].values())
    hsl_used = any(abs(v[k]) >= 1 for v in g["hsl"].values() for k in ("h", "s", "l"))
    split = g["split"]
    split_used = split["shadow_sat"] >= 2 or split["highlight_sat"] >= 2
    cal_used = any(abs(v) >= 1 for v in g["calibration"].values())
    tone_used = any(abs(g[k]) >= 1 for k in
                    ("highlights", "shadows", "whites", "blacks", "vibrance"))
    return (abs(g["temperature"]) < 0.5 and abs(g["tint"]) < 0.5
            and abs(g["exposure"]) < 0.01 and abs(g["contrast"]) < 0.5
            and abs(g["saturation"]) < 0.5 and g["sharpness"] < 1 and wheels_zero
            and not tone_used and not curve_used and not regions_used
            and not hsl_used and not split_used and not cal_used)


def _hsv_rgb(hue):
    """HSV(hue, 1, 1) → RGB 三元组（色相环上最饱和的颜色）"""
    h = (hue % 360.0) / 60.0
    i = int(h) % 6
    f = h - int(h)
    return [
        (1.0, f, 0.0), (1.0 - f, 1.0, 0.0), (0.0, 1.0, f),
        (0.0, 1.0 - f, 1.0), (f, 0.0, 1.0), (1.0, 0.0, 1.0 - f),
    ][i]


def _wheel_rgb(w, strength=0.35):
    """色轮坐标 (x, y) → RGB 偏移量；x 右为正、y 上为正。

    与前端色轮渐变保持一致：正上方为绿，顺时针依次为 黄 → 红 → 品红 → 蓝 → 青。
    """
    x, y = w["x"], w["y"]
    dist = math.hypot(x, y)
    if dist < 0.02:
        return (0.0, 0.0, 0.0)
    ang = math.degrees(math.atan2(x, y)) % 360.0  # 0° 在正上方，顺时针递增
    rgb = _hsv_rgb(120.0 - ang)  # 正上方(0°)对应 HSV 120°（绿）
    mean = sum(rgb) / 3.0
    amp = min(dist, 1.0) * strength
    return tuple((c - mean) * amp for c in rgb)


def _curve_points(lo, mid, hi):
    """黑/中/白三个输出锚点 → curves 控制点字符串"""
    return (f"0/{_clamp(lo, 0.0, 0.95):.4f} "
            f"0.5/{_clamp(mid, 0.02, 0.98):.4f} "
            f"1/{_clamp(hi, 0.05, 1.0):.4f}")


def _channel_curve(lift, gamma, gain):
    """单通道的 lift/gamma/gain 偏移 → curves 三点曲线"""
    lo = _clamp(lift * 0.32, 0.0, 0.30)
    mid = _clamp(0.5 + gamma * 0.35 + lift * 0.12, 0.05, 0.95)
    hi = _clamp(1.0 + gain * 0.45 + lift * 0.20, 0.55, 1.0)
    return _curve_points(lo, mid, hi)


def _curves_filter(r, g, b):
    return f"curves=r='{r}':g='{g}':b='{b}'"


def _rgb_to_hsv(r, g, b):
    mx = max(r, g, b)
    mn = min(r, g, b)
    d = mx - mn
    if mx <= 1e-9:
        return 0.0, 0.0, 0.0
    s = d / mx
    if s <= 1e-9:
        return 0.0, 0.0, mx
    if mx == r:
        h = ((g - b) / d) % 6.0
    elif mx == g:
        h = (b - r) / d + 2.0
    else:
        h = (r - g) / d + 4.0
    return h / 6.0, s, mx


def _hsv_to_rgb(h, s, v):
    if s <= 1e-9:
        return v, v, v
    h6 = (h % 1.0) * 6.0
    i = int(h6)
    f = h6 - i
    p = v * (1 - s)
    q = v * (1 - s * f)
    t = v * (1 - s * (1 - f))
    return [(v, t, p), (q, v, p), (p, v, t), (p, q, v), (t, p, v), (v, p, q)][i % 6]


def _hue_dist(a, b):
    d = abs(a - b) % 360.0
    return d if d <= 180 else 360 - d


def _hsl_lut(hsl, vibrance=0, size=25):
    """按 8 个色相区间做 HSL 微调，并叠加自然饱和度，生成 3D LUT（.cube）并缓存。

    ffmpeg 的 huesaturation 只能对所有色相做统一偏移，无法按颜色区分，
    也没有自然饱和度，因此这里用 Python 生成一张 3D LUT，再交给 lut3d 应用。
    """
    # 量化到 5 的倍数，避免拖动滑杆时生成大量近似 LUT
    q = {k: {kk: int(round(v[kk] / 5.0) * 5) for kk in ("h", "s", "l")}
         for k, v in hsl.items()}
    active = [(HSL_CENTERS[k], q[k]) for k in HSL_KEYS
              if abs(q[k]["h"]) >= 1 or abs(q[k]["s"]) >= 1 or abs(q[k]["l"]) >= 1]
    vib = int(round(vibrance / 5.0) * 5) / 100.0
    if not active and abs(vib) < 0.01:
        return None
    key = _cache_key("hsl", json.dumps(q, sort_keys=True), vib, size)
    out = os.path.join(GRADING_CACHE_DIR, key + ".cube")
    if os.path.isfile(out):
        return out

    step = 1.0 / (size - 1)
    rows = ["LUT_3D_SIZE %d" % size, "DOMAIN_MIN 0 0 0", "DOMAIN_MAX 1 1 1"]
    for bi in range(size):
        b = bi * step
        for gi in range(size):
            g = gi * step
            for ri in range(size):
                r = ri * step
                h, s, v = _rgb_to_hsv(r, g, b)
                if s > 0.01:
                    wsum = dh = ds = dl = 0.0
                    hue_deg = h * 360.0
                    for center, adj in active:
                        w = 1.0 - _hue_dist(hue_deg, center) / 45.0
                        if w <= 0:
                            continue
                        wsum += w
                        dh += w * adj["h"] * 0.30      # ±100 → ±30°
                        ds += w * adj["s"] / 100.0
                        dl += w * adj["l"] / 100.0
                    if wsum > 0:
                        h = (h + (dh / wsum) / 360.0) % 1.0
                        s = _clamp(s * (1.0 + ds / wsum), 0.0, 1.0)
                        v = _clamp(v * (1.0 + dl / wsum * 0.6), 0.0, 1.0)
                    if abs(vib) >= 0.01:
                        # 自然饱和度：低饱和像素提升更多，高饱和像素基本不动
                        if vib > 0:
                            s = _clamp(s + vib * 0.5 * (1.0 - s), 0.0, 1.0)
                        else:
                            s = _clamp(s * (1.0 + vib * 0.6), 0.0, 1.0)
                rr, gg, bb = _hsv_to_rgb(h, s, v)
                rows.append(f"{rr:.6f} {gg:.6f} {bb:.6f}")

    tmp = out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("\n".join(rows) + "\n")
    os.replace(tmp, out)
    return out


def _tonal_curve_filter(blacks=0, shadows=0, midtones=0, highlights=0, whites=0):
    """色调区域 → master 曲线：黑色 / 阴影 / 中间调 / 高光 / 白色"""
    if all(abs(v) < 1 for v in (blacks, shadows, midtones, highlights, whites)):
        return None
    xs = (0.0, 0.2, 0.5, 0.8, 0.92, 1.0)
    ys = [
        _clamp(blacks / 100.0 * 0.12, -0.14, 0.18),
        _clamp(0.2 + shadows / 100.0 * 0.15, 0.02, 0.42),
        _clamp(0.5 + midtones / 100.0 * 0.14, 0.25, 0.75),
        _clamp(0.8 + highlights / 100.0 * 0.16, 0.5, 0.99),
        _clamp(0.92 + whites / 100.0 * 0.08, 0.7, 1.0),
        1.0,
    ]
    ys[0] = _clamp(ys[0], 0.0, 0.98)
    # 保证曲线单调递增，避免 ffmpeg curves 报错
    for i in range(1, len(ys)):
        ys[i] = max(ys[i], ys[i - 1] + 0.005)
    ys[-1] = _clamp(ys[-1], 0.0, 1.0)
    coords = " ".join(f"{x:.4f}/{y:.4f}" for x, y in zip(xs, ys))
    return f"curves=master='{coords}'"


def _tone_curve_filter(curve):
    """用户色调曲线 → curves 滤镜（支持主通道与 R/G/B）"""
    parts = []
    for ch in CURVE_CHANNELS:
        pts = curve.get(ch) or []
        if len(pts) < 2 or _curve_is_linear(pts):
            continue
        name = "master" if ch == "master" else ch
        coords = " ".join(f"{x:.4f}/{y:.4f}" for x, y in pts)
        parts.append(f"{name}='{coords}'")
    return "curves=" + ":".join(parts) if parts else None


def _split_toning_filter(split):
    """分离色调：暗部/高光分别按色相上色，balance 移动交界点"""
    ss = split["shadow_sat"] / 100.0
    hs = split["highlight_sat"] / 100.0
    if ss < 0.02 and hs < 0.02:
        return None
    sc = _hsv_rgb(split["shadow_hue"])
    hc = _hsv_rgb(split["highlight_hue"])
    mid = _clamp(0.5 + split["balance"] / 100.0 * 0.35, 0.2, 0.8)
    chrones = []
    for i in range(3):
        lo = sum(sc) / 3.0
        hi = sum(hc) / 3.0
        y_lo = _clamp((sc[i] - lo) * ss * 0.45, 0.0, 0.45)
        y_hi = _clamp(1.0 + (hc[i] - hi) * hs * 0.45, 0.55, 1.0)
        chrones.append(f"0/{y_lo:.4f} {mid:.4f}/0.5000 1/{y_hi:.4f}")
    return f"curves=r='{chrones[0]}':g='{chrones[1]}':b='{chrones[2]}'"


def _calibration_filter(cal):
    """校准：用 3x3 通道矩阵近似主色相旋转与饱和度增益"""
    if all(abs(v) < 1.0 for v in cal.values()):
        return None
    m = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    # (通道下标, 顺时针方向的下一个通道, 上一个通道, 色相, 饱和度)
    for idx, nxt, prv, hue, sat in (
        (0, 1, 2, cal["red_hue"], cal["red_sat"]),
        (1, 2, 0, cal["green_hue"], cal["green_sat"]),
        (2, 0, 1, cal["blue_hue"], cal["blue_sat"]),
    ):
        h = hue / 100.0 * 0.25
        s = sat / 100.0
        m[idx][idx] += s * 0.35
        m[idx][nxt] += h * 0.35
        m[prv][idx] -= h * 0.15
    names = ("rr", "rg", "rb", "gr", "gg", "gb", "br", "bg", "bb")
    vals = [m[i][j] for i in range(3) for j in range(3)]
    return "colorchannelmixer=" + ":".join(f"{n}={v:.4f}" for n, v in zip(names, vals))


def grading_steps(g, sharpen=True):
    """返回 (LUT 前滤镜, LUT 后滤镜)：白平衡 → 曝光 → 对比/饱和 → 高光/阴影/白色/黑色
    → 色轮 → 校准 → HSL/自然饱和度 → 曲线 → 分离色调 → LUT → 锐化

    注意：ffmpeg 9.0.2 的 colorbalance 滤镜完全不生效（RGB/YUV 均无输出变化），
    因此色调与色轮改用 curves 的三锚点曲线实现。
    """
    pre, post = [], []
    if not g:
        return pre, post
    if abs(g["temperature"]) >= 0.5:
        # colortemperature 的 temperature 越低画面越暖，因此正值（向右拖）要往下调色温
        kelvin = int(round(6500 - g["temperature"] * 25))  # -100 → 9000K（冷），+100 → 4000K（暖）
        pre.append(f"colortemperature=temperature={_clamp(kelvin, 1000, 40000)}:mix=1")
    if abs(g["tint"]) >= 0.5:
        # 正值偏品红：绿中间调下压、蓝中间调上提
        t = g["tint"] / 100 * 0.12
        pre.append(_curves_filter(
            _curve_points(0, 0.5, 1),
            _curve_points(0, 0.5 - t, 1),
            _curve_points(0, 0.5 + t, 1),
        ))
    if abs(g["exposure"]) >= 0.01:
        pre.append(f"exposure=exposure={g['exposure']:.2f}")
    if abs(g["contrast"]) >= 0.5 or abs(g["saturation"]) >= 0.5:
        c = 1 + g["contrast"] / 200.0
        s = 1 + g["saturation"] / 100.0
        pre.append(f"eq=contrast={c:.3f}:saturation={s:.3f}")
    # 一级调色：高光 / 阴影 / 白色 / 黑色（区域色调曲线）
    tone_filter = _tonal_curve_filter(g["blacks"], g["shadows"], 0,
                                      g["highlights"], g["whites"])
    if tone_filter:
        pre.append(tone_filter)
    lift = _wheel_rgb(g["lift"])
    gam = _wheel_rgb(g["gamma"])
    gain = _wheel_rgb(g["gain"])
    if any(abs(v) > 0.001 for v in lift + gam + gain):
        pre.append(_curves_filter(
            _channel_curve(lift[0], gam[0], gain[0]),
            _channel_curve(lift[1], gam[1], gain[1]),
            _channel_curve(lift[2], gam[2], gain[2]),
        ))
    cal_filter = _calibration_filter(g["calibration"])
    if cal_filter:
        pre.append(cal_filter)
    reg = g["curve_regions"]
    region_filter = _tonal_curve_filter(0, reg["shadows"], reg["midtones"],
                                        reg["highlights"], 0)
    if region_filter:
        pre.append(region_filter)
    hsl_lut = _hsl_lut(g["hsl"], g["vibrance"])
    if hsl_lut:
        pre.append(f"lut3d={to_ffmpeg_lut_path(hsl_lut)}")
    curve_filter = _tone_curve_filter(g["curve"])
    if curve_filter:
        pre.append(curve_filter)
    split_filter = _split_toning_filter(g["split"])
    if split_filter:
        pre.append(split_filter)
    if sharpen and g["sharpness"] >= 1:
        post.append(f"unsharp=5:5:{g['sharpness'] / 50:.2f}")
    return pre, post
