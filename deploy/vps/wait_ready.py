#!/usr/bin/env python3
"""Poll agentchattr readiness without exposing response content."""

from __future__ import annotations

import argparse
import json
import time
import urllib.request


SERVICE_NAME = "agentchattr-team-up-v2"
TEAM_IDENTITIES = frozenset({
    "claude-lead",
    "gemini-video",
    "codex-sol",
    "codex-terra",
    "codex-luna",
})


def _server_ready(payload: object) -> bool:
    return isinstance(payload, dict) and payload.get("service") == SERVICE_NAME


def _team_ready(payload: object) -> bool:
    if not _server_ready(payload) or payload.get("ready") is not True:
        return False

    agents = payload.get("agents")
    if not isinstance(agents, dict) or set(agents) != TEAM_IDENTITIES:
        return False
    if not all(
        isinstance(status, dict)
        and status.get("online") is True
        and status.get("provider_state") == "provider_ready"
        and status.get("reason_code") == "ready_prompt"
        for status in agents.values()
    ):
        return False

    canary = payload.get("canary")
    if (
        not isinstance(canary, dict)
        or canary.get("state") != "passed"
        or canary.get("complete") is not True
    ):
        return False
    canary_agents = canary.get("agents")
    return (
        isinstance(canary_agents, dict)
        and set(canary_agents) == TEAM_IDENTITIES
        and all(
            isinstance(status, dict)
            and status.get("state") == "passed"
            and status.get("reason") == "response_verified"
            for status in canary_agents.values()
        )
    )


def wait_ready(url: str, mode: str, timeout_seconds: float) -> bool:
    deadline = time.monotonic() + max(0.0, timeout_seconds)
    validator = _server_ready if mode == "server" else _team_ready

    while True:
        remaining = max(0.0, deadline - time.monotonic())
        try:
            with urllib.request.urlopen(url, timeout=max(0.05, min(1.0, remaining))) as response:
                payload = json.load(response)
            if validator(payload):
                return True
        except Exception:
            pass

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(1.0, remaining))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--mode", choices=("server", "team"), required=True)
    parser.add_argument("--timeout-seconds", type=float, required=True)
    args = parser.parse_args()
    return 0 if wait_ready(args.url, args.mode, args.timeout_seconds) else 1


if __name__ == "__main__":
    raise SystemExit(main())
