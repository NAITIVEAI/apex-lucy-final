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

    def test_generic_notice_fallback_is_spelled_out_play_by_play(self) -> None:
        instructions_path = (
            Path(__file__).resolve().parents[1] / "app" / "agent_instructions.txt"
        )
        text = instructions_path.read_text()

        self.assertIn("single flat folder/prefix `lucycmnotices/generic-notices/", text)
        self.assertIn("search only the West generic notice folder/prefix corpus", text)
        self.assertIn("Apex prints the Apex ID on those individualized mailed PDFs", text)
        self.assertIn("Do not expect the Apex ID to appear in a generic case notice", text)
        self.assertIn("it is the notice for that case, just with member-specific fields filled from Dynamics", text)
        self.assertIn("How much is my check?", text)
        self.assertIn("Never imply that the generic PDF contains member-specific values", text)

    def test_prompt_has_no_individualized_miss_apology_shortcut(self) -> None:
        instructions_path = (
            Path(__file__).resolve().parents[1] / "app" / "agent_instructions.txt"
        )
        text = instructions_path.read_text()

        self.assertIn("Never stop after only the individualized notice miss", text)
        self.assertIn("no individualized or generic case notice was available after both lookup paths", text)
        self.assertIn("generic case notice fallback is part of the required tool path", text)
        self.assertNotIn("If notice not found", text)
        self.assertNotIn("I'm so sorry, I wasn't able to find your notice this time", text)
        self.assertNotIn("check back in about two weeks", text)


if __name__ == "__main__":
    unittest.main()
