# -*- coding: utf-8 -*-
"""helpcenter_test.py —— 内置帮助系统单元测试 (v1.4 · 纯标准库)
跑法A: pytest helpcenter_test.py      跑法B: python helpcenter_test.py
覆盖: 帮助文档四大必备板块(快捷键一览/功能说明/FAQ/备份指引) /
      核心快捷键行齐备 / FAQ 覆盖高频疑问 / API 层返回可渲染 Markdown。
"""
import shutil
import tempfile

import helpcenter


def test_help_markdown_is_renderable_string():
    md = helpcenter.get_help_markdown()
    assert isinstance(md, str) and len(md) > 800, len(md)
    assert md.startswith("#")


def test_has_four_required_sections():
    md = helpcenter.get_help_markdown()
    assert "## 一、" in md and "快捷键" in md
    assert "## 二、" in md and ("功能说明" in md or "功能速览" in md)
    assert "## 三、" in md and "FAQ" in md.upper()
    assert "## 四、" in md and "备份" in md


def test_shortcut_table_lists_core_keys():
    md = helpcenter.get_help_markdown()
    for key in ("Ctrl+Shift+L", "Ctrl+K", "Ctrl+S", "Space", "Ctrl+1",
                "Shift", "Enter"):
        assert key in md, key


def test_faq_answers_top_questions():
    md = helpcenter.get_help_markdown().upper()
    assert "退出" in md or "EXIT" in md                       # 关闭≠退出的澄清必在
    assert "端口" in md                                        # 端口占用怎么办
    assert "数据" in md and ("JSON" in md or "文件" in md)     # 数据存哪


def test_backup_guidance_covers_auto_manual_migrate_restore():
    md = helpcenter.get_help_markdown()
    assert "自动备份" in md and "backup" in md.lower()
    assert "导出" in md and "导入" in md                       # 迁移路径
    assert "还原" in md or "恢复" in md                        # 灾难恢复路径


def test_api_help_returns_same_markdown():
    from build_dashboard import api_help
    d = tempfile.mkdtemp()
    try:
        r = api_help()
        assert r["ok"] is True and r["markdown"] == helpcenter.get_help_markdown()
    finally:
        shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    import sys
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print("PASS", fn.__name__)
        except AssertionError as ex:
            failed += 1
            print("FAIL", fn.__name__, ex)
    print("RUNNER:", "ALL GREEN (%d tests)" % len(fns) if not failed else "%d FAILED" % failed)
    sys.exit(1 if failed else 0)
