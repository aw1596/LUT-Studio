"""蒙版：解析组合树、生成灰度图（PGM）、计算包围盒。"""

import json
import math
import os

try:
    import numpy as np
except ImportError:  # 画笔 / 钢笔蒙版需要 numpy
    np = None

from ..config import MASK_CACHE_DIR
from ..utils import _cache_key, _clamp
from .grading import parse_grading, is_neutral_grading

SHAPES = ("linear", "radial", "rect", "brush", "pen")
OPS = ("add", "subtract", "intersect")
CROP_AREA_LIMIT = 0.55  # 蒙版包围盒占画面比例低于此值时，只在该区域做局部调色


def _parse_points(raw, limit=2000):
    """归一化点列表 → [{'x':..,'y':..}]"""
    pts = []
    if isinstance(raw, list):
        for p in raw[:limit]:
            if not isinstance(p, dict):
                continue
            try:
                pts.append({"x": _clamp(float(p.get("x")), 0, 1),
                            "y": _clamp(float(p.get("y")), 0, 1)})
            except (TypeError, ValueError):
                continue
    return pts


def parse_node(raw, index=0):
    """解析组合树中的一个原始选区节点"""
    if not isinstance(raw, dict):
        raw = {}
    shape = raw.get("shape")
    if shape not in SHAPES:
        shape = "radial"
    op = raw.get("op")
    if op not in OPS:
        op = "add"
    strokes = []
    raw_strokes = raw.get("strokes")
    if isinstance(raw_strokes, list):
        for s in raw_strokes[:64]:
            pts = _parse_points(s, 2000)
            if pts:
                strokes.append(pts)
    return {
        "id": str(raw.get("id") or "n%d" % (index + 1))[:24],
        "name": str(raw.get("name") or "选区 %d" % (index + 1))[:40],
        "op": op,
        "enabled": raw.get("enabled", True) is not False,
        "shape": shape,
        "cx": _clamp(float(raw.get("cx", 0.5) or 0), 0, 1),
        "cy": _clamp(float(raw.get("cy", 0.5) or 0), 0, 1),
        "angle": float(raw.get("angle", 0) or 0),
        "size": _clamp(float(raw.get("size", 0.35) or 0), 0.02, 2.0),
        "aspect": _clamp(float(raw.get("aspect", 0.6) or 0), 0.05, 3.0),
        "feather": _clamp(float(raw.get("feather", 0.25) or 0), 0.01, 1.0),
        "invert": bool(raw.get("invert")),
        "brush_size": _clamp(float(raw.get("brush_size", 0.12) or 0), 0.01, 0.5),
        "strokes": strokes,
        "pen_points": _parse_points(raw.get("pen_points"), 256),
    }


def parse_mask(data):
    """解析单个蒙版；组合树新数据带 nodes，旧数据以顶层形状作为唯一节点"""
    raw = data.get("mask") or {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            raw = {}
    if not isinstance(raw, dict):
        raw = {}
    raw_nodes = raw.get("nodes")
    if isinstance(raw_nodes, list) and raw_nodes:
        nodes = [parse_node(n, i) for i, n in enumerate(raw_nodes[:16])]
        invert_all = bool(raw.get("invert"))
    else:
        nodes = [parse_node(raw, 0)]
        invert_all = False  # 旧数据的反转已挂在唯一节点上，避免二次反转
    mask = dict(nodes[0])  # 顶层保留首个节点几何，兼容旧调用
    mask.update({
        "enabled": bool(raw.get("enabled")),
        "invert": invert_all,
        "nodes": nodes,
    })
    return mask


def _box_blur(a, radius, axis):
    """沿单个轴做 box 模糊（累计和实现，零填充边缘）"""
    if radius < 1:
        return a
    pad = [(radius, radius) if i == axis else (0, 0) for i in range(a.ndim)]
    p = np.pad(a, pad, mode="edge")
    c = np.cumsum(p, axis=axis, dtype=np.float32)
    zero_shape = list(c.shape)
    zero_shape[axis] = 1
    c = np.concatenate([np.zeros(zero_shape, dtype=np.float32), c], axis=axis)
    n = 2 * radius + 1
    hi = np.take(c, np.arange(n, c.shape[axis]), axis=axis)
    lo = np.take(c, np.arange(0, c.shape[axis] - n), axis=axis)
    return (hi - lo) / n


def _blur2d(a, radius, passes=3):
    for _ in range(passes):
        a = _box_blur(a, radius, 1)
        a = _box_blur(a, radius, 0)
    return a


def _fill_polygon(pts, w, h):
    """扫描线填充多边形（pts 为像素坐标）"""
    out = np.zeros((h, w), dtype=np.float32)
    n = len(pts)
    for y in range(h):
        yc = y + 0.5
        xs = []
        for i in range(n):
            x1, y1 = pts[i]
            x2, y2 = pts[(i + 1) % n]
            if (y1 <= yc < y2) or (y2 <= yc < y1):
                xs.append(x1 + (x2 - x1) * (yc - y1) / (y2 - y1))
        if len(xs) < 2:
            continue
        xs.sort()
        for a, b in zip(xs[0::2], xs[1::2]):
            ia = max(0, int(math.ceil(a - 0.5)))
            ib = min(w, int(math.ceil(b - 0.5)))
            if ia < ib:
                out[y, ia:ib] = 1.0
    return out


def _drawn_mask_array(m, w, h):
    """画笔 / 钢笔蒙版 → 灰度数组（0~1）"""
    if np is None:
        raise RuntimeError("画笔 / 钢笔蒙版需要 numpy，请先执行 pip install numpy")
    mask = np.zeros((h, w), dtype=np.float32)
    if m["shape"] == "brush":
        radius = max(1.0, m["brush_size"] * min(w, h))
        inner = radius * (1.0 - _clamp(m["feather"], 0.0, 1.0) * 0.95)
        falloff = max(1.0, radius - inner)
        gap = max(1.0, radius * 0.25)
        for stroke in m["strokes"]:
            pts = [(p["x"] * w, p["y"] * h) for p in stroke]
            if not pts:
                continue
            if len(pts) == 1:
                pts = pts * 2
            stamps = []
            for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
                dist = math.hypot(x2 - x1, y2 - y1)
                steps = max(1, int(dist / gap))
                for i in range(steps + 1):
                    t = i / float(steps)
                    stamps.append((x1 + (x2 - x1) * t, y1 + (y2 - y1) * t))
            for sx, sy in stamps:
                x0 = max(0, int(sx - radius) - 1)
                x1 = min(w, int(sx + radius) + 2)
                y0 = max(0, int(sy - radius) - 1)
                y1 = min(h, int(sy + radius) + 2)
                if x0 >= x1 or y0 >= y1:
                    continue
                yy = np.arange(y0, y1, dtype=np.float32)[:, None]
                xx = np.arange(x0, x1, dtype=np.float32)[None, :]
                d = np.sqrt((xx - sx) ** 2 + (yy - sy) ** 2)
                a = np.clip((radius - d) / falloff, 0.0, 1.0)
                region = mask[y0:y1, x0:x1]
                np.maximum(region, a, out=region)
    else:  # pen
        pts = [(p["x"] * w, p["y"] * h) for p in m["pen_points"]]
        if len(pts) >= 3:
            mask = _fill_polygon(pts, w, h)
            r = int(round(m["feather"] * min(w, h) * 0.25))
            if r >= 1:
                mask = _blur2d(mask, r)
    return mask


def _geom_mask_array(node, w, h):
    """单个几何节点 → 灰度数组（0~1），与旧 geq 表达式语义一致"""
    if node["shape"] in ("brush", "pen"):
        return _drawn_mask_array(node, w, h)
    x = (np.arange(w, dtype=np.float32) + 0.5) / max(1, w)
    y = (np.arange(h, dtype=np.float32) + 0.5) / max(1, h)
    dx = x[None, :] - node["cx"]
    dy = y[:, None] - node["cy"]
    size, feather = node["size"], node["feather"]
    if node["shape"] == "linear":
        a = math.radians(node["angle"])
        v = 0.5 + (dx * math.cos(a) + dy * math.sin(a)) / size
    elif node["shape"] == "radial":
        ratio = (h / w) if w else 1.0
        v = (size - np.sqrt(dx * dx + (dy * ratio) ** 2)) / feather
    else:  # rect：高宽比按画面像素计算，并支持旋转（画面上是真实的角度）
        ratio = (h / w) if w else 1.0
        a = math.radians(node["angle"])
        ca, sa = math.cos(a), math.sin(a)
        ux = dx * ca + dy * ratio * sa
        uy = dy * ratio * ca - dx * sa
        v = (1.0 - np.maximum(np.abs(ux) / size, np.abs(uy) / (size * node["aspect"]))) / feather
    return np.clip(v, 0.0, 1.0).astype(np.float32)


def _nodes_mask_array(mask, w, h):
    """按组合树求值：添加=并集、减去=差集、交叉=交集，最后应用蒙版级反转"""
    acc = None
    for node in mask.get("nodes") or []:
        if not node.get("enabled", True):
            continue
        a = _geom_mask_array(node, w, h)
        if node.get("invert"):
            a = 1.0 - a
        if acc is None:
            acc = a
        elif node["op"] == "subtract":
            acc = acc * (1.0 - a)
        elif node["op"] == "intersect":
            acc = acc * a
        else:
            acc = np.maximum(acc, a)
    if acc is None:
        acc = np.zeros((h, w), dtype=np.float32)
    if mask.get("invert"):
        acc = 1.0 - acc
    return acc.astype(np.float32)


def _write_pgm(path, arr):
    """灰度数组 → PGM（ffmpeg 可直接作为图片输入读取）"""
    h, w = arr.shape
    data = (np.clip(arr, 0.0, 1.0) * 255.0).astype(np.uint8)
    with open(path, "wb") as f:
        f.write(b"P5\n%d %d\n255\n" % (w, h))
        f.write(data.tobytes())


def ensure_mask_png(m, w, h):
    """按组合树生成灰度蒙版图（PGM）并缓存；节点运算结果即为最终选区"""
    if np is None:
        raise RuntimeError("蒙版需要 numpy，请先执行 pip install numpy")
    geo = {"nodes": m.get("nodes"), "invert": bool(m.get("invert"))}
    out = os.path.join(MASK_CACHE_DIR,
                       _cache_key("mask", json.dumps(geo, sort_keys=True), w, h) + ".pgm")
    if os.path.isfile(out):
        return out
    arr = _nodes_mask_array(m, w, h)
    tmp = out + ".tmp"
    _write_pgm(tmp, arr)
    os.replace(tmp, out)
    return out


def mask_bbox(pgm_path):
    """蒙版有效像素包围盒 → (x, y, w, h, 面积占比)

    逐个蒙版做整帧调色的开销最大；知道蒙版只覆盖画面一小块时，
    只对这块区域跑调色滤镜，再把结果叠回原位，结果完全一致但快很多。
    包围盒结果写在 PGM 旁边的 .json 里，避免每次重新扫描大图。
    """
    side = pgm_path + ".bbox2.json"
    try:
        with open(side, "r", encoding="utf-8") as f:
            data = json.load(f)
        box = data["box"]
        return (tuple(box) if box else None), float(data["area"])
    except (OSError, ValueError, TypeError, KeyError):
        pass
    if np is None:
        return None, 1.0
    box, area = None, 1.0
    try:
        with open(pgm_path, "rb") as f:
            f.read(2)
            f.readline()
            w, h = [int(v) for v in f.readline().split()[:2]]
            f.readline()
            arr = np.frombuffer(f.read(), dtype=np.uint8).reshape(h, w)
    except Exception:
        return None, 1.0
    ys, xs = np.where(arr > 2)
    count = len(xs)  # 非有效像素视为透明，bbox 取有效像素外接矩形
    if count and count < w * h:
        pad = 2
        x0 = (max(0, int(xs.min()) - pad) // 2) * 2
        y0 = (max(0, int(ys.min()) - pad) // 2) * 2
        x1 = min(w, ((int(xs.max()) + 1 + pad + 1) // 2) * 2)
        y1 = min(h, ((int(ys.max()) + 1 + pad + 1) // 2) * 2)
        bw, bh = x1 - x0, y1 - y0
        # 宽高取偶数：部分滤镜（如 colortemperature）会在内部转成 4:2:0，奇数尺寸会丢一行
        bw -= bw % 2
        bh -= bh % 2
        if bw >= 2 and bh >= 2:
            box = [x0, y0, bw, bh]
            area = bw * bh / float(w * h)
    try:
        with open(side, "w", encoding="utf-8") as f:
            json.dump({"box": box, "area": area}, f)
    except OSError:
        pass
    return (tuple(box) if box else None), area


def ensure_mask_layers(layers, w, h):
    """为每层蒙版准备灰度图与包围盒（渲染用）"""
    for layer in layers:
        png = ensure_mask_png(layer["mask"], w, h)
        layer["png"] = png
        layer["bbox"], layer["bbox_area"] = mask_bbox(png)


def parse_masks(data):
    """解析多蒙版列表；每个蒙版带自己的完整调色参数"""
    raw = data.get("masks")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            raw = []
    items = raw if isinstance(raw, list) else []
    if not items:
        single = data.get("mask")  # 兼容旧的单蒙版调用
        if single:
            items = [single]
    out = []
    for i, m in enumerate(items[:16]):
        if isinstance(m, str):
            try:
                m = json.loads(m)
            except ValueError:
                continue
        if not isinstance(m, dict):
            continue
        mask = parse_mask({"mask": m})
        mask["grading"] = parse_grading({"grading": m.get("grading")})
        mask["name"] = str(m.get("name") or "蒙版 %d" % (i + 1))[:40]
        out.append(mask)
    return out


def active_masks(masks):
    """真正需要参与渲染的蒙版：已启用且调色参数非中性"""
    return [m for m in (masks or [])
            if m["enabled"] and not is_neutral_grading(m["grading"])]
