# -*- coding: utf-8 -*-
"""review_compose_test.py —— Phase C-B 复习源 compose_tomorrow 聚焦测试
跑法A: pytest review_compose_test.py   跑法B: python review_compose_test.py (零依赖runner)
覆盖(Phase C-B 规格):
  1 噪音过滤(py/md/##/services.py 被拒) / 2 标题解析(topic, 含回退) /
  3 单笔记最多一条 / 4 复习优先于 task_pool / 5 总预算钳制 /
  6 确定性id(c-rev-) / 7 重复调用幂等 / 8 全库id去重 /
  9 等价文本去重(即使id不同) / 10 已复习卡片排除 / 11 缺失/非法analysis安全降级
"""
import datetime
import hashlib
import os
import tempfile

from _app import services

TODAY = "2099-07-10"          # 复习判定日(due_cards 的 today)
TOM = "2099-07-11"
NOTE_D = "2099-07-08"         # 笔记日: 距 TODAY 2 天 >= 首档间隔 1 天 -> 到期
NOTE_D2 = "2099-07-09"        # 第二笔记日(不同 source_date 用)


def _note(topic, concepts, tags=None):
    return {"topic": topic, "concepts": concepts,
            "tags": tags or [], "code_langs": []}


def _mk_ld(notes):
    """建临时学习目录: analysis.json + sync 出 knowledge.json, 返回目录路径"""
    import analyzer
    import forgetting
    d = tempfile.mkdtemp(prefix="rc_")
    os.makedirs(os.path.join(d, "daily"), exist_ok=True)
    analyzer.save_analysis(d, {"notes": notes})
    forgetting.sync_from_analysis(d, today=datetime.date.fromisoformat(TODAY))
    return d


def _exp_id(concept):
    return "c-rev-" + hashlib.md5(concept.encode("utf-8")).hexdigest()[:8]


def _plan():
    return {"version": 1,
            "lines": [{"id": "A", "name": "线A",
                       "task_pool": [{"text": "任务甲", "priority": 2}]}],
            "priority_windows": []}


def _state(tom_bucket=None, other_buckets=None):
    days = {TODAY: [], TOM: list(tom_bucket or [])}
    for k, v in (other_buckets or {}).items():
        days[k] = list(v)
    return {"days": days}


def _cfg(ld, budget_plan=None):
    return {"plan": budget_plan if budget_plan is not None else _plan(),
            "learning_dir": ld, "today": TODAY}


# ---------- 1. 噪音过滤: py/md/##/services.py 被拒, 干净概念通过 ----------
def test_1_noise_filtering():
    ld = _mk_ld({NOTE_D: _note("纯噪音笔记", ["py", "md", "##", "services.py"]),
                 NOTE_D2: _note("Python list 切片技巧", ["切片"])})
    st = _state()
    out = services.compose_tomorrow(st, TOM, 5, cfg=_cfg(ld))
    assert out["review_generated"] == 1, out
    texts = [g["text"] for g in out["generated"]]
    assert "复习：Python list 切片技巧" in texts, texts
    assert sum(1 for t in texts if t.startswith("复习：")) == 1, texts
    for t in texts:
        assert not any(w in t for w in ("py", "md", "services")), t


# ---------- 2. 标题解析: 取 analysis.notes[source_date].topic; 空 topic 回退 concept ----------
def test_2_topic_resolution():
    ld = _mk_ld({NOTE_D: _note("Python list 切片", ["切片"]),
                 NOTE_D2: _note("", ["回测"])})          # 空标题 -> 回退 concept
    st = _state()
    out = services.compose_tomorrow(st, TOM, 5, cfg=_cfg(ld))
    texts = {g["text"] for g in out["generated"]}
    assert "复习：Python list 切片" in texts, out
    assert "复习：回测" in texts, out                     # 标题缺失时用概念名兜底
    assert out["review_generated"] == 2, out


# ---------- 3. 单笔记最多一条: 同 source_date 多概念 -> 只生成 1 条 ----------
def test_3_one_task_per_note():
    ld = _mk_ld({NOTE_D: _note("复合笔记", ["概念A", "概念B"])})
    st = _state()
    out = services.compose_tomorrow(st, TOM, 5, cfg=_cfg(ld))
    assert out["review_generated"] == 1, out
    texts = [g["text"] for g in out["generated"]]
    assert sum(1 for t in texts if t.startswith("复习：")) == 1, texts


# ---------- 4. 复习任务优先于 task_pool 候选 ----------
def test_4_review_priority():
    ld = _mk_ld({NOTE_D: _note("Python list 切片", ["切片"])})
    # budget=1: 只有复习任务, 池候选被挤掉
    st = _state()
    out = services.compose_tomorrow(st, TOM, 1, cfg=_cfg(ld))
    assert out["generated_count"] == 1, out
    assert out["generated"][0]["text"].startswith("复习："), out
    assert out["review_generated"] == 1, out
    # budget=2: 复习在前, 池候选随后
    st2 = _state()
    out2 = services.compose_tomorrow(st2, TOM, 2, cfg=_cfg(ld))
    assert out2["generated_count"] == 2, out2
    assert out2["generated"][0]["text"].startswith("复习："), out2
    assert out2["generated"][1]["text"] == "任务甲", out2


# ---------- 5. 总预算钳制: 复习+池 总生成数不超 remaining ----------
def test_5_total_budget_clamp():
    ld = _mk_ld({NOTE_D: _note("t1", ["概念甲"]),
                 "2099-07-06": _note("t2", ["概念乙"]),
                 "2099-07-05": _note("t3", ["概念丙"])})     # 3 个到期概念
    st = _state()
    out = services.compose_tomorrow(st, TOM, 1, cfg=_cfg(ld))
    assert out["generated_count"] == 1, out              # 只生成 1 条(复习优先)
    assert out["review_generated"] == 1, out
    assert out["final_count"] == 1, out


# ---------- 6. 确定性 id: c-rev-+md5(concept), 跨调用稳定 ----------
def test_6_deterministic_id():
    ld = _mk_ld({NOTE_D: _note("Python list 切片", ["切片"])})
    st = _state()
    out = services.compose_tomorrow(st, TOM, 3, cfg=_cfg(ld))
    tid = st["days"][TOM][0]["id"]
    assert tid == _exp_id("切片"), (tid, _exp_id("切片"))
    assert tid.startswith("c-rev-"), tid
    # 新状态同样输入 -> 同 id
    st2 = _state()
    services.compose_tomorrow(st2, TOM, 3, cfg=_cfg(ld))
    assert st2["days"][TOM][0]["id"] == tid, st2["days"][TOM]


# ---------- 7. 重复调用幂等: 二次调用零新增 ----------
def test_7_idempotency():
    ld = _mk_ld({NOTE_D: _note("Python list 切片", ["切片"])})
    st = _state()
    out1 = services.compose_tomorrow(st, TOM, 1, cfg=_cfg(ld))
    assert out1["generated_count"] == 1, out1            # budget=1: 仅复习(优先)
    assert out1["review_generated"] == 1, out1
    out2 = services.compose_tomorrow(st, TOM, 1, cfg=_cfg(ld))
    assert out2["generated_count"] == 0, out2
    assert out2["review_generated"] == 0, out2
    assert len(st["days"][TOM]) == 1, st["days"][TOM]


# ---------- 8. 全库去重: 同 id 存在于其他日期桶 -> 跳过 ----------
def test_8_whole_repo_dedup():
    ld = _mk_ld({NOTE_D: _note("Python list 切片", ["切片"])})
    st = _state(tom_bucket=[], other_buckets={TODAY: [{"id": _exp_id("切片"),
                                                       "text": "复习：Python list 切片"}]})
    out = services.compose_tomorrow(st, TOM, 3, cfg=_cfg(ld))
    assert out["review_generated"] == 0, out
    texts = [t.get("text", "") for t in st["days"][TOM]]
    assert not any(t.startswith("复习：") for t in texts), texts


# ---------- 9. 等价文本去重: id 不同但文本归一化等价 -> 跳过, 既有任务原样 ----------
def test_9_equivalent_text_dedup():
    ld = _mk_ld({NOTE_D: _note("Python list 切片", ["切片"])})
    manual = {"id": "m1", "text": "复习：Python list 切片", "done": False}
    st = _state(tom_bucket=[manual])
    before = [dict(t) for t in st["days"][TOM]]
    empty_pool = {"version": 1, "lines": [], "priority_windows": []}
    out = services.compose_tomorrow(st, TOM, 3,
                                    cfg={"plan": empty_pool, "learning_dir": ld,
                                         "today": TODAY})
    assert out["review_generated"] == 0, out
    assert out["generated_count"] == 0, out
    assert st["days"][TOM] == before, "既有手工任务被改动"


# ---------- 10. 已复习卡片排除: last_review_ts 近期 -> 不到期 -> 不生成 ----------
def test_10_already_reviewed_excluded():
    import forgetting
    ld = _mk_ld({NOTE_D: _note("Python list 切片", ["切片"])})
    forgetting.mark_reviewed(ld, "切片",
                             now=datetime.datetime(2099, 7, 10, 8, 0, 0), quality=4)
    st = _state()
    out = services.compose_tomorrow(st, TOM, 3, cfg=_cfg(ld))
    assert out["review_generated"] == 0, out


# ---------- 11. 缺失/非法 analysis 安全降级 ----------
def test_11_missing_invalid_degrade():
    # 11a. 不传 learning_dir -> 复习源不启用, 池照常生成, 不报错
    st = _state()
    out = services.compose_tomorrow(st, TOM, 3, cfg={"plan": _plan()})
    assert out["generated_count"] == 1, out
    assert out["review_generated"] == 0, out
    # 11b. learning_dir 指向不存在的目录 -> 零复习, 池照常, 不报错
    st2 = _state()
    out2 = services.compose_tomorrow(
        st2, TOM, 3,
        cfg={"plan": _plan(), "learning_dir": "Z:/no_such_dir_xyz", "today": TODAY})
    assert out2["generated_count"] == 1, out2
    assert out2["review_generated"] == 0, out2
    # 11c. analysis.json 缺失但 knowledge.json 存在 -> topic 回退 concept
    ld = _mk_ld({NOTE_D: _note("Python list 切片", ["切片"])})
    os.remove(os.path.join(ld, "daily", "analysis.json"))
    st3 = _state()
    out3 = services.compose_tomorrow(st3, TOM, 3, cfg=_cfg(ld))
    assert out3["review_generated"] == 1, out3
    assert out3["generated"][0]["text"] == "复习：切片", out3   # 回退概念名


# ---------- 元数据: 复习任务携带 concept/source_date 供 mark_reviewed 复用 ----------
def test_meta_retained():
    ld = _mk_ld({NOTE_D: _note("Python list 切片", ["切片"])})
    st = _state()
    services.compose_tomorrow(st, TOM, 3, cfg=_cfg(ld))
    t = st["days"][TOM][0]
    assert t["review_concept"] == "切片", t
    assert t["review_source_date"] == NOTE_D, t
    assert t["priority"] == 1, t                            # 复习任务最高优先级


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print("PASS", fn.__name__)
        except AssertionError as ex:
            failed += 1
            print("FAIL", fn.__name__, ex)
        except Exception as ex:
            failed += 1
            print("ERROR", fn.__name__, ex)
    print("RUNNER:", "ALL GREEN (%d tests)" % len(fns) if not failed else "%d FAILED" % failed)
    import sys
    sys.exit(1 if failed else 0)
