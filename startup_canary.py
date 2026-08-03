"""Private startup proof that every Team Up wrapper can answer through MCP."""

from __future__ import annotations

import secrets
import hashlib
import hmac
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
        self._nonce_digests: dict[str, bytes] = {}
        self._states: dict[str, dict] = {}

    def begin(self) -> None:
        """Queue one challenge per identity. Repeated calls are idempotent."""
        with self._lock:
            if self._started_at is not None:
                return
            started_at = self._now()
            self._started_at = started_at
            issued = []
            for identity in self._identities:
                nonce = self._nonce_factory()
                issued.append((identity, nonce))
                self._nonces[identity] = nonce
                self._nonce_digests[identity] = self._digest(nonce)
                self._states[identity] = {
                    "state": "pending",
                    "reason": "awaiting_response",
                    "timestamp": started_at,
                }
        for identity, nonce in issued:
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
        sender = message.get("sender")
        text = message.get("text")
        if not isinstance(sender, str) or not isinstance(text, str):
            return False

        _, accepted = self.consume_response(
            sender,
            text,
            message.get("channel"),
        )
        return accepted

    def consume_response(
        self,
        sender: str,
        text: str,
        channel: object,
        *,
        valid_response: bool = True,
    ) -> tuple[bool, bool]:
        """Consume any issued nonce before callers can persist it.

        Returns ``(consumed, accepted)``. A private-channel message is always
        consumed. Outside that channel, only exact or whitespace-padded issued
        nonces are consumed, leaving unrelated agent chat untouched.
        """
        if not isinstance(sender, str) or not isinstance(text, str):
            return channel == self.PRIVATE_CHANNEL, False

        with self._lock:
            self._refresh_locked()
            if self._started_at is None:
                return channel == self.PRIVATE_CHANNEL, False

            owner = self._owner_for(text)
            padded_owner = None
            if text.strip() != text:
                padded_owner = self._owner_for(text.strip())
            consumed = (
                channel == self.PRIVATE_CHANNEL
                or owner is not None
                or padded_owner is not None
            )
            if not consumed:
                return False, False

            matched_owner = owner or padded_owner
            if matched_owner is not None:
                current = self._states[matched_owner]["state"]
                if current == "passed":
                    self._set_state(matched_owner, "blocked", "replayed_nonce")
                    return True, False
                if current != "pending":
                    return True, False

            if padded_owner is not None and owner is None:
                if padded_owner != sender:
                    self._set_state(padded_owner, "blocked", "wrong_sender")
                else:
                    self._set_state(sender, "blocked", "nonce_mismatch")
                return True, False
            if owner is not None and owner != sender:
                self._set_state(owner, "blocked", "wrong_sender")
                return True, False
            if sender not in self._states:
                return True, False

            if owner != sender:
                self._set_state(sender, "blocked", "nonce_mismatch")
                return True, False
            if channel != self.PRIVATE_CHANNEL:
                self._set_state(sender, "blocked", "wrong_channel")
                return True, False
            if not valid_response:
                self._set_state(sender, "blocked", "invalid_response")
                return True, False

            self._set_state(sender, "passed", "response_verified")
            return True, True

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
        if state != "pending":
            self._nonces.pop(identity, None)

    def _owner_for(self, text: str) -> str | None:
        candidate = self._digest(text)
        for identity, expected in self._nonce_digests.items():
            if hmac.compare_digest(candidate, expected):
                return identity
        return None

    @staticmethod
    def _digest(text: str) -> bytes:
        return hashlib.sha256(text.encode("utf-8")).digest()

    @staticmethod
    def _safe_reason(reason: object) -> str:
        allowed = {
            "awaiting_response",
            "response_verified",
            "wrong_sender",
            "wrong_channel",
            "nonce_mismatch",
            "replayed_nonce",
            "invalid_response",
            "response_timeout",
            "queue_delivery_failed",
            "update_dialog",
            "trust_screen",
            "mcp_startup_failure",
            "tool_approval",
            "provider_offline",
        }
        return reason if isinstance(reason, str) and reason in allowed else "provider_unavailable"
