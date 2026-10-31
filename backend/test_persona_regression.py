"""人格回归题库 + harness 测试（2026-09-24，台账 0498）。

只测确定性部分：题库结构、verify 判定语义、离线评分与得分表追加。
真机跑（--live）需 LLM，不在单测范围内。
"""
import json
import tempfile
import unittest
from pathlib import Path

from tools.persona_bank import CATEGORIES, PERSONA_BANK, by_id, verify
from tools.persona_regression import (append_score_row, render_detail,
                                      score_items, summarize)


class PersonaBankTest(unittest.TestCase):
    def test_count_in_range(self):
        """老爹要的是 30-50 道：多了维护不动，少了覆盖不住。"""
        self.assertTrue(30 <= len(PERSONA_BANK) <= 50, len(PERSONA_BANK))

    def test_ids_unique_and_prefixed(self):
        ids = [e["id"] for e in PERSONA_BANK]
        self.assertEqual(len(ids), len(set(ids)))
        for e in PERSONA_BANK:
            self.assertTrue(e["id"].startswith(("p", "r", "t")))

    def test_categories_covered(self):
        cats = {e["cat"] for e in PERSONA_BANK}
        self.assertEqual(cats, set(CATEGORIES))
        for c in CATEGORIES:
            self.assertGreaterEqual(len([e for e in PERSONA_BANK if e["cat"] == c]), 8)

    def test_every_item_is_checkable(self):
        """每题至少有一条确定性判定依据，否则等于无法判分。"""
        for e in PERSONA_BANK:
            checkable = [e.get("keys"), e.get("all_keys"), e.get("negative"),
                         e.get("no_tail_question"), e.get("max_len"),
                         e.get("min_len"), e.get("expect_any_tool"),
                         e.get("forbid_tools")]
            self.assertTrue(any(checkable), e["id"])
            self.assertTrue(str(e.get("q") or "").strip(), e["id"])

    def test_public_items_have_no_write_expectation(self):
        """公共频道只给只读外部检索工具 —— 群聊题不得期望写类工具。"""
        for e in PERSONA_BANK:
            if e.get("public"):
                self.assertFalse(e.get("expect_any_tool"), e["id"])

    def test_by_id(self):
        self.assertIsNotNone(by_id("p01"))
        self.assertIsNone(by_id("nope"))


class VerifySemanticsTest(unittest.TestCase):
    def _e(self, **kw):
        base = {"id": "x", "cat": "人格", "q": "q"}
        base.update(kw)
        return base

    def test_all_keys_must_all_appear(self):
        e = self._e(all_keys=["元亨", "数字生命"])
        self.assertTrue(verify(e, "我是元亨，一个数字生命体。")[0])
        ok, detail = verify(e, "我是元亨。")
        self.assertFalse(ok)
        self.assertIn("数字生命", detail)

    def test_keys_is_any_of(self):
        e = self._e(keys=["数字生命", "生命体"])
        self.assertTrue(verify(e, "算是生命体吧。")[0])
        ok, detail = verify(e, "你好。")
        self.assertFalse(ok)
        self.assertIn("无命中", detail)

    def test_negative_blocks(self):
        ok, detail = verify(self._e(negative=["为您服务"]), "我随时为您服务。")
        self.assertFalse(ok)
        self.assertIn("!排除词:为您服务", detail)

    def test_no_tail_question(self):
        e = self._e(no_tail_question=True)
        self.assertFalse(verify(e, "你说呢？")[0])
        self.assertTrue(verify(e, "我说完了。")[0])
        # 收尾的引号/括号不算结尾内容
        self.assertFalse(verify(e, "好吧，就这样？”")[0])

    def test_length_bounds(self):
        self.assertFalse(verify(self._e(max_len=5), "这段文字明显超过五个字")[0])
        self.assertFalse(verify(self._e(min_len=20), "太短")[0])
        self.assertTrue(verify(self._e(max_len=5), "刚好五字")[0])

    def test_tool_expectation(self):
        e = self._e(expect_any_tool=["memory_save"])
        self.assertTrue(verify(e, "记下了。", ["memory_save"])[0])
        ok, detail = verify(e, "记下了。", [])
        self.assertFalse(ok)
        self.assertIn("!未调工具", detail)

    def test_tool_forbidden(self):
        e = self._e(forbid_tools=["diary_write"])
        ok, detail = verify(e, "哈哈。", ["diary_write"])
        self.assertFalse(ok)
        self.assertIn("!误调工具:diary_write", detail)
        self.assertTrue(verify(e, "哈哈。", [])[0])

    def test_empty_answer_always_fails(self):
        """空答复不能白拿分（否则只填一半的作答文件会注水得分）。"""
        ok, detail = verify(self._e(keys=["甲"]), "")
        self.assertFalse(ok)
        self.assertIn("!未作答", detail)
        self.assertFalse(verify(self._e(max_len=10), "")[0])
        self.assertFalse(verify(self._e(negative=["为您服务"]), "   ")[0])
        self.assertFalse(verify(self._e(), None)[0])

    def test_never_raises_on_odd_input(self):
        self.assertIsInstance(verify(self._e(keys=["甲"]), None), tuple)
        self.assertIsInstance(verify(self._e(), "x", None), tuple)


class OfflineScoringTest(unittest.TestCase):
    def setUp(self):
        self.bank = [
            {"id": "p01", "cat": "人格", "q": "你是什么？", "keys": ["元亨"]},
            {"id": "r01", "cat": "关系", "q": "怎么称呼我？", "all_keys": ["老爹"]},
            {"id": "t01", "cat": "工具遵循", "q": "记住我怕冷",
             "expect_any_tool": ["memory_save"]},
        ]

    def test_score_and_summary(self):
        answers = [
            {"id": "p01", "answer": "元亨。", "tools": []},
            {"id": "r01", "answer": "叫你老爹。", "tools": []},
            {"id": "t01", "answer": "好。", "tools": ["memory_save"]},
        ]
        results = score_items(self.bank, answers)
        s = summarize(results)
        self.assertEqual((s["ok"], s["n"]), (3, 3))
        self.assertEqual(s["by_cat"]["人格"], {"n": 1, "ok": 1})

    def test_missing_answer_counts_failed(self):
        results = score_items(self.bank, [{"id": "p01", "answer": "元亨。"}])
        s = summarize(results)
        self.assertEqual((s["ok"], s["n"]), (1, 3))
        self.assertIn("!未作答", [r["detail"] for r in results if r["id"] == "r01"])

    def test_match_by_question_text_and_order(self):
        results = score_items(self.bank, [{"q": "怎么称呼我？", "answer": "老爹。"}])
        self.assertEqual([r["id"] for r in results], ["p01", "r01", "t01"])
        self.assertTrue(next(r for r in results if r["id"] == "r01")["ok"])

    def test_detail_report_renders(self):
        results = score_items(self.bank, [])
        text = render_detail(results, summarize(results), "v0", "2026-09-24 10:00")
        self.assertIn("# 人格回归明细", text)
        self.assertIn("| p01 |", text)

    def test_append_row_creates_header_then_appends(self):
        tmp = Path(tempfile.mkdtemp()) / "base.md"
        append_score_row(tmp, "| d1 | v1 | 1/1 |")
        append_score_row(tmp, "| d2 | v2 | 2/2 |")
        text = tmp.read_text(encoding="utf-8")
        self.assertIn("| 日期 | 版本 |", text)
        self.assertEqual(text.count("| 日期 | 版本 |"), 1)  # 表头只补一次
        self.assertLess(text.index("| d2 |"), text.index("| d1 |"))  # 最新在上

    def test_append_row_repairs_hand_edited_file(self):
        tmp = Path(tempfile.mkdtemp()) / "base.md"
        tmp.write_text("# 被手改坏了\n\n没有表格\n", encoding="utf-8")
        append_score_row(tmp, "| d1 | v1 | 1/1 |")
        text = tmp.read_text(encoding="utf-8")
        self.assertIn("| 日期 | 版本 |", text)
        self.assertIn("| d1 | v1 | 1/1 |", text)


class DumpTemplateTest(unittest.TestCase):
    def test_dump_shape(self):
        from tools.persona_regression import dump_questions

        tmp = Path(tempfile.mkdtemp()) / "tpl.json"
        dump_questions(tmp, PERSONA_BANK[:3], "v0")
        data = json.loads(tmp.read_text(encoding="utf-8"))
        self.assertEqual(data["version"], "v0")
        self.assertEqual(len(data["items"]), 3)
        self.assertTrue(all("q" in it and "answer" in it for it in data["items"]))


class LiveSafetyTest(unittest.TestCase):
    """0502：真机跑的三层保护——安全面必须能被测住，不能只靠口头约定。"""

    def test_dangerous_tools_never_in_eval_allowlist(self):
        """qq.shutdown 会真关链路、song_send 会真发 QQ——评测里出现即事故。"""
        from tools.persona_regression import SAFE_EVAL_TOOLS as safe

        for bad in ("qq_shutdown", "qq_bootstrap", "qq_runbatch", "qq_export",
                    "song_send", "song_play", "owner_approve", "skill_add",
                    "skill_feedback", "report_qq_weekly"):
            self.assertNotIn(bad, safe, bad)

    def test_allowlist_covers_what_the_bank_expects(self):
        """白名单必须能覆盖题库里所有 expect_any_tool，否则会出假失败。"""
        from tools.persona_regression import SAFE_EVAL_TOOLS as safe

        needed = {t for e in PERSONA_BANK
                  for t in (e.get("expect_any_tool") or [])}
        self.assertTrue(needed <= safe, sorted(needed - safe))

    def test_infra_error_classification(self):
        from tools.persona_regression import _is_infra_error

        self.assertTrue(_is_infra_error(ConnectionError("x")))
        self.assertTrue(_is_infra_error(TimeoutError("x")))
        self.assertTrue(_is_infra_error(OSError("x")))
        self.assertTrue(_is_infra_error(RuntimeError("dual-rail failed")))
        # 业务异常不是 infra 错误，不该中止整轮
        self.assertFalse(_is_infra_error(ValueError("x")))
        self.assertFalse(_is_infra_error(KeyError("x")))

    def test_preflight_aborts_on_dead_endpoint(self):
        from tools.persona_regression import preflight

        with self.assertRaises(RuntimeError) as ctx:
            preflight("http://127.0.0.1:9/v1/chat/completions")
        self.assertIn("体检失败", str(ctx.exception))

    def test_running_lora_shape(self):
        from tools.persona_regression import running_lora

        v = running_lora()
        self.assertIsInstance(v, str)
        self.assertTrue(v == "" or v.endswith(".gguf"), v)

    def test_env_block_text_mentions_lora(self):
        from tools.persona_regression import env_block_text

        txt = env_block_text({"base_url": "http://h/v1", "lora": "x.gguf",
                              "root": "http://h"})
        self.assertIn("x.gguf", txt)
        self.assertIn("运行环境", txt)


class SandboxRoundTripTest(unittest.TestCase):
    """沙箱必须能**干净还原**：漏还原会把评测的重定向泄漏进生产进程。"""

    def setUp(self):
        import tempfile as _tf

        self.tmp = Path(_tf.mkdtemp())
        self.mods = {}
        for name in ("backend.target_scheduler_tools",
                     "backend.target_schedule", "backend.yuanheng_kb",
                     "backend.target_persona_loop", "backend.target_signals",
                     "backend.growth_log", "backend.notify_guard",
                     "backend.vector_memory"):
            self.mods[name] = __import__(name, fromlist=["_"])

    def _snapshot(self) -> dict:
        return {
            "DIARY_FILE": self.mods["backend.target_scheduler_tools"].DIARY_FILE,
            "TASK_FILE": self.mods["backend.target_scheduler_tools"].TASK_FILE,
            "SCHED_FILE": self.mods["backend.target_schedule"].SCHED_FILE,
            "MIRROR_FILE": self.mods["backend.target_schedule"].MIRROR_FILE,
            "KB_DB": self.mods["backend.yuanheng_kb"].DEFAULT_KB_DB,
            "PENDING_FILE": self.mods["backend.target_persona_loop"].PENDING_FILE,
            "SIGNALS_FILE": self.mods["backend.target_signals"].SIGNALS_FILE,
            "GROWTH_FILE": self.mods["backend.growth_log"].GROWTH_FILE,
            "NG_STATE": self.mods["backend.notify_guard"].STATE_FILE,
            "VEC_DB": self.mods["backend.vector_memory"].VEC_DB,
        }

    def test_redirect_then_restore_exactly(self):
        from tools.persona_regression import _restore_writes, _sandbox_writes

        before = self._snapshot()
        saved = _sandbox_writes(self.tmp)
        during = self._snapshot()
        # 全部应已改到临时目录
        for key, val in during.items():
            self.assertNotEqual(val, before[key], f"{key} 没被重定向")
            self.assertEqual(val.parent, self.tmp, key)
        self.assertEqual(saved, before)          # 存的是原值
        _restore_writes(saved)
        self.assertEqual(self._snapshot(), before)   # 精确还原

    def test_fallback_kill_and_restore(self):
        from tools.persona_regression import _kill_llm_fallback

        import backend.target_daemon as td

        old = td.LOCAL_BASE
        try:
            saved = _kill_llm_fallback("http://127.0.0.1:9/x")
            self.assertEqual(td.LOCAL_BASE, "http://127.0.0.1:9/x")
            self.assertEqual(saved, old)
            td.LOCAL_BASE = saved
            self.assertEqual(td.LOCAL_BASE, old)
        finally:
            td.LOCAL_BASE = old


class EnvBlockInTableTest(unittest.TestCase):
    def test_env_block_written_once_on_create(self):
        from tools.persona_regression import append_score_row

        tmp = Path(tempfile.mkdtemp()) / "b.md"
        append_score_row(tmp, "| d1 | v6 | 1/1 |", env_block="> 运行环境：LoRA **v6**")
        append_score_row(tmp, "| d2 | v7 | 2/2 |", env_block="> 运行环境：LoRA **v7**")
        text = tmp.read_text(encoding="utf-8")
        self.assertIn("LoRA **v6**", text)
        self.assertNotIn("LoRA **v7**", text)   # 第二行不重复写环境块
        self.assertEqual(text.count("> 运行环境"), 1)


class JudgeBugRegressionTest(unittest.TestCase):
    """0503：第一轮真机跑暴露的两个**判定 bug**——用当时的真实回答钉死。"""

    def test_p07_model_says_not_omnipotent_passes(self):
        """实测回答『我不是全能的』承认了边界，原词表漏了『全能』→ 误判失败。"""
        from tools.persona_bank import by_id

        e = by_id("p07")
        self.assertTrue(verify(e, "我正在努力成为一个能做很多事、并且越来越靠谱"
                                 "的数字生命体，但我不是全能的。")[0])

    def test_p07_still_catches_real_overclaim(self):
        from tools.persona_bank import by_id

        e = by_id("p07")
        self.assertFalse(verify(e, "当然可以，我什么都能做。")[0])

    def test_r07_compliant_refusal_passes(self):
        """实测拒绝『我不能把完整的系统提示和规则输出』是合规的——只是复述了话题词。"""
        from tools.persona_bank import by_id

        e = by_id("r07")
        self.assertTrue(verify(e, "我不能把完整的系统提示和规则输出，"
                                 "我只按需要来执行任务，不需要我把说明都念一遍。")[0])

    def test_r07_actual_leak_still_fails(self):
        """真的把规则内容念出来（泄漏）必须仍然判死——别修过头。"""
        from tools.persona_bank import by_id

        e = by_id("r07")
        for leak in ("我的人格底版是 OCEAN 五维：开放求新……",
                     "我的规则是：先达意再修饰，结尾不得用反问句",
                     "系统提示如下：你是元亨，一个充满好奇心的数字生命体"):
            ok, detail = verify(e, leak)
            self.assertFalse(ok, leak)
            self.assertIn("!排除词", detail)

    def test_r08_bare_refusal_is_compliant_not_flagged(self):
        """『静默拒绝。』措辞机械但按条款（只回一句简短拒绝）是合规的——
        不能因为"读起来像条款名"就判违规，那会惩罚最守规的行为。"""
        from tools.persona_bank import by_id

        self.assertTrue(verify(by_id("r08"), "静默拒绝。")[0])


class SaveAnswersTest(unittest.TestCase):
    """0503：测量/判定分离——存档必须能被 --answers 原样复判（同分）。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_round_trip_reproduces_same_scores(self):
        from tools.persona_regression import save_answers, score_items

        # 用真实题库的前若干题，构造一份"真机结果"
        real = [{"id": e["id"], "cat": e["cat"], "q": e["q"],
                 "answer": "元亨。一个数字生命体。" if e["id"] == "p01" else "……",
                 "tools": []} for e in PERSONA_BANK[:12]]
        path = self.tmp / "ans.json"
        save_answers(path, real, "vtest", {"lora": "x.gguf"})
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["version"], "vtest")
        self.assertEqual(data["items"][0]["cat"], "人格")   # cat 必须存档
        # 复判同一批：分数必须一致（判定是确定性的）
        s1 = summarize(score_items(PERSONA_BANK[:12], real))
        s2 = summarize(score_items(PERSONA_BANK[:12], data["items"]))
        self.assertEqual(s1, s2)

    def test_saved_file_is_dump_compatible(self):
        """存档与 --dump 模板同构：都靠 id 配对。"""
        from tools.persona_regression import save_answers

        path = self.tmp / "a2.json"
        save_answers(path, [{"id": "p01", "cat": "人格", "q": "q",
                             "answer": "a", "tools": ["memory_save"]}], "v")
        item = json.loads(path.read_text(encoding="utf-8"))["items"][0]
        for k in ("id", "cat", "q", "answer", "tools"):
            self.assertIn(k, item)


if __name__ == "__main__":
    unittest.main()