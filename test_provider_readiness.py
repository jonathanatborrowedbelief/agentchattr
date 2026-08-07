"""Behavior tests for provider-pane readiness classification."""

import unittest

from provider_readiness import classify_provider_screen


CLAUDE_READY_FOOTER = "⏸ manual mode on · ? for shortcuts · ← for agents"


class ClaudeReadinessTests(unittest.TestCase):
    def test_bare_claude_composer_remains_ready_without_footer(self):
        """Catch the established bare-composer readiness contract regressing."""
        self.assertEqual(
            classify_provider_screen("claude", "❯"),
            ("provider_ready", "ready_prompt"),
        )

    def test_claude_suggestion_composer_requires_the_ready_footer(self):
        """Catch a suggestion composer being missed or accepted without footer proof."""
        composer = '❯\u00a0Try "how do I log an error?"'
        self.assertEqual(
            classify_provider_screen("claude", f"{composer}\n{CLAUDE_READY_FOOTER}"),
            ("provider_ready", "ready_prompt"),
        )
        self.assertEqual(
            classify_provider_screen("claude", composer),
            ("registered", "unknown_screen"),
        )

    def test_claude_numbered_menu_prompts_without_footer_remain_unknown(self):
        """Catch login and menu choices being mistaken for the composer."""
        for prompt in (
            "❯ 1. Claude account...",
            "❯ 1. Yes",
        ):
            with self.subTest(prompt=prompt):
                self.assertEqual(
                    classify_provider_screen("claude", prompt),
                    ("registered", "unknown_screen"),
                )

    def test_claude_manual_action_has_priority_over_ready_evidence(self):
        """Catch a ready-looking Claude pane masking an update dialog."""
        pane = f'update available\n❯\u00a0Try "how do I log an error?"\n{CLAUDE_READY_FOOTER}'
        self.assertEqual(
            classify_provider_screen("claude", pane),
            ("manual_action_required", "update_dialog"),
        )


class OtherProviderReadinessTests(unittest.TestCase):
    def test_gemini_and_codex_ready_composers_are_unchanged(self):
        """Catch the Claude-specific recognition changing other provider contracts."""
        self.assertEqual(
            classify_provider_screen("gemini", "> Type your message or @path/to/file"),
            ("provider_ready", "ready_prompt"),
        )
        self.assertEqual(
            classify_provider_screen("codex", "›"),
            ("provider_ready", "ready_prompt"),
        )


if __name__ == "__main__":
    unittest.main()
