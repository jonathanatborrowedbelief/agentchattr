"""Classify interactive provider panes without exposing their contents."""

import re
from typing import Literal


ProviderState = Literal[
    "registered",
    "provider_ready",
    "manual_action_required",
    "offline",
]

PROVIDER_STATES = frozenset({
    "registered",
    "provider_ready",
    "manual_action_required",
    "offline",
})

REASON_CODES = frozenset({
    "unknown_screen",
    "ready_prompt",
    "update_dialog",
    "trust_screen",
    "mcp_startup_failure",
    "tool_approval",
    "provider_offline",
})

_STATE_REASONS = {
    "registered": {"unknown_screen"},
    "provider_ready": {"ready_prompt"},
    "manual_action_required": {
        "update_dialog",
        "trust_screen",
        "mcp_startup_failure",
        "tool_approval",
    },
    "offline": {"provider_offline"},
}

_READY_PROMPTS = {
    "claude": re.compile(r"(?m)^[^\S\r\n]*❯[^\S\r\n]*$"),
    "gemini": re.compile(
        r"(?mi)^[^\S\r\n]*>[^\S\r\n]*type your message or @path/to/file[^\r\n]*$"
    ),
    "codex": re.compile(r"(?m)^[^\S\r\n]*›(?:[^\S\r\n]+[^\r\n]*)?$"),
}


def is_valid_provider_report(state: str, reason_code: str) -> bool:
    """Return whether a provider report uses a safe, supported state pair."""
    return (
        state in PROVIDER_STATES
        and reason_code in REASON_CODES
        and reason_code in _STATE_REASONS.get(state, set())
    )


def classify_provider_screen(provider: str, pane_text: str) -> tuple[ProviderState, str]:
    """Return a safe readiness tuple; unrecognized screens always fail closed.

    ``pane_text`` is deliberately inspected only locally and is never returned.
    """
    text = pane_text.lower() if isinstance(pane_text, str) else ""

    if re.search(r"\b(update available|restart to update|update now)\b", text):
        return "manual_action_required", "update_dialog"
    if re.search(r"\b(trust (this |the )?(folder|files|workspace)|folder trust)\b", text):
        return "manual_action_required", "trust_screen"
    if re.search(r"\bmcp\b.{0,120}\b(failed to start|startup failed|connection refused)\b", text):
        return "manual_action_required", "mcp_startup_failure"
    if re.search(r"\b(allow|approve)\b.{0,80}\b(tool|command)\b", text):
        return "manual_action_required", "tool_approval"
    ready_prompt = _READY_PROMPTS.get(str(provider).lower())
    if ready_prompt is not None and ready_prompt.search(text):
        return "provider_ready", "ready_prompt"

    return "registered", "unknown_screen"
