"""Private startup proof that every Team Up wrapper can answer through MCP."""

from __future__ import annotations

import secrets
import threading
import time
from collections.abc import Callable, Iterable


class StartupCanary:
    """Issue one private challenge to each identity and retain only safe evidence."""

    PRIVATE_CHANNEL = "__team-up-startup-canary"

    def __init__(
        self,
        agents,
        identities: Iterable[str],
        *,
        timeout_seconds: float = 30.0,
        now: Callable[[], float] = time.time,
        nonce_factory: Callable[[], str] = lambda: secrets.token_urlsafe(32),
        provider_status: Callable[[str], tuple[str, str]] | None = None,
    ):
        self._agents = agents
        self._identities = tuple(identities)
        self._timeout_seconds = timeout_seconds
        self._now = now
        self._nonce_factory = nonce_factory
        self._provider_status = provider_status
        self._lock = threading.RLock()
        self._started_at: float | None = None
        self._nonces: dict[str, str] = {}
        self._states: dict[str, dict] = {}

    def begin(self) -> None:
        """Queue one challenge per identity. Repeated calls are idempotent."""
        with self._lock:
            if self._started_at is not None:
                return
            started_at = self._now()
            self._started_at = started_at
            for identity in self._identities:
                self._nonces[identity] = self._nonce_factory()
                self._states[identity] = {
                    "state": "pending",
                    "reason": "awaiting_response",
                    "timestamp": started_at,
                }

        for identity in self._identities:
            with self._lock:
                nonce = self._nonces[identity]
            prompt = (
                "Complete the private Team Up startup canary now. Call "
                f"chat_send(sender={identity!r}, message={nonce!r}, choices=[], "
                f"channel={self.PRIVATE_CHANNEL!r}) exactly once. "
                "Do not post, summarize, or repeat this value anywhere else."
            )
            try:
                self._agents.trigger_sync(
                    identity,
                    message="system: private startup canary",
                    channel=self.PRIVATE_CHANNEL,
                    prompt=prompt,
                )
            except Exception:
                with self._lock:
                    self._set_state(identity, "blocked", "queue_delivery_failed")

    def observe(self, message: dict) -> bool:
        """Consume a private authenticated response without persisting its text."""
        if not isinstance(message, dict):
            return False
        if message.get("channel") != self.PRIVATE_CHANNEL:
            return False

        sender = message.get("sender")
        text = message.get("text")
        if not isinstance(sender, str) or not isinstance(text, str):
            return False

        with self._lock:
            self._refresh_locked()
            if self._started_at is None:
                return False

            owner = next(
                (identity for identity, nonce in self._nonces.items() if nonce == text),
                None,
            )
            if owner is not None and owner != sender:
                self._set_state(owner, "blocked", "wrong_sender")
                return False
            if sender not in self._states:
                return False

            current = self._states[sender]["state"]
            if owner != sender:
                self._set_state(sender, "blocked", "nonce_mismatch")
                return False
            if current == "passed":
                self._set_state(sender, "blocked", "replayed_nonce")
                return False
            if current != "pending":
                return False

            self._set_state(sender, "passed", "response_verified")
            return True

    def snapshot(self) -> dict:
        """Return bounded, sanitized evidence; raw challenges never leave memory."""
        with self._lock:
            self._refresh_locked()
            agents = {
                identity: dict(self._states.get(identity, {
                    "state": "pending",
                    "reason": "not_started",
                    "timestamp": 0.0,
                }))
                for identity in self._identities
            }
            if any(item["state"] == "blocked" for item in agents.values()):
                state = "blocked"
            elif agents and all(item["state"] == "passed" for item in agents.values()):
                state = "passed"
            else:
                state = "pending"
            return {
                "state": state,
                "complete": state in {"passed", "blocked"},
                "agents": agents,
            }

    def _refresh_locked(self) -> None:
        if self._started_at is None:
            return
        now = self._now()
        if now - self._started_at > self._timeout_seconds:
            for identity, evidence in self._states.items():
                if evidence["state"] == "pending":
                    self._set_state(identity, "blocked", "response_timeout", now)

        if self._provider_status is None:
            return
        for identity, evidence in self._states.items():
            if evidence["state"] != "pending":
                continue
            try:
                provider_state, reason = self._provider_status(identity)
            except Exception:
                continue
            if provider_state == "manual_action_required":
                self._set_state(identity, "blocked", self._safe_reason(reason), now)
            elif provider_state == "offline":
                self._set_state(identity, "blocked", "provider_offline", now)

    def _set_state(
        self,
        identity: str,
        state: str,
        reason: str,
        timestamp: float | None = None,
    ) -> None:
        self._states[identity] = {
            "state": state,
            "reason": self._safe_reason(reason),
            "timestamp": self._now() if timestamp is None else timestamp,
        }

    @staticmethod
    def _safe_reason(reason: object) -> str:
        allowed = {
            "awaiting_response",
            "response_verified",
            "wrong_sender",
            "nonce_mismatch",
            "replayed_nonce",
            "response_timeout",
            "queue_delivery_failed",
            "update_dialog",
            "trust_screen",
            "mcp_startup_failure",
            "tool_approval",
            "provider_offline",
        }
        return reason if isinstance(reason, str) and reason in allowed else "provider_unavailable"
