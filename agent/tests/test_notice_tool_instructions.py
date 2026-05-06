import unittest
from pathlib import Path


class TestNoticeToolInstructions(unittest.TestCase):
    def test_notice_tool_uses_apex_id_param(self) -> None:
        instructions_path = (
            Path(__file__).resolve().parents[1] / "app" / "agent_instructions.txt"
        )
        text = instructions_path.read_text()

        self.assertIn(
            "find_notice_for_user_sync(apex_id)",
            text,
            "Instructions should call find_notice_for_user_sync with apex_id parameter",
        )
        self.assertNotIn(
            "find_notice_for_user_sync(new_apexid)",
            text,
            "Instructions should not use new_apexid parameter for notice tool",
        )

    def test_case_followups_route_to_dynamics_after_notice_miss(self) -> None:
        instructions_path = (
            Path(__file__).resolve().parents[1] / "app" / "agent_instructions.txt"
        )
        text = instructions_path.read_text()

        self.assertIn("get_class_member_details_sync(apex_id)", text)
        self.assertIn("get_member_cases_sync(apex_id)", text)
        self.assertIn("get_case_details_sync(case_id)", text)
        self.assertIn("do not repeat `find_notice_for_user_sync`", text)


if __name__ == "__main__":
    unittest.main()
