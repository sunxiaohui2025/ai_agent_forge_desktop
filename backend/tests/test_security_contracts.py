import unittest

from app.runtime.permissions import classify
from app.ui_schema.types import is_declared_ui_action


class SecurityContractTests(unittest.TestCase):
    def test_ui_action_requires_matching_surface_and_tool(self):
        uis = [{
            "surface_id": "surface-1",
            "actions": [{"agent_call": True, "tool": "book_hotel"}],
        }]
        self.assertTrue(is_declared_ui_action(uis, "surface-1", "book_hotel"))
        self.assertFalse(is_declared_ui_action(uis, "surface-2", "book_hotel"))
        self.assertFalse(is_declared_ui_action(uis, "surface-1", "delete_all"))

    def test_message_actions_cannot_be_used_as_direct_tools(self):
        uis = [{
            "surface_id": "surface-1",
            "actions": [{
                "agent_call": True,
                "submit_as": "message",
                "tool": "book_hotel",
            }],
        }]
        self.assertFalse(is_declared_ui_action(uis, "surface-1", "book_hotel"))

    def test_dangerous_shell_is_high_risk(self):
        self.assertEqual(classify("run_command", {"command": "rm -rf ./build"}).level, "high")


if __name__ == "__main__":
    unittest.main()
