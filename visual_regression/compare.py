# -*- coding: utf-8 -*-
"""visual_regression/compare.py —— 像素级对比（Pillow，非文件大小比较）。

输出：Total Pixels / Changed Pixels / Changed Ratio + diff 图（变化区域红描）。
"""
import os

from PIL import Image, ImageChops

import config


def _pixel_diff_count(img_a, img_b, threshold=config.PIXEL_DIFF_THRESHOLD):
    """逐像素比较，返回变化像素数（任一通道差 ≥ threshold 即计为变化）。"""
    assert img_a.size == img_b.size, "尺寸不一致: %s vs %s" % (img_a.size, img_b.size)
    a = img_a.convert("RGB")
    b = img_b.convert("RGB")
    diff = ImageChops.difference(a, b)
    # 任一通道 > threshold → 变化像素
    r, g, bl = diff.split()
    mask = r.point(lambda v: 255 if v > threshold else 0)
    mask = ImageChops.lighter(mask, g.point(lambda v: 255 if v > threshold else 0))
    mask = ImageChops.lighter(mask, bl.point(lambda v: 255 if v > threshold else 0))
    changed = sum(1 for px in mask.getdata() if px == 255)
    return changed


def make_diff_image(img_a, img_b, out_path, threshold=config.PIXEL_DIFF_THRESHOLD):
    """生成 diff 图：变化区域用红色高亮，便于人工定位。"""
    a = img_a.convert("RGB")
    b = img_b.convert("RGB")
    diff = ImageChops.difference(a, b)
    r, g, bl = diff.split()
    mask = r.point(lambda v: 255 if v > threshold else 0)
    mask = ImageChops.lighter(mask, g.point(lambda v: 255 if v > threshold else 0))
    mask = ImageChops.lighter(mask, bl.point(lambda v: 255 if v > threshold else 0))
    # 变化区域涂红
    red = Image.new("RGB", a.size, (220, 38, 38))
    composite = Image.composite(red, b, mask)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    composite.save(out_path)
    return out_path


def compare_images(path_a, path_b, diff_out=None):
    """比较两张图。返回 dict: {total, changed, ratio, dims}"""
    img_a = Image.open(path_a)
    img_b = Image.open(path_b)
    dims = img_a.size
    changed = _pixel_diff_count(img_a, img_b)
    total = dims[0] * dims[1]
    ratio = changed / total if total else 1.0
    if diff_out and changed:
        make_diff_image(img_a, img_b, diff_out)
    return {
        "total": total,
        "changed": changed,
        "ratio": ratio,
        "dims": "%dx%d" % dims,
    }


def compare_rounds(round_paths):
    """比较同一组合的 3 轮截图（r1 vs r2, r2 vs r3, r1 vs r3）。
    round_paths: 有序路径列表。返回 {pair: result, max_ratio, stable}"""
    results = {}
    max_ratio = 0.0
    for i in range(len(round_paths)):
        for j in range(i + 1, len(round_paths)):
            pair = "r%d-vs-r%d" % (i + 1, j + 1)
            res = compare_images(round_paths[i], round_paths[j])
            results[pair] = res
            max_ratio = max(max_ratio, res["ratio"])
    stable = max_ratio <= config.STABILITY_THRESHOLD
    return {"pairs": results, "max_ratio": max_ratio, "stable": stable}


def main():
    """CLI：python compare.py <imgA> <imgB> [diffOut]"""
    import sys
    if len(sys.argv) < 3:
        print("用法: python compare.py <imgA> <imgB> [diffOut.png]")
        return
    diff = sys.argv[3] if len(sys.argv) > 3 else None
    res = compare_images(sys.argv[1], sys.argv[2], diff)
    print("尺寸: %s  总像素: %d  变化像素: %d  变化比例: %.4f%%" % (
        res["dims"], res["total"], res["changed"], res["ratio"] * 100))
    if diff:
        print("diff 图: %s" % diff)


if __name__ == "__main__":
    main()
