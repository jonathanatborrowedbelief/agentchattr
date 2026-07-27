"""Memory-only, secret-safe agent lifecycle telemetry."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable


_CAPTIONS = {
    "task_queued": ("queue", "Task queued"),
    "terminal_activity": ("terminal", "Terminal activity"),
    "chat_read": ("tool", "Reading chat"),
    "response_posted": ("response", "Response posted"),
    "session_paused": ("session", "Session paused"),
    "missing_cast": ("session", "Missing session cast"),
    "external_blocker": ("blocker", "Blocked by external dependency"),
    "tests_complete": ("test", "Tests complete"),
}

_STATE_REASONS = {
    "WAITING": {"task_queued"},
    "WORKING": {"terminal_activity", "chat_read"},
    "BLOCKED": {"session_paused", "missing_cast", "external_blocker"},
    "DONE": {"response_posted", "tests_complete"},
}

_VALID_STATES = {"IDLE", *_STATE_REASONS}


def _validate_text_field(value: str, field: str, *, allow_empty: bool = False):
    if not isinstance(value, str):
        raise ValueError(f"{field} must be text")
    if not value and not allow_empty:
        raise ValueError(f"{field} is required")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError(f"{field} contains control characters")


class AgentActivityStore:
    """Tracks bounded lifecycle events without persisting caller-supplied text."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.time,
        terminal_lease_seconds: float = 8,
        max_events: int = 8,
    ):
        self._clock = clock
        self._terminal_lease_seconds = terminal_lease_seconds
        self._max_events = max_events
        self._records: dict[str, dict] = {}
        self._lock = threading.RLock()

    def mark_queued(self, name: str, channel: str = "", job_id: int = 0):
        _validate_text_field(channel, "channel", allow_empty=True)
        self._record(name, "WAITING", "task_queued")

    def mark_terminal(self, name: str, active: bool):
        _validate_text_field(name, "name")
        with self._lock:
            record = self._records.get(name)
            if not active:
                if record and record.get("terminal_until") is not None:
                    record["state"] = record.get("terminal_fallback", "IDLE")
                    record["terminal_until"] = None
                return

            record = self._get_record(name)
            if record.get("terminal_until") is None:
                fallback = record["state"] if record["state"] != "WORKING" else "IDLE"
                record["terminal_fallback"] = fallback
            record["terminal_until"] = self._clock() + self._terminal_lease_seconds
            self._append_event(record, "WORKING", "terminal_activity")
            record["state"] = "WORKING"

    def mark_tool(self, name: str, reason_code: str):
        self._record(name, "WORKING", reason_code)

    def mark_blocked(self, name: str, reason_code: str):
        self._record(name, "BLOCKED", reason_code)

    def mark_done(self, name: str, reason_code: str):
        self._record(name, "DONE", reason_code)

    def mark_activity(self, name: str, state: str, reason_code: str):
        """Record an allowlisted externally reported lifecycle transition."""
        if state not in ("WORKING", "BLOCKED", "DONE"):
            raise ValueError("state is not allowed")
        self._record(name, state, reason_code)

    def snapshot(self, name: str) -> dict:
        _validate_text_field(name, "name")
        with self._lock:
            record = self._records.get(name)
            if not record:
                return {"state": "IDLE", "event": None, "recent_events": []}
            self._expire_terminal(record)
            events = [dict(event) for event in record["recent_events"]]
            return {
                "state": record["state"],
                "event": dict(events[-1]) if events else None,
                "recent_events": events,
            }

    def migrate_identity(self, old: str, new: str):
        _validate_text_field(old, "old name")
        _validate_text_field(new, "new name")
        if old == new:
            return
        with self._lock:
            source = self._records.pop(old, None)
            if not source:
                return
            target = self._records.get(new)
            if not target:
                self._records[new] = source
                return
            combined = sorted(
                [*target["recent_events"], *source["recent_events"]],
                key=lambda event: event["time"],
            )[-self._max_events :]
            source["recent_events"] = combined
            self._records[new] = source

    def purge_identity(self, name: str):
        _validate_text_field(name, "name")
        with self._lock:
            self._records.pop(name, None)

    def _get_record(self, name: str) -> dict:
        return self._records.setdefault(
            name,
            {
                "state": "IDLE",
                "recent_events": [],
                "terminal_until": None,
                "terminal_fallback": "IDLE",
            },
        )

    def _record(self, name: str, state: str, reason_code: str):
        _validate_text_field(name, "name")
        if state not in _VALID_STATES:
            raise ValueError("state is not allowed")
        if reason_code not in _CAPTIONS:
            raise ValueError("reason is not allowed")
        if reason_code not in _STATE_REASONS.get(state, set()):
            raise ValueError("reason is not allowed for state")

        with self._lock:
            record = self._get_record(name)
            record["terminal_until"] = None
            record["terminal_fallback"] = "IDLE"
            self._append_event(record, state, reason_code)
            record["state"] = state

    def _append_event(self, record: dict, state: str, reason_code: str):
        kind, caption = _CAPTIONS[reason_code]
        now = self._clock()
        events = record["recent_events"]
        if events and events[-1]["state"] == state and events[-1]["reason"] == reason_code:
            events[-1]["time"] = now
            events[-1]["count"] += 1
            return
        events.append(
            {
                "state": state,
                "kind": kind,
                "reason": reason_code,
                "text": caption,
                "time": now,
                "count": 1,
            }
        )
        del events[: max(0, len(events) - self._max_events)]

    def _expire_terminal(self, record: dict):
        deadline = record.get("terminal_until")
        if deadline is not None and self._clock() > deadline:
            record["state"] = record.get("terminal_fallback", "IDLE")
            record["terminal_until"] = None
