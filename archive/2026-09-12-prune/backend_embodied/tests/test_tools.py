"""
YHLZ Embodied AI V4.2 - 具身 Agent 工具单元测试

覆盖:
    - register_embodied_tools / unregister_embodied_tools (V4.2: 3 个工具)
    - 工具参数 schema 完整
    - handler 调用 (只读查询, 返回 JSON)
    - 异常兜底 (不抛异常)
"""
import json
import unittest
from unittest import mock

from backend.embodied.tools import (
    EMBODIED_TOOL_NAMES,
    _tool_predict_environment_change,
    _tool_query_environment_events,
    _tool_query_environment_state,
    register_embodied_tools,
    unregister_embodied_tools,
)


class TestRegisterTools(unittest.TestCase):

    def tearDown(self):
        unregister_embodied_tools()

    def test_register_three_tools(self):
        n = register_embodied_tools(override=True)
        self.assertEqual(n, 3)
        self.assertEqual(
            EMBODIED_TOOL_NAMES,
            [
                "query_environment_state",
                "query_environment_events",
                "predict_environment_change",
            ],
        )

    def test_register_idempotent(self):
        register_embodied_tools(override=True)
        n = register_embodied_tools(override=True)
        self.assertEqual(n, 3)

    def test_registered_in_registry(self):
        from backend.agent.tool_registry import get_registry

        reg = get_registry()
        register_embodied_tools(override=True)
        tool = reg.get("query_environment_state")
        self.assertIsNotNone(tool)
        self.assertEqual(tool.category, "embodied")
        self.assertIn("environment", tool.parameters.properties)
        self.assertIn("include_changes", tool.parameters.properties)
        # V4.2: 新增工具
        self.assertIsNotNone(reg.get("query_environment_events"))
        self.assertIsNotNone(reg.get("predict_environment_change"))
        self.assertEqual(
            reg.list_names(category="embodied"),
            ["query_environment_state", "query_environment_events", "predict_environment_change"],
        )

    def test_unregister(self):
        register_embodied_tools(override=True)
        n = unregister_embodied_tools()
        self.assertEqual(n, 3)

    def test_unregister_twice(self):
        register_embodied_tools(override=True)
        unregister_embodied_tools()
        n = unregister_embodied_tools()
        self.assertEqual(n, 0)


class TestToolHandler(unittest.TestCase):

    def tearDown(self):
        unregister_embodied_tools()

    def test_query_returns_json(self):
        register_embodied_tools(override=True)
        out = _tool_query_environment_state({})
        data = json.loads(out)
        self.assertIn("current_state", data)
        self.assertIn("environments", data)
        self.assertIn("feedback_stats", data)
        self.assertIn("memory_stats", data)
        # V4.2: 上下文增强
        self.assertIn("events", data)
        self.assertIn("causal_analysis", data)
        self.assertIn("prediction_confidence", data)
        self.assertIn("experience", data)

    def test_query_with_environment_param(self):
        register_embodied_tools(override=True)
        out = _tool_query_environment_state({"environment": "mock", "include_changes": True})
        data = json.loads(out)
        self.assertIn("recent_changes", data)

    def test_handler_error_fallback(self):
        """异常兜底: 不抛异常, 返回错误 JSON"""
        with mock.patch(
            "backend.embodied.service.get_service",
            side_effect=RuntimeError("boom"),
        ):
            out = _tool_query_environment_state({})
        data = json.loads(out)
        self.assertFalse(data["success"])
        self.assertIn("工具异常", data["error"])

    def test_handler_never_executes_actions(self):
        """只读安全: 工具不暴露任何执行动作能力"""
        reg_handler = _tool_query_environment_state
        self.assertEqual(reg_handler({"environment": "mock"})[:1], "{")
        # 参数表不包含任何动作类型字段
        from backend.agent.tool_registry import get_registry

        register_embodied_tools(override=True)
        tool = get_registry().get("query_environment_state")
        props = tool.parameters.properties
        self.assertNotIn("action_type", props)
        self.assertNotIn("confirmed", props)


class TestQueryEnvironmentEventsTool(unittest.TestCase):
    """V4.2: query_environment_events 工具"""

    def tearDown(self):
        unregister_embodied_tools()

    def test_returns_events_json(self):
        register_embodied_tools(override=True)
        out = _tool_query_environment_events({"limit": 10})
        data = json.loads(out)
        self.assertTrue(data["success"])
        self.assertIn("events", data)
        self.assertIn("event_stats", data)

    def test_filters(self):
        register_embodied_tools(override=True)
        out = _tool_query_environment_events(
            {"limit": 5, "event_type": "action", "result": "success"},
        )
        data = json.loads(out)
        self.assertTrue(data["success"])
        self.assertLessEqual(data["count"], 5)

    def test_limit_clamped(self):
        register_embodied_tools(override=True)
        out = _tool_query_environment_events({"limit": 9999})
        data = json.loads(out)
        self.assertTrue(data["success"])
        self.assertLessEqual(data["count"], 100)

    def test_error_fallback(self):
        with mock.patch(
            "backend.embodied.service.get_service",
            side_effect=RuntimeError("boom"),
        ):
            out = _tool_query_environment_events({})
        data = json.loads(out)
        self.assertFalse(data["success"])

    def test_registry_params(self):
        from backend.agent.tool_registry import get_registry

        register_embodied_tools(override=True)
        tool = get_registry().get("query_environment_events")
        self.assertIn("limit", tool.parameters.properties)
        self.assertIn("event_type", tool.parameters.properties)


class TestPredictEnvironmentChangeTool(unittest.TestCase):
    """V4.2: predict_environment_change 工具 (只预测不执行)"""

    def tearDown(self):
        unregister_embodied_tools()

    def test_predict_sequence(self):
        register_embodied_tools(override=True)
        out = _tool_predict_environment_change({
            "actions": [
                {"action_type": "move", "parameters": {"dx": 1, "dy": 0}},
                {"action_type": "pick", "target": "lamp", "parameters": {"object": "lamp"}},
            ],
        })
        data = json.loads(out)
        self.assertTrue(data["success"])
        self.assertIn("prediction", data)
        self.assertEqual(len(data["prediction"]["steps"]), 2)
        self.assertIn("final_expected", data["prediction"])

    def test_empty_actions_rejected(self):
        register_embodied_tools(override=True)
        out = _tool_predict_environment_change({"actions": []})
        data = json.loads(out)
        self.assertFalse(data["success"])
        self.assertIn("actions", data["error"])

    def test_error_fallback(self):
        with mock.patch(
            "backend.embodied.service.get_service",
            side_effect=RuntimeError("boom"),
        ):
            out = _tool_predict_environment_change({
                "actions": [{"action_type": "scan"}],
            })
        data = json.loads(out)
        self.assertFalse(data["success"])

    def test_predict_tool_never_executes(self):
        """只预测: 工具无执行参数 (confirmed 等), 且注册表无执行工具"""
        from backend.agent.tool_registry import get_registry

        register_embodied_tools(override=True)
        tool = get_registry().get("predict_environment_change")
        props = tool.parameters.properties
        self.assertIn("actions", props)
        self.assertNotIn("confirmed", props)
        self.assertNotIn("execution", props)
        names = get_registry().list_names(category="embodied")
        for n in names:
            self.assertNotIn("execute", n)


if __name__ == "__main__":
    unittest.main()
