"""
YHLZ Vision Action V1.0 - 规划器单元测试

覆盖:
    - 错误/异常场景 → 检查日志 + 诊断报告
    - 登录场景 → 检查账户
    - 任务/文档场景 → 生成报告
    - 普通场景 → 无建议
    - 对象 / dict 双输入
"""
import unittest

from backend.action.planners.action_planner import suggest_actions
from backend.action.schema import ActionRequest


class TestSuggestActions(unittest.TestCase):

    def test_error_scene_suggests_logs_check(self):
        suggestions = suggest_actions({
            "scene_type": "error",
            "description": "浏览器报错: 连接超时",
            "subjects": [],
            "summary": "",
        })
        self.assertEqual(len(suggestions), 2)
        self.assertEqual(suggestions[0].action_type, "check")
        self.assertEqual(suggestions[0].target, "logs")
        self.assertEqual(suggestions[1].action_type, "report")

    def test_error_keyword_in_description(self):
        suggestions = suggest_actions({
            "scene_type": "web",
            "description": "页面显示 500 错误",
            "subjects": [],
            "summary": "",
        })
        self.assertGreaterEqual(len(suggestions), 1)
        self.assertEqual(suggestions[0].target, "logs")

    def test_login_scene(self):
        suggestions = suggest_actions({
            "scene_type": "web",
            "description": "页面提示需要登录",
            "subjects": ["login"],
            "summary": "",
        })
        self.assertEqual(len(suggestions), 1)
        self.assertEqual(suggestions[0].target, "account")
        self.assertEqual(suggestions[0].risk_level, "medium")

    def test_task_scene(self):
        suggestions = suggest_actions({
            "scene_type": "document",
            "description": "任务文档已就绪",
            "subjects": [],
            "summary": "需要总结",
        })
        self.assertEqual(len(suggestions), 1)
        self.assertEqual(suggestions[0].action_type, "report")

    def test_plain_scene_no_suggestion(self):
        suggestions = suggest_actions({
            "scene_type": "web",
            "description": "普通网页内容",
            "subjects": [],
            "summary": "",
        })
        self.assertEqual(suggestions, [])

    def test_object_input(self):
        class Obj:
            scene_type = "error"
            description = "服务崩溃"
            subjects = []
            summary = ""

        suggestions = suggest_actions(Obj())
        self.assertEqual(suggestions[0].target, "logs")

    def test_empty_input(self):
        self.assertEqual(suggest_actions({}), [])

    def test_suggestions_are_requests_not_executed(self):
        suggestions = suggest_actions({
            "scene_type": "error",
            "description": "报错",
            "subjects": [],
            "summary": "",
        })
        for s in suggestions:
            self.assertIsInstance(s, ActionRequest)
            self.assertTrue(s.reason)


if __name__ == "__main__":
    unittest.main()
