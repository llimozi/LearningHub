# -*- coding: utf-8 -*-
"""tag_notes.py —— v1.8 模块A1: 笔记标签批量补录(纯标准库)

解决什么: daily 笔记缺 tags: 行 → 概念全部落入「未分类」, 稳固度聚合失效。

用法:
  python tag_notes.py                       # 预览推荐 -> 交互确认 y 才写入
  python tag_notes.py --dry-run             # 只预览, 绝不写盘
  python tag_notes.py --yes                 # 预览后直接写入(免确认, 供自动化)
  python tag_notes.py --tag=agent,mcp --files=2026-08-22.md   # 手动指定模式

为什么插入位置是标题行之后: analyzer.analyze_note 只在笔记【前4行】里找
tags: 行; 为什么格式是 "tags: a, b" 而非 "#a": analyzer 按逗号切分,
带 # 会把脏字符带进标签体系。
已有 tags: 行的文件一律跳过(绝不覆盖用户手写内容)。
写入后: 删除 analysis.json 对应日期缓存 -> update_analysis 重析 ->
invalidate_cache, 三级联动保证洞察面板当次可见。
"""
import io
import json
import os
import re
import sys
from collections import Counter

BASE = os.path.dirname(os.path.abspath(__file__))
NOTES_DIR = os.path.join(BASE, "daily")          # 笔记真实存放处(daily/*.md)
KW_PATH = os.path.join(BASE, "tag_keywords.json")

DEFAULT_KEYWORDS = {
    "agent":    ["agent", "智能体", "多智能体", "mcp", "编排", "function calling",
                  "工具调用", "functioncalling"],
    "python":   ["python", "pytest", "tkinter", "pyinstaller", "脚本", "pip"],
    "项目工程": ["打包", "架构", "readme", "启动脚本", "交付", "冒烟", "测试",
                 "重构", "部署", "常驻"],
    "调研":     ["trending", "github", "调研", "种子资源", "sources", "星标", "仓库"],
    "复习自测": ["复习", "自测", "遗忘", "sm-2", "口述", "变式题"],
    "复盘":     ["复盘", "周报", "周复盘", "反思", "五问"],
}


def load_keywords():
    """读映射表; 不存在则落一份默认值(用户可直接编辑该 JSON 调整推荐行为)。"""
    if not os.path.exists(KW_PATH):
        with open(KW_PATH, "w", encoding="utf-8-sig") as f:
            json.dump(DEFAULT_KEYWORDS, f, ensure_ascii=False, indent=2)
        return DEFAULT_KEYWORDS
    with open(KW_PATH, encoding="utf-8-sig") as f:
        data = json.load(f)
    return data if isinstance(data, dict) else dict(DEFAULT_KEYWORDS)


def recommend(text, mapping, topn=3):
    """统计各标签命中关键词次数, 返回 [(tag, hits)] 按 hits 降序, 最多 topn 个。
    为什么用词频而非布尔: 一篇讲透某个领域的笔记应更强烈地倾向该领域。"""
    low = text.lower()
    scored = []
    for tag, words in mapping.items():
        hits = sum(low.count(str(w).lower()) for w in words)
        if hits > 0:
            scored.append((tag, hits))
    scored.sort(key=lambda x: -x[1])
    return scored[:topn]


def has_tags_line(head_lines):
    """前4行内是否已存在 tags: 行(analyzer 的解析窗口与此一致)。"""
    return any(re.match(r"tagss*:", ln.strip(), re.I) for ln in head_lines)


def collect_targets(mapping, force_tags=None, only_files=None):
    """返回 [(path, [tags])] 待写清单。force_tags 时只处理指定文件。"""
    out = []
    for name in sorted(os.listdir(NOTES_DIR)):
        if not name.endswith(".md"):
            continue
        if only_files and name not in only_files:
            continue
        p = os.path.join(NOTES_DIR, name)
        with open(p, encoding="utf-8") as f:
            lines = f.read().split("\n")
        head = lines[:4]
        if has_tags_line(head):
            continue                                  # 已有标签: 绝不覆盖
        if force_tags:
            out.append((p, list(force_tags)))
            continue
        text = "\n".join(lines[:40])                  # 前40行足够代表主题
        rec = recommend(text, mapping)
        if rec:
            out.append((p, [t for t, _ in rec]))
    return out


def refresh_caches(paths):
    """三级联动: 删 analysis 旧键 -> 重析 -> 失效洞察缓存。为什么删键:
    update_analysis 是增量式(只析缺失日期), 改动过的旧日期必须踢掉才会重析。"""
    try:
        apath = os.path.join(NOTES_DIR, "analysis.json")
        notes = {}
        if os.path.exists(apath):
            with open(apath, encoding="utf-8-sig") as f:
                notes = json.load(f).get("notes", {})
        for p in paths:
            ds = os.path.splitext(os.path.basename(p))[0]
            notes.pop(ds, None)
        with open(apath, "w", encoding="utf-8-sig") as f:
            json.dump({"notes": notes}, f, ensure_ascii=False)
        import analyzer
        analyzer.update_analysis(BASE)
    except Exception as e:                            # 分析层失败不阻断标签写入本身
        print("[warn] analysis refresh skipped:", str(e)[:80])
    try:
        import analytics
        analytics.invalidate_cache(BASE)
    except Exception:
        pass


def main(argv):
    dry = "--dry-run" in argv
    yes = "--yes" in argv or dry is False and "--no-ask" in argv
    force_tags, only_files = None, None
    for a in argv:
        if a.startswith("--tag="):
            force_tags = [x.strip() for x in a.split("=", 1)[1].split(",") if x.strip()]
        if a.startswith("--files="):
            only_files = {x.strip() for x in a.split("=", 1)[1].split(",") if x.strip()}
    mapping = load_keywords()
    targets = collect_targets(mapping, force_tags, only_files)

    if not targets:
        print("没有需要补标签的笔记(全部已有 tags 或无命中)。")
        return 0

    print("=" * 46)
    print("标签补录预览" + ("(dry-run, 不写入)" if dry else ""))
    print("=" * 46)
    for p, tags in targets:
        print(" ", os.path.basename(p), "->", "tags:", ", ".join(tags))
    if dry:
        print("\ndry-run 结束, 未写入任何文件。")
        return 0
    if not yes:
        ans = input("\n确认写入以上标签? (y/N) ").strip().lower()
        if ans != "y":
            print("已取消, 未写入。")
            return 0
    done_paths = []
    for p, tags in targets:
        with open(p, encoding="utf-8") as f:
            content = f.read()
        lines = content.split("\n")
        insert_at = 1 if lines and lines[0].startswith("#") else 0   # 标题行后 = 保证落进前4行窗口
        lines.insert(insert_at, "tags: " + ", ".join(tags))
        with open(p, "w", encoding="utf-8-sig") as f:
            f.write("\n".join(lines))
        done_paths.append(p)
        print("[written]", os.path.basename(p), "<-", ", ".join(tags))
    refresh_caches(done_paths)
    print("\n完成:", len(done_paths), "个文件; analysis 与洞察缓存已刷新。")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
