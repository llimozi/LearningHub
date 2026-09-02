# -*- coding: utf-8 -*-
"""normalize.py —— 知识概念归一化层 (Phase D-B · 纯标准库 · 确定性)

定位: 在 analyzer 的词频抽取之外, 提供一层「质量优先」的概念归一化。
不改写 analyzer, 不迁移/清空现有知识, 不删旧概念; 仅在调用方显式启用时,
把笔记中的高质量信号(tags > 已知技术短语 > 现有 concept 候选)转成
{concept(稳定键), label(人类可读名)} 列表。

设计契约:
  - 确定性、可复现: 无随机、无 LLM、无网络;
  - 向后兼容: 归一化默认关闭, 开启时旧行为不变;
  - 不激进合并同义词: 仅对可安全证明等价(英文大小写/空白)的形式归并,
    不确定的同义(如 mcp / mcp-server)不合并。
"""
import re

# ---------------- 技术词汇表(可扩展入口) ----------------
# 每项: 关键词(匹配用, 小写) -> 可读 label。
# 扩展: 直接在此 dict 增补即可; 匹配大小写不敏感。
TECH_TERMS = {
    "mcp": "MCP",
    "fastmcp": "FastMCP",
    "function calling": "Function Calling",
    "function-calling": "Function Calling",
    "rag": "RAG",
    "github trending": "GitHub Trending",
    "倒排表": "倒排索引",
    "倒排索引": "倒排索引",
    "长期记忆": "长期记忆",
    "向量检索": "向量检索",
    "检索增强": "检索增强",
    "工具调用": "工具调用",
    "智能体": "智能体",
    "agent": "Agent",
}

# ---------------- 语义噪声(非符号噪音) ----------------
# 这些是流程/状态/文件类 token, 无复习价值; 词频抽取常把它们当「概念」。
SEMANTIC_NOISE = {
    "py", "md", "txt", "json", "csv", "html", "css", "js", "ts", "yaml",
    "交付", "冒烟", "回归", "复盘", "调研", "重试", "selftest", "todo",
    "done", "check", "wip", "tbd", "fixme", "commit", "push", "部署",
    "测试", "验证", "打包", "上线", "修复", "优化", "整理", "重构",
}

# 星期词(中文/英文缩写)
_WEEKDAYS = {
    "周一", "周二", "周三", "周四", "周五", "周六", "周日",
    "星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
}

# 文件类 token: 含扩展名或路径分隔
_RE_FILE = re.compile(r"[\w.-]+\.(?:md|py|txt|json|csv|html|css|js|ts|yaml)$", re.I)
_RE_PATH = re.compile(r"[./\\]")
# 纯符号
_RE_SYMBOL = re.compile(r"^[^\w\u4e00-\u9fff]+$")
# 英文词(2+ 字母)用于术语匹配
_RE_EN = re.compile(r"[A-Za-z][A-Za-z0-9\- ]{1,40}")


def _stable_key(text):
    """稳定键: 去首尾空白、连续空白压成一个空格、英文小写。中文原样保留。"""
    s = re.sub(r"\s+", " ", str(text or "")).strip()
    return s.lower()


def _is_semantic_noise(c):
    """语义噪声判定: 短单字/纯数字/纯符号/文件或路径/星期/流程状态词。"""
    s = str(c or "").strip()
    if not s or len(s) < 2:
        return True
    if s.isdigit():
        return True
    if s in SEMANTIC_NOISE:
        return True
    if s.lower() in _WEEKDAYS:
        return True
    if _RE_SYMBOL.match(s):
        return True
    if _RE_FILE.match(s) or _RE_PATH.search(s):
        return True
    return False


def _match_tech_terms(text):
    """在文本中按词汇表顺序匹配已知技术术语, 返回 (concept_key, label) 列表(去重保序)。"""
    low = str(text or "").lower()
    found = []
    seen = set()
    for term, label in TECH_TERMS.items():
        if term in low:
            key = _stable_key(term)
            if key not in seen:
                seen.add(key)
                found.append({"concept": key, "label": label})
    return found


def normalize_concepts(note):
    """把单条 note(analysis.json 的 notes[date] 结构)归一化为概念列表。

    note 形如 {"topic":..., "concepts":[...], "tags":[...], "code_langs":[...]}。
    优先级:
      1. 显式 tags(去语义噪声后, 直接作为概念 + label)
      2. 正文中的已知技术短语(topic + tags 文本内匹配词汇表)
      3. 现有 concept 候选作为回退(去语义噪声后)
    返回 [{concept, label}, ...], 确定性、去重保序。
    空/无效 note -> 空列表(安全)。
    """
    if not isinstance(note, dict):
        return []
    out, seen = [], set()

    def _add(key, label, override_label=False):
        key = _stable_key(key)
        if not key:
            return
        if key in seen:
            # 词汇表命中(规范名)可覆盖已有 tag 原文 label, 使 label 更可读
            if override_label:
                for o in out:
                    if o["concept"] == key:
                        o["label"] = str(label or "").strip() or key
            return
        seen.add(key)
        out.append({"concept": key, "label": str(label or "").strip() or key})

    # 1. 显式 tags 优先(concept + 原文 label)
    for t in note.get("tags") or []:
        t = str(t).strip()
        if t and not _is_semantic_noise(t):
            _add(t, t)

    # 2. 正文(话题 + tags 拼接)中的已知技术短语 -> 规范 label(可覆盖 tag 原文)
    probe = " ".join([str(note.get("topic") or ""),
                      " ".join(str(x) for x in (note.get("tags") or []))])
    for hit in _match_tech_terms(probe):
        _add(hit["concept"], hit["label"], override_label=True)

    # 3. 现有 concept 候选回退(去语义噪声)
    for c in note.get("concepts") or []:
        c = str(c).strip()
        if c and not _is_semantic_noise(c):
            _add(c, c)

    return out
