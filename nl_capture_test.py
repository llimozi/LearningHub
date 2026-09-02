# -*- coding: utf-8 -*-
"""nl_capture_test.py —— v1.9 C3 自然语言快捕解析测试(全部固定日期注入)"""
import datetime

import nl_capture

TODAY = datetime.date(2099, 8, 10)          # 周一(用于周X相对计算)



def _iso(d):
    return d.isoformat()


def test_examples_from_spec():
    r = nl_capture.parse_quick_input("明天上午 45分钟 复习agent", today=TODAY)
    assert r["title"].find("复习") >= 0 and "45" not in r["title"], r
    assert r["day"] == "tomorrow" and r["window"] == "09-12", r
    assert r["est_minutes"] == 45, r
    assert "agent" in r["tags"], r

    r = nl_capture.parse_quick_input("下周一 写周报 P1", today=TODAY)
    assert r["day"] and r["priority"] == 1, r
    assert r["title"].find("周报") >= 0 and "P1" not in r["title"], r

    r = nl_capture.parse_quick_input("≤30min 读论文", today=TODAY)
    assert r["est_minutes"] == 30 and r["title"].find("读论文") >= 0, r

    r = nl_capture.parse_quick_input("今天 复习 #项目工程 3张", today=TODAY,
                                     keywords={"项目工程": ["项目", "打包"]})
    assert r["day"] == "today" and r["review_count"] == 3, r
    assert "项目工程" in r["tags"], r

    r = nl_capture.parse_quick_input("整理笔记", today=TODAY)
    assert r["title"] == "整理笔记" and r["day"] is None and r["confidence"] == "low", r


def test_unresolvable_words_stay_in_title():
    r = nl_capture.parse_quick_input("尽快 把架构图补完", today=TODAY)
    assert "尽快" in r["title"] and "补完" in r["title"], r   # 无法解析不报错不丢失
    assert r["day"] is None, r


def test_weekday_and_date_forms():
    r = nl_capture.parse_quick_input("周五 交作业", today=TODAY)   # 周一->本周五=+4
    assert r["day"] == _iso(TODAY + datetime.timedelta(days=4)), r
    r = nl_capture.parse_quick_input("下周三 预研", today=TODAY)
    assert r["day"] == _iso(TODAY + datetime.timedelta(days=9)), r
    r = nl_capture.parse_quick_input("12月1日 年终总结", today=TODAY)
    assert r["day"] == "2099-12-01", r


def test_confidence_levels():
    hi = nl_capture.parse_quick_input("明天上午 30分钟 复习 #agent 5张", today=TODAY)
    assert hi["confidence"] == "high", hi
    mid = nl_capture.parse_quick_input("明天 写代码 P2", today=TODAY)
    assert mid["confidence"] in ("mid", "low"), mid


if __name__ == "__main__":
    fns = [(k, v) for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in fns:
        try:
            fn()
            print("PASS", name)
        except Exception as e:
            failed += 1
            print("FAIL", name, "->", repr(e)[:200])
    if failed:
        print("RUNNER: %d FAILED" % failed)
    else:
        print("RUNNER: ALL GREEN (%d tests)" % len(fns))
