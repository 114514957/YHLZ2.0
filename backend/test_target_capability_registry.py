"""Capability Registry + scheduler tests (ADR-007 / ledger 0145)."""

import unittest

from backend.target_capability_registry import Capability, CapabilityRegistry
from backend.target_scheduler_tools import (
    LEDGER,
    ledger_search,
    recall_memory,
    scheduler_capabilities,
    setup_scheduler_capabilities,
    setup_scheduler_tools,
    system_time,
)
from backend.agent.tool_registry import ToolRegistry


def _sq(params: dict) -> str:
    return "ok"


class TestCapabilityRegistry(unittest.TestCase):
    def setUp(self):
        self.reg = CapabilityRegistry()
        self.reg.register_policy("allow", lambda: True)
        self.reg.register_policy("deny", lambda: False)
        self.reg.register_capability(Capability(name="demo.run", handler=_sq,
                                                input=("a",), requires=("allow",)))

    def test_register_and_query(self):
        cap = self.reg.get("demo.run")
        self.assertIsNotNone(cap)
        self.assertEqual(cap.risk, "low")

    def test_execute_ok(self):
        res = self.reg.execute("demo.run", {"a": "x"})
        self.assertTrue(res["ok"])
        self.assertEqual(res["output"], "ok")

    def test_missing_input_rejected(self):
        res = self.reg.execute("demo.run", {})
        self.assertFalse(res["ok"])
        self.assertIn("missing input", res["error"])

    def test_policy_fail_closed(self):
        reg = CapabilityRegistry()
        reg.register_capability(Capability(name="demo.run", handler=_sq, input=(), requires=("missing",)))
        res = reg.execute("demo.run", {})
        self.assertFalse(res["ok"])
        self.assertIn("policy not registered", res["error"])

    def test_policy_denied(self):
        res = self.reg.execute("demo.run", {"a": "x"})
        self.assertTrue(res["ok"])
        denied = CapabilityRegistry()
        denied.register_policy("deny", lambda: False)
        denied.register_capability(Capability(name="demo.run", handler=_sq, input=(), requires=("deny",)))
        res = denied.execute("demo.run", {})
        self.assertFalse(res["ok"])
        self.assertIn("policy denied", res["error"])

    def test_unknown_capability(self):
        res = self.reg.execute("nope.nope", {})
        self.assertFalse(res["ok"])
        self.assertEqual(res["error"], "unknown capability")

    def test_exception_rollback(self):
        class R:
            def __init__(self):
                self.called = False
            def __call__(self):
                self.called = True
        r = R()

        def bad(_params):
            raise RuntimeError("boom")

        reg = CapabilityRegistry()
        reg.register_policy("allow", lambda: True)
        reg.register_capability(Capability(name="demo.bad", handler=bad, input=(), requires=("allow",), rollback=r))
        res = reg.execute("demo.bad", {})
        self.assertFalse(res["ok"])
        self.assertTrue(r.called)

    def test_name_dash_domain_validation(self):
        with self.assertRaises(ValueError):
            Capability(name="badname", handler=_sq)

    def test_typed_args_invalid_rejected(self):
        reg = setup_scheduler_capabilities()
        r = reg.execute("ledger.search", {"query": ""})
        self.assertFalse(r["ok"])
        self.assertIn("invalid arguments", r["error"])
        r2 = reg.execute("ledger.search", {"query": "麦克风", "limit": 999})
        self.assertFalse(r2["ok"])
        r3 = reg.execute("ledger.search", {"limit": 3})  # missing required query
        self.assertFalse(r3["ok"])

    def test_typed_args_valid_runs(self):
        reg = setup_scheduler_capabilities()
        r = reg.execute("ledger.search", {"query": "元亨", "limit": 2})
        self.assertTrue(r["ok"])

    def test_typed_schema_in_tool_export(self):
        reg = setup_scheduler_capabilities()
        tools = {t["function"]["name"]: t["function"] for t in reg.export_openai_tools()}
        params = tools["ledger_search"]["parameters"]
        props = params.get("properties", {})
        self.assertIn("query", props)
        self.assertIn("limit", props)
        self.assertIn("query", params.get("required", []))

    def test_policy_never_exported(self):
        tools = self.reg.export_openai_tools()
        flat = str(tools)
        self.assertNotIn("allow", flat)
        self.assertNotIn("deny", flat)
        self.assertEqual(len(tools), 1)

    def test_high_risk_requires_approval_policy(self):
        with self.assertRaises(ValueError):
            Capability(name="demo.risky", handler=_sq, risk="high")
        ok = Capability(name="demo.risky", handler=_sq, risk="high",
                        requires=("demo.risky.approval",))
        self.assertEqual(ok.risk, "high")

    def test_verify_rejected_rollback(self):
        class R:
            def __init__(self):
                self.called = False

            def __call__(self):
                self.called = True

        r = R()
        reg = CapabilityRegistry()
        reg.register_policy("allow", lambda: True)
        reg.register_capability(Capability(name="demo.verify", handler=_sq, input=(),
                                           requires=("allow",), rollback=r,
                                           verify=lambda out: False))
        res = reg.execute("demo.verify", {})
        self.assertFalse(res["ok"])
        self.assertEqual(res["error"], "verify failed")
        self.assertTrue(r.called)

    def test_verify_passed_commit_hook(self):
        events = []
        reg = CapabilityRegistry()
        reg.register_policy("allow", lambda: True)
        reg.set_commit_hook(events.append)
        reg.register_capability(Capability(name="demo.commit", handler=_sq, input=(),
                                           requires=("allow",), verify=lambda out: True))
        res = reg.execute("demo.commit", {})
        self.assertTrue(res["ok"])
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["name"], "demo.commit")

    def test_execute_openai_reverse_map(self):
        reg = setup_scheduler_capabilities()
        res = reg.execute_openai("system_time", {})
        self.assertTrue(res["ok"])
        self.assertIn("星期", res["output"])
        res2 = reg.execute_openai("no_such_tool", {})
        self.assertFalse(res2["ok"])
        self.assertEqual(res2["error"], "unknown capability")


class TestSchedulerCapabilities(unittest.TestCase):
    def test_metadata(self):
        caps = {c.name: c for c in scheduler_capabilities()}
        self.assertEqual(
            set(caps),
            {"ledger.search", "memory.recall", "memory.save", "system.time",
             "task.plan",
             "diary.write", "diary.list", "diary.delete",
             "task.plan",
             "kb.add", "kb.query",
             "qq.bootstrap", "qq.digest", "qq.export", "qq.process", "qq.status", "qq.summarize",
             "file.list", "file.read", "task.plan", "kb.add", "kb.query",
             "qq.bootstrap", "qq.digest", "qq.export", "qq.process", "qq.status", "qq.summarize",
             "web.fetch", "web.search"},
        )
        for name, cap in caps.items():
            if name in ("ledger.search", "memory.recall"):
                self.assertIn("query", cap.input)
                self.assertFalse(cap.side_effect)
            if name == "memory.save":
                self.assertIn("content", cap.input)
                self.assertTrue(cap.side_effect)
                self.assertEqual(cap.risk, "high")
            self.assertIn(cap.risk, ("low", "medium", "high"))
            cap.validate()

    def test_setup_registry_executes(self):
        reg = setup_scheduler_capabilities()
        res = reg.execute("system.time", {})
        self.assertTrue(res["ok"])
        self.assertIn("星期", res["output"])
        res = reg.execute("ledger.search", {"query": "元亨"})
        self.assertTrue(res["ok"])
        self.assertTrue(res["output"])

    def test_openai_tools_view(self):
        reg = setup_scheduler_capabilities()
        tools = reg.export_openai_tools()
        names = {t["function"]["name"] for t in tools}
        self.assertEqual(names, {"ledger_search", "memory_recall", "memory_save", "system_time",
              "diary_write", "diary_list", "diary_delete",
              "file_list", "file_read", "task_plan", "kb_add", "kb_query",
                   "qq_bootstrap", "qq_digest", "qq_export", "qq_process", "qq_status", "qq_summarize",
                   "web_fetch", "web_search"})

    def test_internal_names_stay_dotted(self):
        reg = setup_scheduler_capabilities()
        self.assertEqual(reg.names(), ["diary.delete", "diary.list", "diary.write", "file.list", "file.read",
             "kb.add", "kb.query", "ledger.search", "memory.recall", "memory.save",
             "qq.bootstrap", "qq.digest", "qq.export", "qq.process", "qq.status", "qq.summarize", "system.time",
             "task.plan", "web.fetch", "web.search"])

    def test_agent_core_registry_view(self):
        rt = ToolRegistry()
        names = setup_scheduler_tools(rt)
        self.assertEqual(sorted(names), ["diary_delete", "diary_list", "diary_write", "file_list", "file_read",
             "kb_add", "kb_query", "ledger_search", "memory_recall", "memory_save",
             "qq_bootstrap", "qq_digest", "qq_export", "qq_process", "qq_status", "qq_summarize", "system_time",
             "task_plan", "web_fetch", "web_search"])
        exported = rt.export_openai_tools()
        self.assertTrue(any(t["function"]["name"] == "system_time" for t in exported))


class TestSchedulerHandlers(unittest.TestCase):
    def test_ledger_search_anchor(self):
        result = ledger_search("元亨")
        self.assertTrue(result)
        self.assertIsNotNone(result)

    def test_ledger_search_empty(self):
        self.assertIn("未找到", ledger_search(""))

    def test_recall_memory_shape(self):
        self.assertIsInstance(recall_memory("zzz-not-exist"), str)

    def test_system_time(self):
        self.assertIn("星期", system_time())


if __name__ == "__main__":
    unittest.main()
