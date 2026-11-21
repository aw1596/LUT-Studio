"""LUT 目录扫描与显示名。"""

import os

from ..config import CREATIVE_LUTS_DIR, LOG_STYLE_LUTS_DIR, LUTS_DIR, RESTORE_LUTS_DIR

LUT_DISPLAY_NAMES = {
    "DJI DLogM To Rec.709": "DJI D-Log-M → Rec.709",
    "DJI OSMO Pocket 4 D-Log to Rec.709": "DJI Pocket 4 D-Log → Rec.709",
    "DJI OSMO Pocket 4P D-Log2 to Rec.709": "DJI Pocket 4P D-Log2 → Rec.709",
    "Apple Log To Rec.709": "Apple Log → Rec.709",
    "Apple Log To Rec.709 Fix": "Apple Log → Rec.709 (Fix)",
    "Apple Log2 To Rec.709": "Apple Log 2 → Rec.709",
    "O Log To Rec.709": "O-Log → Rec.709",
    "O Log2 To Rec709": "O-Log 2 → Rec.709",
    "ViVO Log To Rec.709": "ViVO Log → Rec.709",
}


def lut_display_name(filename):
    # 兼容被重复改名成 xxx.cube.cube 的文件：剥掉所有 .cube 后缀再显示
    stem = filename
    while stem.lower().endswith('.cube'):
        stem = stem[:-5]
    return LUT_DISPLAY_NAMES.get(stem, stem)


def _scan_lut_dir(directory, kind):
    """扫描目录里的 .cube；新增文件无需改代码，刷新页面即可显示"""
    items = []
    if not os.path.isdir(directory):
        return items
    for name in sorted(os.listdir(directory)):
        if name.lower().endswith('.cube'):
            items.append({"name": lut_display_name(name),
                          "path": os.path.join(directory, name),
                          "kind": kind})
    # 还原目录把 DJI 的 LUT 排在最前，作为默认选项（本工具主要面向 Osmo 素材）
    if kind == 'restore':
        items.sort(key=lambda it: (0 if os.path.basename(it["path"]).startswith("DJI") else 1, it["name"]))
    return items


def scan_all_luts():
    """restore 目录优先；luts/ 根目录保留兼容旧文件，一并按个性化处理"""
    return (_scan_lut_dir(RESTORE_LUTS_DIR, 'restore')
            + _scan_lut_dir(LOG_STYLE_LUTS_DIR, 'log')
            + _scan_lut_dir(CREATIVE_LUTS_DIR, 'creative')
            + _scan_lut_dir(LUTS_DIR, 'creative'))
