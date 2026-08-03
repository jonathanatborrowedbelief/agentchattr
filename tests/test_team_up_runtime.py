import asyncio
import json
import os
import shlex
import shutil
import subprocess
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from wrapper import _merge_launch_args, _resolve_mcp_inject, _resolve_provider


class StartupCanaryTests(unittest.TestCase):
    IDENTITIES = (
        "claude-lead",
        "gemini-video",
        "codex-sol",
        "codex-terra",
        "codex-luna",
    )

    def _make_canary(self, root, *, now=None, provider_status=None, nonces=None):
        from agents import AgentTrigger
        from startup_canary import StartupCanary

        nonce_values = iter(nonces or [f"nonce-{name}" for name in self.IDENTITIES])
        trigger = AgentTrigger(SimpleNamespace(), data_dir=str(root))
        canary = StartupCanary(
            trigger,
            self.IDENTITIES,
            timeout_seconds=10,
            now=now or (lambda: 100.0),
            nonce_factory=lambda: next(nonce_values),
            provider_status=provider_status,
        )
        return canary

    def test_all_five_agents_must_answer_through_the_production_queue_path(self):
        from startup_canary import StartupCanary

        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            canary = self._make_canary(root)
            canary.begin()

            for identity in self.IDENTITIES:
                entries = [
                    json.loads(line)
                    for line in (root / f"{identity}_queue.jsonl").read_text("utf-8").splitlines()
                ]
                self.assertEqual(len(entries), 1)
                self.assertEqual(entries[0]["channel"], StartupCanary.PRIVATE_CHANNEL)
                self.assertIn(f"nonce-{identity}", entries[0]["prompt"])
                canary.observe({
                    "sender": identity,
                    "text": f"nonce-{identity}",
                    "channel": StartupCanary.PRIVATE_CHANNEL,
                })

            snapshot = canary.snapshot()

        self.assertEqual(snapshot["state"], "passed")
        self.assertTrue(snapshot["complete"])
        self.assertTrue(all(item["state"] == "passed" for item in snapshot["agents"].values()))
        serialized = json.dumps(snapshot)
        self.assertNotIn("nonce-", serialized)

    def test_nonce_from_the_wrong_authenticated_sender_fails_closed(self):
        from startup_canary import StartupCanary

        with tempfile.TemporaryDirectory() as temporary_dir:
            canary = self._make_canary(Path(temporary_dir))
            canary.begin()
            canary.observe({
                "sender": "codex-terra",
                "text": "nonce-codex-sol",
                "channel": StartupCanary.PRIVATE_CHANNEL,
            })

        snapshot = canary.snapshot()
        self.assertEqual(snapshot["state"], "blocked")
        self.assertEqual(
            snapshot["agents"]["codex-sol"],
            {"state": "blocked", "reason": "wrong_sender", "timestamp": 100.0},
        )

    def test_wrong_or_replayed_nonce_fails_closed(self):
        from startup_canary import StartupCanary

        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            wrong = self._make_canary(root / "wrong")
            wrong.begin()
            wrong.observe({
                "sender": "codex-sol",
                "text": "not-the-issued-value",
                "channel": StartupCanary.PRIVATE_CHANNEL,
            })
            self.assertEqual(
                wrong.snapshot()["agents"]["codex-sol"]["reason"],
                "nonce_mismatch",
            )

            replayed = self._make_canary(root / "replayed")
            replayed.begin()
            response = {
                "sender": "codex-sol",
                "text": "nonce-codex-sol",
                "channel": StartupCanary.PRIVATE_CHANNEL,
            }
            replayed.observe(response)
            replayed.observe(response)
            self.assertEqual(
                replayed.snapshot()["agents"]["codex-sol"]["reason"],
                "replayed_nonce",
            )

    def test_terminal_states_erase_raw_nonces_but_digest_still_catches_replay(self):
        from startup_canary import StartupCanary

        def make_one(root, nonce, now=lambda: 100.0):
            from agents import AgentTrigger

            return StartupCanary(
                AgentTrigger(SimpleNamespace(), data_dir=str(root)),
                ("codex-sol",),
                timeout_seconds=10,
                now=now,
                nonce_factory=lambda: nonce,
            )

        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)

            passed = make_one(root / "passed", "pass-raw-nonce")
            passed.begin()
            self.assertTrue(passed.observe({
                "sender": "codex-sol",
                "text": "pass-raw-nonce",
                "channel": StartupCanary.PRIVATE_CHANNEL,
            }))
            self.assertEqual(passed._nonces, {})
            self.assertFalse(passed.observe({
                "sender": "codex-sol",
                "text": "pass-raw-nonce",
                "channel": StartupCanary.PRIVATE_CHANNEL,
            }))
            self.assertEqual(passed._nonces, {})
            self.assertEqual(
                passed.snapshot()["agents"]["codex-sol"]["reason"],
                "replayed_nonce",
            )

            blocked = make_one(root / "blocked", "block-raw-nonce")
            blocked.begin()
            blocked.observe({
                "sender": "codex-sol",
                "text": "incorrect",
                "channel": StartupCanary.PRIVATE_CHANNEL,
            })
            self.assertEqual(blocked._nonces, {})

            clock = [100.0]
            timed_out = make_one(
                root / "timeout",
                "timeout-raw-nonce",
                now=lambda: clock[0],
            )
            timed_out.begin()
            clock[0] = 111.0
            timed_out.snapshot()
            self.assertEqual(timed_out._nonces, {})

        for raw_nonce, canary in (
            ("pass-raw-nonce", passed),
            ("block-raw-nonce", blocked),
            ("timeout-raw-nonce", timed_out),
        ):
            self.assertNotIn(raw_nonce, repr(canary.__dict__))

    def test_timeout_and_manual_action_results_are_sanitized_blockers(self):
        from startup_canary import StartupCanary

        clock = [100.0]
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            timed_out = self._make_canary(root / "timeout", now=lambda: clock[0])
            timed_out.begin()
            clock[0] = 111.0
            timeout_snapshot = timed_out.snapshot()

            provider_reports = {
                identity: ("provider_ready", "ready_prompt")
                for identity in self.IDENTITIES
            }
            manual = self._make_canary(
                root / "manual",
                provider_status=lambda name: provider_reports[name],
            )
            manual.begin()
            provider_reports["gemini-video"] = ("manual_action_required", "tool_approval")
            manual_snapshot = manual.snapshot()

        self.assertEqual(timeout_snapshot["state"], "blocked")
        self.assertTrue(all(
            item["reason"] == "response_timeout"
            for item in timeout_snapshot["agents"].values()
        ))
        self.assertEqual(manual_snapshot["state"], "blocked")
        self.assertEqual(
            manual_snapshot["agents"]["gemini-video"]["reason"],
            "tool_approval",
        )

    def test_server_restart_creates_a_fresh_unpassed_generation(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            first = self._make_canary(
                root / "first",
                nonces=[f"old-{name}" for name in self.IDENTITIES],
            )
            first.begin()
            for identity in self.IDENTITIES:
                first.observe({
                    "sender": identity,
                    "text": f"old-{identity}",
                    "channel": first.PRIVATE_CHANNEL,
                })
            self.assertEqual(first.snapshot()["state"], "passed")

            restarted = self._make_canary(
                root / "restarted",
                nonces=[f"new-{name}" for name in self.IDENTITIES],
            )
            restarted.begin()
            restarted_snapshot = restarted.snapshot()

        self.assertEqual(restarted_snapshot["state"], "pending")
        self.assertTrue(all(
            item["reason"] == "awaiting_response"
            for item in restarted_snapshot["agents"].values()
        ))
        self.assertNotIn("old-", json.dumps(restarted_snapshot))
        self.assertNotIn("new-", json.dumps(restarted_snapshot))

    def test_authenticated_chat_send_is_consumed_without_store_or_mcp_leakage(self):
        import mcp_bridge
        from registry import RuntimeRegistry
        from startup_canary import StartupCanary
        from store import MessageStore

        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            registry = RuntimeRegistry(data_dir=str(root / "registry"))
            registry.seed({"codex-sol": {"dedicated_identity": True}})
            registered = registry.register("codex-sol")
            store = MessageStore(str(root / "messages.jsonl"))
            canary = mock.Mock()
            canary.consume_response.return_value = (True, True)
            ctx = SimpleNamespace(
                request_context=SimpleNamespace(
                    request=SimpleNamespace(
                        headers={"authorization": f"Bearer {registered['token']}"},
                    ),
                ),
            )
            with (
                mock.patch.object(mcp_bridge, "registry", registry),
                mock.patch.object(mcp_bridge, "store", store),
                mock.patch.object(mcp_bridge, "startup_canary", canary),
                mock.patch.object(mcp_bridge, "activity_store", None),
            ):
                result = mcp_bridge.chat_send(
                    sender="forged-name",
                    message="raw-private-nonce",
                    choices=[],
                    channel=StartupCanary.PRIVATE_CHANNEL,
                    ctx=ctx,
                )

        self.assertEqual(result, "Startup canary response accepted.")
        canary.consume_response.assert_called_once_with(
            "codex-sol",
            "raw-private-nonce",
            StartupCanary.PRIVATE_CHANNEL,
            valid_response=True,
        )
        self.assertEqual(store.get_recent(10), [])
        self.assertNotIn("raw-private-nonce", result)

    def test_canary_nonce_sent_to_general_is_consumed_before_history_persistence(self):
        import mcp_bridge
        from registry import RuntimeRegistry
        from store import MessageStore

        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            registry = RuntimeRegistry(data_dir=str(root / "registry"))
            registry.seed({"codex-sol": {"dedicated_identity": True}})
            registered = registry.register("codex-sol")
            store = MessageStore(str(root / "messages.jsonl"))
            canary = self._make_canary(
                root / "canary",
                nonces=["one", "two", "raw-general-nonce", "four", "five"],
            )
            canary.begin()
            ctx = SimpleNamespace(request_context=SimpleNamespace(request=SimpleNamespace(
                headers={"authorization": f"Bearer {registered['token']}"},
            )))
            with (
                mock.patch.object(mcp_bridge, "registry", registry),
                mock.patch.object(mcp_bridge, "store", store),
                mock.patch.object(mcp_bridge, "startup_canary", canary),
                mock.patch.object(mcp_bridge, "activity_store", None),
            ):
                result = mcp_bridge.chat_send(
                    sender="codex-sol",
                    message="raw-general-nonce",
                    choices=[],
                    channel="general",
                    ctx=ctx,
                )

        self.assertEqual(result, "Error: startup canary response rejected.")
        self.assertEqual(store.get_recent(10), [])
        self.assertNotIn("raw-general-nonce", result)
        self.assertEqual(
            canary.snapshot()["agents"]["codex-sol"]["reason"],
            "wrong_channel",
        )

    def test_canary_nonce_sent_to_job_is_consumed_before_job_persistence(self):
        import mcp_bridge
        from jobs import JobStore
        from registry import RuntimeRegistry
        from store import MessageStore

        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            registry = RuntimeRegistry(data_dir=str(root / "registry"))
            registry.seed({"codex-sol": {"dedicated_identity": True}})
            registered = registry.register("codex-sol")
            store = MessageStore(str(root / "messages.jsonl"))
            jobs = JobStore(str(root / "jobs.json"))
            job = jobs.create(
                title="Canary leak check",
                job_type="job",
                channel="general",
                created_by="user",
            )
            canary = self._make_canary(
                root / "canary",
                nonces=["one", "two", "raw-job-nonce", "four", "five"],
            )
            canary.begin()
            ctx = SimpleNamespace(request_context=SimpleNamespace(request=SimpleNamespace(
                headers={"authorization": f"Bearer {registered['token']}"},
            )))
            with (
                mock.patch.object(mcp_bridge, "registry", registry),
                mock.patch.object(mcp_bridge, "store", store),
                mock.patch.object(mcp_bridge, "jobs", jobs),
                mock.patch.object(mcp_bridge, "startup_canary", canary),
                mock.patch.object(mcp_bridge, "activity_store", None),
                mock.patch.object(mcp_bridge, "router", None),
                mock.patch.object(mcp_bridge, "agents", None),
            ):
                result = mcp_bridge.chat_send(
                    sender="codex-sol",
                    message="raw-job-nonce",
                    choices=[],
                    channel="general",
                    job_id=job["id"],
                    ctx=ctx,
                )

        self.assertEqual(result, "Error: startup canary response rejected.")
        self.assertEqual(jobs.get_messages(job["id"]), [])
        self.assertNotIn("raw-job-nonce", result)

    def test_padded_nonce_is_consumed_but_rejected_as_not_exact(self):
        import mcp_bridge
        from registry import RuntimeRegistry
        from store import MessageStore
        from startup_canary import StartupCanary

        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            registry = RuntimeRegistry(data_dir=str(root / "registry"))
            registry.seed({"codex-sol": {"dedicated_identity": True}})
            registered = registry.register("codex-sol")
            store = MessageStore(str(root / "messages.jsonl"))
            canary = self._make_canary(
                root / "canary",
                nonces=["one", "two", "raw-padded-nonce", "four", "five"],
            )
            canary.begin()
            ctx = SimpleNamespace(request_context=SimpleNamespace(request=SimpleNamespace(
                headers={"authorization": f"Bearer {registered['token']}"},
            )))
            with (
                mock.patch.object(mcp_bridge, "registry", registry),
                mock.patch.object(mcp_bridge, "store", store),
                mock.patch.object(mcp_bridge, "startup_canary", canary),
                mock.patch.object(mcp_bridge, "activity_store", None),
            ):
                result = mcp_bridge.chat_send(
                    sender="codex-sol",
                    message=" raw-padded-nonce ",
                    choices=[],
                    channel=StartupCanary.PRIVATE_CHANNEL,
                    ctx=ctx,
                )

        self.assertEqual(result, "Error: startup canary response rejected.")
        self.assertEqual(store.get_recent(10), [])
        self.assertEqual(
            canary.snapshot()["agents"]["codex-sol"]["reason"],
            "nonce_mismatch",
        )

    def test_rest_send_cannot_bypass_the_authenticated_chat_send_canary_path(self):
        import app
        from registry import RuntimeRegistry
        from startup_canary import StartupCanary

        class Request:
            headers = {}

            async def json(self):
                return {
                    "text": "raw-private-nonce",
                    "channel": StartupCanary.PRIVATE_CHANNEL,
                }

        with tempfile.TemporaryDirectory() as temporary_dir:
            registry = RuntimeRegistry(data_dir=temporary_dir)
            registry.seed({"codex-sol": {"dedicated_identity": True}})
            registered = registry.register("codex-sol")
            request = Request()
            request.headers = {
                "authorization": f"Bearer {registered['token']}",
            }
            canary = mock.Mock()
            canary.observe.return_value = True
            with (
                mock.patch.object(app, "registry", registry),
                mock.patch.object(app, "startup_canary", canary),
            ):
                response = asyncio.run(app.api_send(request))

        self.assertEqual(response.status_code, 400)
        self.assertEqual(json.loads(response.body), {"error": "private channel is reserved"})
        canary.observe.assert_not_called()

    def test_private_channel_is_absent_from_mcp_reads_channels_and_summaries(self):
        import mcp_bridge
        from startup_canary import StartupCanary
        from store import MessageStore
        from summaries import SummaryStore

        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            store = MessageStore(str(root / "messages.jsonl"))
            store.add("ben", "visible", channel="general")
            summaries = SummaryStore(str(root / "summaries.json"))
            with (
                mock.patch.object(mcp_bridge, "store", store),
                mock.patch.object(mcp_bridge, "summaries", summaries),
                mock.patch.object(
                    mcp_bridge,
                    "room_settings",
                    {"channels": ["general", StartupCanary.PRIVATE_CHANNEL]},
                ),
                mock.patch.object(mcp_bridge, "registry", None),
                mock.patch.object(mcp_bridge, "activity_store", None),
            ):
                all_messages = mcp_bridge.chat_read(limit=10)
                private_messages = mcp_bridge.chat_read(
                    limit=10,
                    channel=StartupCanary.PRIVATE_CHANNEL,
                )
                channels = mcp_bridge.chat_channels()
                summary_result = mcp_bridge.chat_summary(
                    "write",
                    "ben",
                    text="raw-private-nonce",
                    channel=StartupCanary.PRIVATE_CHANNEL,
                )

        self.assertIn("visible", all_messages)
        self.assertEqual(private_messages, "")
        self.assertEqual(json.loads(channels), ["general"])
        self.assertEqual(summary_result, "Error: private channel is reserved.")
        self.assertIsNone(summaries.get(StartupCanary.PRIVATE_CHANNEL))


class ProviderReadinessClassifierTests(unittest.TestCase):
    def test_classifies_a_usable_provider_prompt(self):
        from provider_readiness import classify_provider_screen

        self.assertEqual(
            classify_provider_screen("codex", "› Describe the task you want to work on"),
            ("provider_ready", "ready_prompt"),
        )

    def test_classifies_captured_provider_specific_composers(self):
        from provider_readiness import classify_provider_screen

        cases = {
            "claude": "Claude Code\n❯\u00a0\n  ? for shortcuts",
            "gemini": "Gemini\n> Type your message or @path/to/file\nUsing 1 GEMINI.md file",
            "codex": "Codex\n› <composer placeholder>\n  ? for shortcuts",
        }
        for provider, pane_text in cases.items():
            with self.subTest(provider=provider):
                self.assertEqual(
                    classify_provider_screen(provider, pane_text),
                    ("provider_ready", "ready_prompt"),
                )

    def test_provider_composers_do_not_cross_classify(self):
        from provider_readiness import classify_provider_screen

        self.assertEqual(
            classify_provider_screen("gemini", "❯\u00a0"),
            ("registered", "unknown_screen"),
        )
        self.assertEqual(
            classify_provider_screen("claude", "> Type your message or @path/to/file"),
            ("registered", "unknown_screen"),
        )

    def test_classifies_known_manual_action_blockers_without_returning_pane_text(self):
        from provider_readiness import classify_provider_screen

        cases = {
            "An update is available. Restart to update now.": "update_dialog",
            "Do you trust the files in this folder? (y/N)": "trust_screen",
            "MCP server agentchattr failed to start: connection refused": "mcp_startup_failure",
            "Allow this tool to run? [y/N]": "tool_approval",
        }
        for pane_text, expected_reason in cases.items():
            with self.subTest(reason=expected_reason):
                state, reason = classify_provider_screen("codex", pane_text)
                self.assertEqual(state, "manual_action_required")
                self.assertEqual(reason, expected_reason)
                self.assertNotEqual(reason, pane_text)

    def test_unknown_screen_fails_closed_as_registered(self):
        from provider_readiness import classify_provider_screen

        pane_text = "ACCESS_TOKEN=provider-secret-9fcd unexpected terminal banner"
        self.assertEqual(
            classify_provider_screen("codex", pane_text),
            ("registered", "unknown_screen"),
        )


class TeamUpRuntimeTests(unittest.TestCase):
    def test_team_up_agents_are_the_only_dedicated_identities(self):
        from config_loader import load_config

        config = load_config(Path(__file__).parents[1])

        self.assertEqual(
            {
                name
                for name, agent_config in config["agents"].items()
                if agent_config.get("dedicated_identity")
            },
            {
                "claude-lead",
                "gemini-video",
                "codex-sol",
                "codex-terra",
                "codex-luna",
            },
        )

    def test_dedicated_identity_reclaims_its_exact_base_during_grace_window(self):
        from registry import RuntimeRegistry

        with tempfile.TemporaryDirectory() as temporary_dir:
            registry = RuntimeRegistry(data_dir=temporary_dir)
            registry.seed(
                {
                    "codex-sol": {
                        "label": "Codex Sol",
                        "dedicated_identity": True,
                    },
                }
            )

            first = registry.register("codex-sol")
            registry.deregister(first["name"])
            restarted = registry.register("codex-sol")

        self.assertEqual(first["name"], "codex-sol")
        self.assertEqual(restarted["name"], "codex-sol")

    def test_second_live_dedicated_registration_returns_http_409(self):
        import app as app_module
        from registry import RuntimeRegistry

        class RegisterRequest:
            async def json(self):
                return {"base": "codex-sol"}

        with tempfile.TemporaryDirectory() as temporary_dir:
            registry = RuntimeRegistry(data_dir=temporary_dir)
            registry.seed({"codex-sol": {"dedicated_identity": True}})
            registry.register("codex-sol")
            with mock.patch.object(app_module, "registry", registry):
                response = asyncio.run(app_module.register_agent(RegisterRequest()))

        self.assertEqual(response.status_code, 409)
        self.assertEqual(json.loads(response.body), {"error": "identity already live: codex-sol"})

    def test_wrapper_rejects_a_suffix_for_a_dedicated_identity(self):
        from wrapper import _register_configured_identity

        with mock.patch(
            "wrapper._register_instance",
            return_value={"name": "codex-sol-2", "token": "test-token"},
        ):
            with self.assertRaisesRegex(RuntimeError, "codex-sol-2"):
                _register_configured_identity(
                    8300,
                    "codex-sol",
                    {"dedicated_identity": True},
                )

    def test_dedicated_heartbeat_keeps_the_exact_identity_after_rename_attempts(self):
        import app as app_module
        from registry import RuntimeRegistry
        from wrapper import _resolve_heartbeat_identity

        class HeartbeatRequest:
            def __init__(self, token: str):
                self.headers = {"authorization": f"Bearer {token}"}

            async def json(self):
                raise ValueError("plain heartbeat")

        with tempfile.TemporaryDirectory() as temporary_dir:
            registry = RuntimeRegistry(data_dir=temporary_dir)
            registry.seed({"codex-sol": {"dedicated_identity": True}})
            registered = registry.register("codex-sol")

            self.assertEqual(
                registry.claim("codex-sol", "codex-sol-2"),
                "Dedicated identity must remain: codex-sol",
            )
            self.assertEqual(
                registry.rename("codex-sol", "codex-sol-2"),
                "Dedicated identity must remain: codex-sol",
            )

            with mock.patch.object(app_module, "registry", registry):
                heartbeat = asyncio.run(
                    app_module.heartbeat(
                        "codex-sol",
                        HeartbeatRequest(registered["token"]),
                    )
                )

        payload = heartbeat
        self.assertEqual(payload["name"], "codex-sol")
        self.assertEqual(
            _resolve_heartbeat_identity(
                "codex-sol",
                {"dedicated_identity": True},
                "codex-sol",
                payload,
            ),
            "codex-sol",
        )
        with self.assertRaisesRegex(RuntimeError, "codex-sol-2"):
            _resolve_heartbeat_identity(
                "codex-sol",
                {"dedicated_identity": True},
                "codex-sol",
                {"name": "codex-sol-2"},
            )

    def test_generic_multi_instance_registration_keeps_suffixes_and_reservations(self):
        from registry import RuntimeRegistry

        with tempfile.TemporaryDirectory() as temporary_dir:
            registry = RuntimeRegistry(data_dir=temporary_dir)
            registry.seed({"codex": {"label": "Codex"}})

            first = registry.register("codex")
            second = registry.register("codex")
            registry.deregister(second["name"])
            third = registry.register("codex")

        self.assertEqual(first["name"], "codex")
        self.assertEqual(second["name"], "codex-2")
        self.assertEqual(third["name"], "codex-3")

    def test_provider_state_is_authenticated_and_heartbeat_does_not_change_it(self):
        import app as app_module
        from registry import RuntimeRegistry

        class HeartbeatRequest:
            def __init__(self, token):
                self.headers = {"authorization": f"Bearer {token}"}

            async def json(self):
                raise ValueError("plain heartbeat")

        with tempfile.TemporaryDirectory() as temporary_dir:
            registry = RuntimeRegistry(data_dir=temporary_dir)
            registry.seed({"codex-sol": {"dedicated_identity": True}})
            registered = registry.register("codex-sol")

            self.assertEqual(registered["provider_state"], "registered")
            self.assertTrue(registry.report_provider_state(
                registered["token"], "provider_ready", "ready_prompt",
            ))
            self.assertFalse(registry.report_provider_state(
                "wrong-token", "provider_ready", "ready_prompt",
            ))
            self.assertFalse(registry.report_provider_state(
                registered["token"], "provider_ready", "unknown_screen",
            ))

            self.assertEqual(
                registry.get_instance("codex-sol")["provider_state"],
                "provider_ready",
            )
            with mock.patch.object(app_module, "registry", registry):
                response = asyncio.run(app_module.heartbeat(
                    "codex-sol", HeartbeatRequest(registered["token"]),
                ))
            self.assertEqual(response["name"], "codex-sol")
            self.assertEqual(
                registry.get_instance("codex-sol")["provider_state"],
                "provider_ready",
            )

    def test_provider_state_endpoint_rejects_spoofed_sender_and_unknown_values(self):
        import app as app_module
        from registry import RuntimeRegistry

        class ProviderStateRequest:
            def __init__(self, token, body):
                self.headers = {"authorization": f"Bearer {token}"}
                self._body = body

            async def json(self):
                return self._body

        with tempfile.TemporaryDirectory() as temporary_dir:
            registry = RuntimeRegistry(data_dir=temporary_dir)
            registry.seed({"codex-sol": {"dedicated_identity": True}})
            registered = registry.register("codex-sol")
            with mock.patch.object(app_module, "registry", registry):
                spoofed = asyncio.run(app_module.report_provider_state(
                    "codex-terra",
                    ProviderStateRequest(
                        registered["token"],
                        {"state": "provider_ready", "reason_code": "ready_prompt"},
                    ),
                ))
                invalid = asyncio.run(app_module.report_provider_state(
                    "codex-sol",
                    ProviderStateRequest(
                        registered["token"],
                        {"state": "provider_ready", "reason_code": "pane secret"},
                    ),
                ))

        self.assertEqual(spoofed.status_code, 403)
        self.assertEqual(invalid.status_code, 400)

    def test_stable_agents_declare_control_root_instruction_files(self):
        from config_loader import load_config

        config = load_config(Path(__file__).parents[1])
        expected = {
            "claude-lead": "Claude.md",
            "gemini-video": "Gemini.md",
            "codex-luna": "Codex.md",
            "codex-terra": "Codex.md",
            "codex-sol": "Codex.md",
        }

        self.assertEqual(
            {
                name: config["agents"][name].get("instructions_file")
                for name in expected
            },
            expected,
        )
        self.assertEqual(config["agents"]["claude-lead"].get("inject_delay"), 1.0)
        self.assertEqual(
            config["agents"]["claude-lead"].get("launch_args"),
            [
                "--model",
                "opus",
                "--effort",
                "high",
                "--permission-mode",
                "auto",
            ],
        )

    def test_dedicated_codex_launches_disable_unrelated_optional_mcps(self):
        from config_loader import load_config

        config = load_config(Path(__file__).parents[1])
        expected_tail = [
            "-c",
            "mcp_servers.magic.enabled=false",
            "-c",
            "mcp_servers.apify.enabled=false",
        ]

        for identity in ("codex-luna", "codex-terra", "codex-sol"):
            with self.subTest(identity=identity):
                self.assertEqual(
                    _merge_launch_args(config["agents"][identity], [])[-4:],
                    expected_tail,
                )
        self.assertNotIn(
            "mcp_servers.magic.enabled=false",
            _merge_launch_args(config["agents"]["codex"], []),
        )

    def test_dedicated_codex_injection_waits_for_multiline_paste(self):
        from config_loader import load_config

        config = load_config(Path(__file__).parents[1])

        self.assertEqual(
            {
                identity: config["agents"][identity].get("inject_delay")
                for identity in ("codex-luna", "codex-terra", "codex-sol")
            },
            {
                "codex-luna": 1.0,
                "codex-terra": 1.0,
                "codex-sol": 1.0,
            },
        )
        self.assertIsNone(config["agents"]["codex"].get("inject_delay"))

    def test_claude_lead_injected_config_excludes_project_mcps(self):
        from config_loader import load_config
        from wrapper import _build_provider_launch

        config = load_config(Path(__file__).parents[1])
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            project_dir = root / "project"
            project_dir.mkdir()
            (project_dir / ".mcp.json").write_text(
                json.dumps({
                    "mcpServers": {
                        "magic": {"command": "optional-project-mcp"},
                    },
                }),
                encoding="utf-8",
            )
            _, _, _, settings_path = _build_provider_launch(
                "claude-lead",
                config["agents"]["claude-lead"],
                "claude-lead",
                root / "data",
                None,
                [],
                {},
                token="test-token",
                mcp_cfg=config["mcp"],
                project_dir=project_dir,
            )
            injected = json.loads(settings_path.read_text("utf-8"))

        self.assertEqual(set(injected["mcpServers"]), {"agentchattr"})

    def test_provider_alias_reuses_builtin_mcp_defaults(self):
        cfg = {"provider": "codex"}

        self.assertEqual(_resolve_provider("codex-sol", cfg), "codex")
        self.assertEqual(_resolve_mcp_inject("codex", cfg)["mcp_inject"], "proxy_flag")

    def test_config_launch_args_precede_runtime_extras(self):
        args = _merge_launch_args(
            {"launch_args": ["--model", "gpt-5.6-sol"]},
            ["-c", "model_reasoning_effort=high"],
        )
        self.assertEqual(
            args,
            [
                "--model",
                "gpt-5.6-sol",
                "-c",
                "model_reasoning_effort=high",
            ],
        )

    def test_runtime_model_override_replaces_configured_model(self):
        configured = {"launch_args": ["--model", "gemini-2.5-pro"]}

        self.assertEqual(
            _merge_launch_args(configured, []),
            ["--model", "gemini-2.5-pro"],
        )
        self.assertEqual(
            _merge_launch_args(configured, ["--model", "gemini-2.5-flash"]),
            ["--model", "gemini-2.5-flash"],
        )

    def test_runtime_env_file_override_replaces_configured_source(self):
        from wrapper import _select_env_file

        self.assertEqual(
            _select_env_file("~/shared.env", None),
            "~/shared.env",
        )
        self.assertEqual(
            _select_env_file("~/shared.env", "~/working-video.env"),
            "~/working-video.env",
        )

    def test_env_loader(self):
        from wrapper import _load_selected_env

        with tempfile.TemporaryDirectory(dir=Path.home()) as temporary_dir:
            env_file = Path(temporary_dir) / ".env.master"
            env_file.write_text(
                "GEMINI_API_KEY=file-secret\n"
                "export OTHER_API_KEY=other-secret\n"
                "UNRELATED_KEY=unrelated-secret\n",
                encoding="utf-8",
            )
            home_relative = "~/" + str(env_file.relative_to(Path.home()))

            overridden = _load_selected_env(
                env_file=home_relative,
                keys=["GEMINI_API_KEY"],
                environ={"GEMINI_API_KEY": "inherited-secret"},
            )
            self.assertEqual(overridden, {"GEMINI_API_KEY": "file-secret"})

            loaded = _load_selected_env(
                env_file=home_relative,
                keys=["GEMINI_API_KEY", "OTHER_API_KEY"],
                environ={},
            )
            self.assertEqual(set(loaded), {"GEMINI_API_KEY", "OTHER_API_KEY"})

            blank_file = Path(temporary_dir) / "blank.env"
            blank_file.write_text("GEMINI_API_KEY=\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "GEMINI_API_KEY") as blank_error:
                _load_selected_env(
                    env_file=str(blank_file),
                    keys=["GEMINI_API_KEY"],
                    environ={},
                )
            self.assertNotIn("file-secret", str(blank_error.exception))

            with self.assertRaisesRegex(ValueError, "MISSING_API_KEY") as missing_error:
                _load_selected_env(
                    env_file=home_relative,
                    keys=["MISSING_API_KEY"],
                    environ={},
                )
            self.assertNotIn("file-secret", str(missing_error.exception))

            fallback = _load_selected_env(
                env_file=str(Path(temporary_dir) / "unavailable.env"),
                keys=["GEMINI_API_KEY"],
                environ={"GEMINI_API_KEY": "inherited-fallback"},
            )
            self.assertEqual(fallback, {"GEMINI_API_KEY": "inherited-fallback"})

            with self.assertRaisesRegex(ValueError, "Unable to read environment file"):
                _load_selected_env(
                    env_file=str(Path(temporary_dir) / "unavailable.env"),
                    keys=["GEMINI_API_KEY"],
                    environ={"GEMINI_API_KEY": "inherited-fallback"},
                    allow_inherited_fallback=False,
                )

            with self.assertRaisesRegex(ValueError, "GEMINI_API_KEY"):
                _load_selected_env(
                    env_file=str(blank_file),
                    keys=["GEMINI_API_KEY"],
                    environ={"GEMINI_API_KEY": "inherited-fallback"},
                    allow_inherited_fallback=False,
                )

    def test_configured_credential_keys_are_stripped_from_every_parent(self):
        from wrapper import _configured_credential_keys

        config = {
            "agents": {
                "claude-lead": {},
                "gemini-video": {"env_keys": ["GEMINI_API_KEY"]},
                "codex-sol": {"env_keys": ["CODEX_PRIVATE_KEY"]},
                "minimax": {"api_key_env": "MINIMAX_API_KEY"},
            }
        }

        self.assertEqual(
            _configured_credential_keys(config),
            {"GEMINI_API_KEY", "CODEX_PRIVATE_KEY", "MINIMAX_API_KEY"},
        )

    def test_failed_queue_injection_preserves_batch_for_retry(self):
        import wrapper

        class StopWatcher(BaseException):
            pass

        with tempfile.TemporaryDirectory() as temporary_dir:
            queue_file = Path(temporary_dir) / "codex-sol_queue.jsonl"
            queue_file.write_text(
                '{"channel":"general","prompt":"RETRY_ME"}\n',
                encoding="utf-8",
            )
            with (
                mock.patch("wrapper._fetch_role", return_value="Integrator"),
                mock.patch("wrapper._fetch_active_rules", return_value=None),
                mock.patch(
                    "wrapper.time.sleep",
                    side_effect=[None, StopWatcher()],
                ),
            ):
                with self.assertRaises(StopWatcher):
                    wrapper._queue_watcher(
                        lambda: ("codex-sol", queue_file),
                        mock.Mock(side_effect=RuntimeError("tmux unavailable")),
                        agent_name="codex-sol",
                    )

            inflight = Path(f"{queue_file}.inflight")
            self.assertTrue(inflight.exists())
            self.assertIn("RETRY_ME", inflight.read_text("utf-8"))

    def test_successful_queue_retry_acknowledges_preserved_batch(self):
        import wrapper

        class StopWatcher(BaseException):
            pass

        with tempfile.TemporaryDirectory() as temporary_dir:
            queue_file = Path(temporary_dir) / "codex-sol_queue.jsonl"
            inflight = Path(f"{queue_file}.inflight")
            inflight.write_text(
                '{"channel":"general","prompt":"DELIVER_ME"}\n',
                encoding="utf-8",
            )
            injected = []
            with (
                mock.patch("wrapper._fetch_role", return_value="Integrator"),
                mock.patch("wrapper._fetch_active_rules", return_value=None),
                mock.patch(
                    "wrapper.time.sleep",
                    side_effect=[None, StopWatcher()],
                ),
            ):
                with self.assertRaises(StopWatcher):
                    wrapper._queue_watcher(
                        lambda: ("codex-sol", queue_file),
                        lambda prompt: injected.append(prompt) or True,
                        agent_name="codex-sol",
                    )

            self.assertEqual(injected, ["DELIVER_ME\n\nROLE: Integrator"])
            self.assertFalse(inflight.exists())

    def test_queue_batch_delivers_each_distinct_prompt_in_order(self):
        import wrapper

        class StopWatcher(BaseException):
            pass

        with tempfile.TemporaryDirectory() as temporary_dir:
            queue_file = Path(temporary_dir) / "codex-sol_queue.jsonl"
            queue_file.write_text(
                '{"prompt":"FIRST"}\n{"prompt":"SECOND"}\n',
                encoding="utf-8",
            )
            injected = []
            with (
                mock.patch("wrapper._fetch_role", return_value=""),
                mock.patch("wrapper._fetch_active_rules", return_value=None),
                mock.patch(
                    "wrapper.time.sleep",
                    side_effect=[None, None, None, StopWatcher()],
                ),
            ):
                with self.assertRaises(StopWatcher):
                    wrapper._queue_watcher(
                        lambda: ("codex-sol", queue_file),
                        lambda prompt: injected.append(prompt) or True,
                        agent_name="codex-sol",
                    )

            self.assertEqual(injected, ["FIRST", "SECOND"])
            self.assertFalse(Path(f"{queue_file}.inflight").exists())

    def test_runtime_cwd_expands_environment_and_home(self):
        from wrapper import _resolve_runtime_cwd

        with tempfile.TemporaryDirectory(dir=Path.home()) as temporary_dir:
            path = Path(temporary_dir)
            with mock.patch.dict(os.environ, {"TEAM_UP_RUNTIME_DIR": str(path)}, clear=False):
                self.assertEqual(_resolve_runtime_cwd("$TEAM_UP_RUNTIME_DIR"), str(path.resolve()))
            self.assertEqual(
                _resolve_runtime_cwd("~/" + str(path.relative_to(Path.home()))),
                str(path.resolve()),
            )

    def test_assign_role_posts_to_registered_identity(self):
        from wrapper import _assign_role

        requests: list[tuple[str, bytes]] = []

        class RoleHandler(BaseHTTPRequestHandler):
            def do_POST(self):
                requests.append((self.path, self.rfile.read(int(self.headers["Content-Length"]))))
                self.send_response(200)
                self.end_headers()

            def log_message(self, format, *args):
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), RoleHandler)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            _assign_role(server.server_port, "codex-sol", "Integrator")
        finally:
            server.shutdown()
            thread.join()
            server.server_close()

        self.assertEqual(requests, [("/api/roles/codex-sol", b'{"role": "Integrator"}')])

    def test_provider_state_wrapper_posts_only_allowlisted_status(self):
        from wrapper import _report_provider_state

        requests = []

        class ProviderStateHandler(BaseHTTPRequestHandler):
            def do_POST(self):
                requests.append((self.path, dict(self.headers), self.rfile.read(int(self.headers["Content-Length"]))))
                self.send_response(200)
                self.end_headers()

            def log_message(self, format, *args):
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), ProviderStateHandler)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            _report_provider_state(
                server.server_port,
                "codex-sol",
                "test-token",
                "provider_ready",
                "ready_prompt",
            )
        finally:
            server.shutdown()
            thread.join()
            server.server_close()

        self.assertEqual(len(requests), 1)
        path, headers, body = requests[0]
        self.assertEqual(path, "/api/provider-state/codex-sol")
        self.assertEqual(headers["Authorization"], "Bearer test-token")
        self.assertEqual(body, b'{"state": "provider_ready", "reason_code": "ready_prompt"}')
        self.assertNotIn(b"PANE_SECRET_aa21", body)

    def test_selected_environment_reaches_tmux_for_inherited_values(self):
        from wrapper import _isolate_selected_session_env
        from wrapper_unix import _build_tmux_new_session_command

        parent_env, session_env = _isolate_selected_session_env(
            {
                "PATH": "/usr/bin",
                "GEMINI_API_KEY": "stale-parent-value",
            },
            {"MCP_SETTINGS": "settings-path"},
            {"GEMINI_API_KEY": "inherited-for-test"},
        )
        command = _build_tmux_new_session_command(
            "agentchattr-gemini-video",
            "/tmp/project",
            "gemini",
            session_env,
        )

        self.assertIn("GEMINI_API_KEY=inherited-for-test", command)
        self.assertIn("MCP_SETTINGS=settings-path", command)
        self.assertEqual(parent_env, {"PATH": "/usr/bin"})

    def test_registration_retries_a_cold_server(self):
        from wrapper import _register_instance_with_retry

        with mock.patch("wrapper._register_instance", side_effect=[OSError(), OSError(), {"name": "codex-sol"}]) as register:
            with mock.patch("wrapper.time.sleep") as sleep:
                result = _register_instance_with_retry(8300, "codex-sol", attempts=3, retry_delay=0)

        self.assertEqual(result, {"name": "codex-sol"})
        self.assertEqual(register.call_count, 3)
        self.assertEqual(sleep.call_count, 2)

    def test_detached_tmux_session_disappearance_restarts_agent(self):
        from wrapper_unix import run_agent

        commands = []
        new_session_count = 0

        def fake_run(command, **kwargs):
            nonlocal new_session_count
            commands.append(command)
            if command[:3] == ["tmux", "new-session", "-d"]:
                new_session_count += 1
                return SimpleNamespace(returncode=0 if new_session_count == 1 else 1)
            if command[:2] == ["tmux", "attach-session"]:
                return SimpleNamespace(returncode=1)
            return SimpleNamespace(returncode=0)

        with (
            mock.patch("wrapper_unix._check_tmux"),
            mock.patch("wrapper_unix._session_exists", side_effect=[True, False]),
            mock.patch("wrapper_unix.subprocess.run", side_effect=fake_run),
            mock.patch("wrapper_unix.time.sleep") as sleep,
        ):
            run_agent(
                command="codex",
                extra_args=[],
                cwd="/tmp",
                env={},
                queue_file=Path("/tmp/unused-queue"),
                agent="codex-luna",
                no_restart=False,
                start_watcher=lambda inject: None,
                session_name="agentchattr-codex-luna",
            )

        new_sessions = [
            command for command in commands
            if command[:3] == ["tmux", "new-session", "-d"]
        ]
        self.assertEqual(len(new_sessions), 2)
        sleep.assert_any_call(3)

    def test_readiness_monitor_defers_queue_watcher_until_provider_prompt(self):
        from wrapper_unix import _monitor_provider_readiness

        pane_texts = iter([
            "Allow this tool to run? [y/N]",
            "› Describe the task you want to work on",
        ])
        reports = []
        watcher = mock.Mock()

        with mock.patch(
            "wrapper_unix._capture_pane_text",
            side_effect=lambda session: next(pane_texts),
        ):
            ready = _monitor_provider_readiness(
                "agentchattr-codex-sol",
                "codex",
                report_provider_state=lambda state, reason: reports.append((state, reason)),
                start_watcher=watcher,
                inject_fn=mock.sentinel.inject,
                poll_interval=0,
                session_exists=mock.Mock(side_effect=[True, True, True, True, False]),
            )

        self.assertTrue(ready)
        self.assertEqual(reports, [
            ("manual_action_required", "tool_approval"),
            ("provider_ready", "ready_prompt"),
            ("offline", "provider_offline"),
        ])
        watcher.assert_called_once_with(mock.sentinel.inject)

    def test_readiness_monitor_reports_offline_after_the_child_session_exits(self):
        from wrapper_unix import _monitor_provider_readiness

        reports = []
        with mock.patch(
            "wrapper_unix._capture_pane_text",
            return_value="› Describe the task you want to work on",
        ):
            ready = _monitor_provider_readiness(
                "agentchattr-codex-sol",
                "codex",
                report_provider_state=lambda state, reason: reports.append((state, reason)),
                start_watcher=mock.Mock(),
                inject_fn=mock.sentinel.inject,
                poll_interval=0,
                session_exists=mock.Mock(side_effect=[True, True, False]),
            )

        self.assertTrue(ready)
        self.assertEqual(reports, [
            ("provider_ready", "ready_prompt"),
            ("offline", "provider_offline"),
        ])

    def test_readiness_monitor_does_not_reopen_delivery_after_exit_race(self):
        from wrapper_unix import _monitor_provider_readiness

        reports = []
        watcher = mock.Mock()
        with mock.patch(
            "wrapper_unix._capture_pane_text",
            return_value="› Describe the task you want to work on",
        ):
            ready = _monitor_provider_readiness(
                "agentchattr-codex-sol",
                "codex",
                report_provider_state=lambda state, reason: reports.append((state, reason)),
                start_watcher=watcher,
                inject_fn=mock.sentinel.inject,
                poll_interval=0,
                session_exists=mock.Mock(side_effect=[True, False]),
            )

        self.assertFalse(ready)
        self.assertEqual(reports, [("offline", "provider_offline")])
        watcher.assert_not_called()

    def test_provider_delivery_gate_rejects_queue_injection_after_restart_exit(self):
        from wrapper_unix import _ProviderDeliveryGate

        injected = []
        reports = []
        gate = _ProviderDeliveryGate(
            lambda prompt: injected.append(prompt) or True,
            lambda state, reason: reports.append((state, reason)),
        )

        gate.report("provider_ready", "ready_prompt")
        self.assertTrue(gate.inject("first prompt"))
        gate.report("offline", "provider_offline")
        self.assertFalse(gate.inject("must remain queued"))
        gate.report("registered", "unknown_screen")
        self.assertFalse(gate.inject("restart still blocked"))

        self.assertEqual(injected, ["first prompt"])
        self.assertEqual(reports, [
            ("provider_ready", "ready_prompt"),
            ("offline", "provider_offline"),
            ("registered", "unknown_screen"),
        ])

    def test_provider_delivery_gate_serializes_offline_with_inflight_injection(self):
        from wrapper_unix import _ProviderDeliveryGate

        injection_started = threading.Event()
        release_injection = threading.Event()
        offline_reported = threading.Event()
        reports = []

        def inject(prompt):
            injection_started.set()
            release_injection.wait(timeout=1)
            return True

        gate = _ProviderDeliveryGate(inject, lambda state, reason: reports.append((state, reason)))
        gate.report("provider_ready", "ready_prompt")
        delivery = threading.Thread(target=lambda: gate.inject("queued prompt"))
        delivery.start()
        self.assertTrue(injection_started.wait(timeout=1))

        self.assertFalse(gate._lock.acquire(blocking=False))
        offline = threading.Thread(
            target=lambda: (gate.report("offline", "provider_offline"), offline_reported.set()),
        )
        offline.start()
        self.assertFalse(offline_reported.wait(timeout=0.05))

        release_injection.set()
        delivery.join(timeout=1)
        offline.join(timeout=1)

        self.assertTrue(offline_reported.is_set())
        self.assertEqual(reports, [
            ("provider_ready", "ready_prompt"),
            ("offline", "provider_offline"),
        ])

    def test_windows_launch_omits_unix_readiness_arguments(self):
        from wrapper import _provider_readiness_run_kwargs

        self.assertEqual(
            _provider_readiness_run_kwargs("win32", "codex", mock.sentinel.report),
            {},
        )
        self.assertEqual(
            _provider_readiness_run_kwargs("darwin", "codex", mock.sentinel.report),
            {"provider": "codex", "report_provider_state": mock.sentinel.report},
        )

    def test_unix_injection_uses_private_tmux_buffer_before_enter(self):
        from wrapper_unix import inject

        prompt = "private first line\nROLE: Integrator\nfinal line"
        buffer_id = SimpleNamespace(hex="fixed-buffer-id")
        with (
            mock.patch(
                "wrapper_unix.subprocess.run",
                side_effect=[
                    SimpleNamespace(returncode=0),
                    SimpleNamespace(returncode=0),
                    SimpleNamespace(returncode=0),
                ],
            ) as run,
            mock.patch("uuid.uuid4", return_value=buffer_id),
            mock.patch("wrapper_unix.time.sleep") as sleep,
        ):
            self.assertTrue(
                inject(prompt, tmux_session="agentchattr-codex-sol", delay=1.0)
            )
        self.assertEqual(run.call_args_list, [
            mock.call(
                [
                    "tmux", "load-buffer", "-b",
                    "agentchattr-inject-fixed-buffer-id", "-",
                ],
                input=prompt.encode("utf-8"),
                capture_output=True,
            ),
            mock.call(
                [
                    "tmux", "paste-buffer", "-p", "-d", "-b",
                    "agentchattr-inject-fixed-buffer-id", "-t",
                    "agentchattr-codex-sol",
                ],
                capture_output=True,
            ),
            mock.call(
                [
                    "tmux", "send-keys", "-t",
                    "agentchattr-codex-sol", "Enter",
                ],
                capture_output=True,
            ),
        ])
        sleep.assert_called_once_with(1.0)
        for call in run.call_args_list:
            self.assertNotIn(prompt, call.args[0])

    def test_unix_injection_cleans_buffer_and_preserves_failure(self):
        from wrapper_unix import inject

        prompt = "private multiline\ncanary"
        with (
            mock.patch(
                "wrapper_unix.subprocess.run",
                side_effect=[
                    SimpleNamespace(returncode=0),
                    SimpleNamespace(returncode=1),
                    SimpleNamespace(returncode=0),
                ],
            ) as run,
            mock.patch(
                "uuid.uuid4",
                return_value=SimpleNamespace(hex="failed-buffer-id"),
            ),
            mock.patch("wrapper_unix.time.sleep") as sleep,
        ):
            with self.assertRaisesRegex(RuntimeError, "tmux injection failed"):
                inject(prompt, tmux_session="agentchattr-codex-sol")

        self.assertEqual(run.call_args_list[-1], mock.call(
            ["tmux", "delete-buffer", "-b", "agentchattr-inject-failed-buffer-id"],
            capture_output=True,
        ))
        self.assertEqual(run.call_count, 3)
        sleep.assert_not_called()
        for call in run.call_args_list:
            self.assertNotIn(prompt, call.args[0])

    def test_watcher_starts_only_after_tmux_session_exists(self):
        from wrapper_unix import run_agent

        events = []

        def fake_run(command, **kwargs):
            events.append(("command", command[:3]))
            return SimpleNamespace(returncode=0)

        with (
            mock.patch("wrapper_unix._check_tmux"),
            mock.patch("wrapper_unix.subprocess.run", side_effect=fake_run),
            mock.patch("wrapper_unix._session_exists", return_value=False),
        ):
            run_agent(
                command="codex",
                extra_args=[],
                cwd="/tmp",
                env={},
                queue_file=Path("/tmp/unused-queue"),
                agent="codex-sol",
                no_restart=True,
                start_watcher=lambda inject_fn: events.append(("watcher", None)),
                session_name="agentchattr-codex-sol",
            )

        session_index = events.index(
            ("command", ["tmux", "new-session", "-d"])
        )
        watcher_index = events.index(("watcher", None))
        self.assertLess(session_index, watcher_index)

    def test_team_up_health_reports_exact_ready_cast(self):
        import asyncio
        import app
        import mcp_bridge

        expected = {
            "claude-lead",
            "gemini-video",
            "codex-sol",
            "codex-terra",
            "codex-luna",
        }
        secret_pane_text = "GEMINI_API_KEY=never-return-this"
        exact_registry = SimpleNamespace(
            get_active_names=lambda: sorted(expected),
            get_instance=lambda name: {
                "provider_state": "provider_ready",
                "provider_reason_code": "ready_prompt",
                "raw_pane_text": secret_pane_text,
            },
        )
        passed_canary = mock.Mock()
        passed_canary.snapshot.return_value = {
            "state": "passed",
            "complete": True,
            "agents": {
                name: {"state": "passed", "reason": "response_verified", "timestamp": 100.0}
                for name in expected
            },
        }
        with (
            mock.patch.object(app, "registry", exact_registry),
            mock.patch.object(app, "startup_canary", passed_canary),
            mock.patch.object(
                mcp_bridge,
                "is_online",
                side_effect=lambda name: name in expected,
            ),
        ):
            payload = asyncio.run(app.team_up_health())

        self.assertEqual(payload["service"], "agentchattr-team-up-v2")
        self.assertTrue(payload["ready"])
        self.assertEqual(set(payload["agents"]), expected)
        self.assertEqual(payload["canary"]["state"], "passed")
        self.assertEqual(
            payload["agents"]["codex-sol"],
            {"online": True, "provider_state": "provider_ready", "reason_code": "ready_prompt"},
        )
        self.assertNotIn(secret_pane_text, json.dumps(payload))

        suffixed_registry = SimpleNamespace(
            get_active_names=lambda: [*sorted(expected), "gemini-video-2"],
            get_instance=exact_registry.get_instance,
        )
        with (
            mock.patch.object(app, "registry", suffixed_registry),
            mock.patch.object(app, "startup_canary", passed_canary),
            mock.patch.object(mcp_bridge, "is_online", return_value=True),
        ):
            payload = asyncio.run(app.team_up_health())
        self.assertFalse(payload["ready"])

        blocked_registry = SimpleNamespace(
            get_active_names=lambda: sorted(expected),
            get_instance=lambda name: {
                "provider_state": "manual_action_required"
                if name == "codex-luna" else "provider_ready",
                "provider_reason_code": "tool_approval"
                if name == "codex-luna" else "ready_prompt",
            },
        )
        with (
            mock.patch.object(app, "registry", blocked_registry),
            mock.patch.object(app, "startup_canary", passed_canary),
            mock.patch.object(mcp_bridge, "is_online", return_value=True),
        ):
            payload = asyncio.run(app.team_up_health())
        self.assertFalse(payload["ready"])

        with (
            mock.patch.object(app, "registry", exact_registry),
            mock.patch.object(app, "startup_canary", passed_canary),
            mock.patch.object(
                mcp_bridge,
                "is_online",
                side_effect=lambda name: name != "codex-luna",
            ),
        ):
            payload = asyncio.run(app.team_up_health())
        self.assertFalse(payload["ready"])

        pending_canary = mock.Mock()
        pending_canary.snapshot.return_value = {
            "state": "pending",
            "complete": False,
            "agents": {},
        }
        canary_trigger = object()
        with (
            mock.patch.object(app, "registry", exact_registry),
            mock.patch.object(app, "startup_canary", None),
            mock.patch.object(app, "agents", canary_trigger),
            mock.patch.object(app, "StartupCanary", return_value=pending_canary) as constructor,
            mock.patch.object(mcp_bridge, "startup_canary", None),
            mock.patch.object(mcp_bridge, "is_online", return_value=True),
        ):
            payload = asyncio.run(app.team_up_health())
            self.assertIs(mcp_bridge.startup_canary, pending_canary)
        constructor.assert_called_once_with(
            canary_trigger,
            app.TEAM_UP_IDENTITIES,
            provider_status=mock.ANY,
        )
        pending_canary.begin.assert_called_once_with()
        self.assertFalse(payload["ready"])

    def test_team_up_health_resets_a_passed_canary_after_wrapper_offline(self):
        import app
        import mcp_bridge

        expected = set(app.TEAM_UP_IDENTITIES)
        registry = SimpleNamespace(
            get_active_names=lambda: sorted(expected),
            get_instance=lambda name: {
                "provider_state": "offline" if name == "codex-luna" else "provider_ready",
                "provider_reason_code": "provider_offline" if name == "codex-luna" else "ready_prompt",
            },
        )
        passed_canary = mock.Mock()
        with (
            mock.patch.object(app, "registry", registry),
            mock.patch.object(app, "startup_canary", passed_canary),
            mock.patch.object(mcp_bridge, "startup_canary", passed_canary),
            mock.patch.object(mcp_bridge, "is_online", return_value=True),
        ):
            payload = asyncio.run(app.team_up_health())
            self.assertIsNone(app.startup_canary)
            self.assertIsNone(mcp_bridge.startup_canary)

        self.assertFalse(payload["ready"])
        self.assertEqual(payload["canary"]["state"], "blocked")

    def test_fast_deregister_reregister_ready_cycle_invalidates_passed_canary_without_health_poll(self):
        import app
        import mcp_bridge
        from registry import RuntimeRegistry
        from store import MessageStore

        class Request:
            def __init__(self, token="", body=None):
                self.headers = {
                    "authorization": f"Bearer {token}",
                } if token else {}
                self._body = body or {}

            async def json(self):
                return self._body

        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            registry = RuntimeRegistry(data_dir=str(root / "registry"))
            registry.seed({"codex-sol": {"dedicated_identity": True}})
            first = registry.register("codex-sol")
            store = MessageStore(str(root / "messages.jsonl"))
            passed_canary = mock.Mock()
            with (
                mock.patch.object(app, "registry", registry),
                mock.patch.object(app, "store", store),
                mock.patch.object(app, "startup_canary", passed_canary),
                mock.patch.object(mcp_bridge, "startup_canary", passed_canary),
                mock.patch.object(mcp_bridge, "registry", registry),
                mock.patch.object(mcp_bridge, "_presence", {}),
                mock.patch.object(mcp_bridge, "_activity", {}),
                mock.patch.object(mcp_bridge, "_activity_ts", {}),
                mock.patch.object(mcp_bridge, "_cursors", {}),
                mock.patch.object(mcp_bridge, "_roles", {}),
                mock.patch.object(mcp_bridge, "activity_store", None),
                mock.patch.object(mcp_bridge, "_CURSORS_FILE", None),
            ):
                deregistered = asyncio.run(app.deregister_agent(
                    "codex-sol",
                    Request(first["token"]),
                ))
                self.assertEqual(deregistered.status_code, 200)
                self.assertIsNone(app.startup_canary)
                self.assertIsNone(mcp_bridge.startup_canary)

                registered_response = asyncio.run(app.register_agent(Request(
                    body={"base": "codex-sol"},
                )))
                self.assertEqual(registered_response.status_code, 200)
                second = json.loads(registered_response.body)
                self.assertNotEqual(first["token"], second["token"])

                ready_response = asyncio.run(app.report_provider_state(
                    "codex-sol",
                    Request(second["token"], {
                        "state": "provider_ready",
                        "reason_code": "ready_prompt",
                    }),
                ))
                self.assertEqual(ready_response.status_code, 200)
                self.assertIsNone(app.startup_canary)

        self.assertEqual(
            registry.get_instance("codex-sol")["provider_state"],
            "provider_ready",
        )

    def test_queue_lock_serializes_append_and_claim(self):
        import threading

        from agents import AgentTrigger
        from queue_io import queue_lock
        from wrapper import _claim_queue_batch

        with tempfile.TemporaryDirectory() as temporary_dir:
            queue_file = Path(temporary_dir) / "codex-sol_queue.jsonl"
            entered = threading.Event()
            release = threading.Event()
            claimed = []

            def hold_producer_lock():
                with queue_lock(queue_file):
                    with open(queue_file, "a", encoding="utf-8") as stream:
                        entered.set()
                        release.wait(timeout=2)
                        stream.write('{"prompt":"LOCKED"}\n')

            producer = threading.Thread(target=hold_producer_lock)
            producer.start()
            self.assertTrue(entered.wait(timeout=1))

            consumer = threading.Thread(
                target=lambda: claimed.append(_claim_queue_batch(queue_file))
            )
            consumer.start()
            consumer.join(timeout=0.05)
            self.assertTrue(consumer.is_alive())

            release.set()
            producer.join(timeout=1)
            consumer.join(timeout=1)
            self.assertFalse(consumer.is_alive())
            self.assertIn("LOCKED", claimed[0].read_text("utf-8"))

            next_queue = Path(temporary_dir) / "next_queue.jsonl"
            AgentTrigger._append_queue_entry(
                next_queue,
                {"prompt": "APPENDED"},
            )
            self.assertIn("APPENDED", next_queue.read_text("utf-8"))

    def test_role_instructions_use_control_root_and_reach_each_trigger(self):
        import wrapper

        class StopWatcher(BaseException):
            pass

        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            control_root = root / "control"
            target_root = root / "target"
            control_root.mkdir()
            target_root.mkdir()
            (control_root / "Codex.md").write_text("CONTROL ROLE RULE", encoding="utf-8")
            (target_root / "Codex.md").write_text("TARGET FILE MUST NOT LOAD", encoding="utf-8")
            queue_file = target_root / "codex-sol_queue.jsonl"
            queue_file.write_text('{"channel":"build"}\n', encoding="utf-8")

            instructions = wrapper._load_role_instructions(control_root, "Codex.md")
            injected = []
            with (
                mock.patch("wrapper._fetch_role", return_value="Integrator"),
                mock.patch("wrapper._fetch_active_rules", return_value=None),
                mock.patch("wrapper.time.sleep", side_effect=[None, StopWatcher()]),
            ):
                with self.assertRaises(StopWatcher):
                    wrapper._queue_watcher(
                        lambda: ("codex-sol", queue_file),
                        injected.append,
                        server_port=8300,
                        agent_name="codex-sol",
                        role_instructions=instructions,
                    )

        self.assertEqual(len(injected), 1)
        self.assertIn("\n\nROLE INSTRUCTIONS:\nCONTROL ROLE RULE", injected[0])
        self.assertNotIn("TARGET FILE MUST NOT LOAD", injected[0])

    def test_role_instruction_startup_failures_do_not_register(self):
        import wrapper

        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            oversized = root / "oversized.md"
            oversized.write_bytes(b"x" * (16 * 1024 + 1))
            unreadable = root / "unreadable.md"
            unreadable.mkdir()

            for instructions_file in ("missing.md", "oversized.md", "unreadable.md"):
                with self.subTest(instructions_file=instructions_file):
                    config = {
                        "server": {"port": 8300, "data_dir": "./data"},
                        "agents": {
                            "codex-sol": {
                                "command": "codex",
                                "instructions_file": instructions_file,
                            },
                        },
                    }
                    with (
                        mock.patch.object(wrapper, "ROOT", root),
                        mock.patch("config_loader.load_config", return_value=config),
                        mock.patch("wrapper._register_instance_with_retry") as register,
                        mock.patch.object(
                            wrapper.sys,
                            "argv",
                            ["wrapper.py", "codex-sol"],
                        ),
                    ):
                        with self.assertRaises(SystemExit):
                            wrapper.main()
                    register.assert_not_called()

    def test_post_registration_failure_deregisters_exactly_once(self):
        import urllib.request

        import wrapper

        with tempfile.TemporaryDirectory() as temporary_dir:
            config = {
                "server": {"port": 8300, "data_dir": temporary_dir},
                "agents": {
                    "codex-sol": {
                        "command": "codex",
                        "mcp_inject": "invalid-mode",
                    },
                },
            }
            registration = {
                "name": "codex-sol",
                "token": "opaque-test-token",
                "slot": 1,
            }
            opened = mock.MagicMock()
            opened.__enter__.return_value = mock.MagicMock()
            with (
                mock.patch("config_loader.load_config", return_value=config),
                mock.patch(
                    "wrapper._register_instance_with_retry",
                    return_value=registration,
                ),
                mock.patch.object(
                    wrapper.sys,
                    "argv",
                    ["wrapper.py", "codex-sol"],
                ),
                mock.patch.object(urllib.request, "urlopen", return_value=opened) as urlopen,
            ):
                with self.assertRaises(SystemExit):
                    wrapper.main()

        deregistration_requests = [
            call.args[0]
            for call in urlopen.call_args_list
            if getattr(call.args[0], "full_url", "").endswith(
                "/api/deregister/codex-sol"
            )
        ]
        self.assertEqual(len(deregistration_requests), 1)
        self.assertEqual(
            deregistration_requests[0].headers["Authorization"],
            "Bearer opaque-test-token",
        )

    def _make_wrapper_launcher_fixture(
        self,
        root: Path,
        initial_tmux_targets: tuple[str, ...] = (),
        server_listening: bool = True,
        server_becomes_ready: bool = True,
        dead_tmux_targets: tuple[str, ...] = (),
        health_ready: bool = True,
        agents_ready: bool = True,
        blocked_identity: str = "codex-luna",
        blocked_reason: str = "response_timeout",
    ):
        source_script = Path(__file__).parents[1] / "macos-linux" / "start_team_up.sh"

        repo = root / "repo"
        script_dir = repo / "macos-linux"
        script_dir.mkdir(parents=True)
        script = script_dir / "start_team_up.sh"
        shutil.copy2(source_script, script)
        (repo / "requirements.txt").write_text("", encoding="utf-8")
        python = repo / ".venv" / "bin" / "python"
        python.parent.mkdir(parents=True)
        python.write_text(
            "#!/bin/sh\n"
            "if [ \"$1\" = \"-c\" ]; then\n"
            "    case \"$3\" in\n"
            "        server) [ \"$TEAM_UP_HEALTH_READY\" = \"1\" ] ;;\n"
            "        agents) [ \"$TEAM_UP_AGENTS_READY\" = \"1\" ] ;;\n"
            "        blocker) printf '%s: %s\\n' \"$TEAM_UP_BLOCKED_IDENTITY\" \"$TEAM_UP_BLOCKED_REASON\" ;;\n"
            "    esac\n"
            "    exit $?\n"
            "fi\n"
            "exit 0\n",
            encoding="utf-8",
        )
        python.chmod(0o755)
        project = root / "project"
        project.mkdir()

        fake_bin = root / "bin"
        fake_bin.mkdir()
        (fake_bin / "lsof").write_text(
            "#!/bin/sh\n"
            "[ -f \"$TEAM_UP_LISTEN_STATE\" ]\n",
            encoding="utf-8",
        )
        (fake_bin / "sleep").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        (fake_bin / "nohup").write_text(
            "#!/bin/sh\n"
            "printf '%s\\n' \"$*\" >> \"$TEAM_UP_NOHUP_LOG\"\n",
            encoding="utf-8",
        )
        (fake_bin / "tmux").write_text(
            "#!/bin/sh\n"
            "printf '%s\\n' \"$*\" >> \"$TEAM_UP_TMUX_LOG\"\n"
            "tmux_command=$1\n"
            "shift\n"
            "target=\n"
            "window=\n"
            "session=\n"
            "while [ \"$#\" -gt 0 ]; do\n"
            "    case \"$1\" in\n"
            "        -t) shift; target=$1 ;;\n"
            "        -n) shift; window=$1 ;;\n"
            "        -s) shift; session=$1 ;;\n"
            "    esac\n"
            "    shift\n"
            "done\n"
            "case \"$target\" in\n"
            "    =*:*)\n"
            "        target_session=${target%%:*}\n"
            "        target_window=${target#*:}\n"
            "        target=${target_session#=}:${target_window#=}\n"
            "        ;;\n"
            "    =*) target=${target#=} ;;\n"
            "esac\n"
            "case \"$tmux_command\" in\n"
            "    has-session)\n"
            "        grep -Fqx \"$target\" \"$TEAM_UP_TMUX_STATE\"\n"
            "        ;;\n"
            "    display-message)\n"
            "        if grep -Fqx \"$target\" \"$TEAM_UP_TMUX_STATE\"; then\n"
            "            printf '0\\n'\n"
            "        else\n"
            "            exit 1\n"
            "        fi\n"
            "        ;;\n"
            "    list-panes)\n"
            "        if grep -Fqx \"$target\" \"$TEAM_UP_TMUX_STATE\"; then\n"
            "            if grep -Fqx \"$target\" \"$TEAM_UP_DEAD_TMUX_STATE\"; then\n"
            "                printf '1\\n'\n"
            "            else\n"
            "                printf '0\\n'\n"
            "            fi\n"
            "        else\n"
            "            exit 1\n"
            "        fi\n"
            "        ;;\n"
            "    new-window)\n"
            "        printf '%s:%s\\n' \"$target\" \"$window\" >> \"$TEAM_UP_TMUX_STATE\"\n"
            "        if [ \"$window\" = \"server\" ] && [ \"$TEAM_UP_SERVER_BECOMES_READY\" = \"1\" ]; then\n"
            "            : > \"$TEAM_UP_LISTEN_STATE\"\n"
            "        fi\n"
            "        ;;\n"
            "    new-session)\n"
            "        printf '%s\\n' \"$session\" >> \"$TEAM_UP_TMUX_STATE\"\n"
            "        if [ -n \"$window\" ]; then\n"
            "            printf '%s:%s\\n' \"$session\" \"$window\" >> \"$TEAM_UP_TMUX_STATE\"\n"
            "        fi\n"
            "        if [ \"$window\" = \"server\" ] && [ \"$TEAM_UP_SERVER_BECOMES_READY\" = \"1\" ]; then\n"
            "            : > \"$TEAM_UP_LISTEN_STATE\"\n"
            "        fi\n"
            "        ;;\n"
            "    kill-session)\n"
            "        awk -v target=\"$target\" '$0 != target && index($0, target \":\") != 1' \"$TEAM_UP_TMUX_STATE\" > \"$TEAM_UP_TMUX_STATE.tmp\"\n"
            "        mv \"$TEAM_UP_TMUX_STATE.tmp\" \"$TEAM_UP_TMUX_STATE\"\n"
            "        ;;\n"
            "    kill-window)\n"
            "        awk -v target=\"$target\" '$0 != target' \"$TEAM_UP_TMUX_STATE\" > \"$TEAM_UP_TMUX_STATE.tmp\"\n"
            "        mv \"$TEAM_UP_TMUX_STATE.tmp\" \"$TEAM_UP_TMUX_STATE\"\n"
            "        awk -v target=\"$target\" '$0 != target' \"$TEAM_UP_DEAD_TMUX_STATE\" > \"$TEAM_UP_DEAD_TMUX_STATE.tmp\"\n"
            "        mv \"$TEAM_UP_DEAD_TMUX_STATE.tmp\" \"$TEAM_UP_DEAD_TMUX_STATE\"\n"
            "        ;;\n"
            "    *) exit 0 ;;\n"
            "esac\n",
            encoding="utf-8",
        )
        for executable in fake_bin.iterdir():
            executable.chmod(0o755)

        tmux_state = root / "tmux.state"
        tmux_state.write_text(
            "".join(f"{target}\n" for target in initial_tmux_targets),
            encoding="utf-8",
        )
        dead_tmux_state = root / "tmux.dead.state"
        dead_tmux_state.write_text(
            "".join(f"{target}\n" for target in dead_tmux_targets),
            encoding="utf-8",
        )
        listen_state = root / "listening"
        if server_listening:
            listen_state.touch()
        tmux_log = root / "tmux.log"
        nohup_log = root / "nohup.log"
        env = {
            **os.environ,
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "TEAM_UP_TMUX_STATE": str(tmux_state),
            "TEAM_UP_DEAD_TMUX_STATE": str(dead_tmux_state),
            "TEAM_UP_TMUX_LOG": str(tmux_log),
            "TEAM_UP_NOHUP_LOG": str(nohup_log),
            "TEAM_UP_LISTEN_STATE": str(listen_state),
            "TEAM_UP_SERVER_BECOMES_READY": (
                "1" if server_becomes_ready else "0"
            ),
            "TEAM_UP_HEALTH_READY": "1" if health_ready else "0",
            "TEAM_UP_AGENTS_READY": "1" if agents_ready else "0",
            "TEAM_UP_BLOCKED_IDENTITY": blocked_identity,
            "TEAM_UP_BLOCKED_REASON": blocked_reason,
        }
        return script, project, env, tmux_state, tmux_log, nohup_log

    def test_launcher_owns_wrappers_in_server_tmux_windows(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            script, project, env, tmux_state, _, nohup_log = (
                self._make_wrapper_launcher_fixture(
                    root,
                    initial_tmux_targets=("agentchattr-team-up-server",),
                )
            )

            subprocess.run(
                ["sh", str(script), str(project)],
                check=True,
                env=env,
                capture_output=True,
                text=True,
            )

            self.assertEqual(
                set(tmux_state.read_text("utf-8").splitlines()),
                {
                    "agentchattr-team-up-server",
                    "agentchattr-team-up-server:wrapper-claude-lead",
                    "agentchattr-team-up-server:wrapper-gemini-video",
                    "agentchattr-team-up-server:wrapper-codex-sol",
                    "agentchattr-team-up-server:wrapper-codex-terra",
                    "agentchattr-team-up-server:wrapper-codex-luna",
                },
            )
            self.assertFalse(nohup_log.exists())

    def test_launcher_rerun_keeps_one_tmux_owner_per_wrapper(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            script, project, env, _, tmux_log, _ = (
                self._make_wrapper_launcher_fixture(
                    root,
                    initial_tmux_targets=("agentchattr-team-up-server",),
                )
            )

            subprocess.run(
                ["sh", str(script), str(project)],
                check=True,
                env=env,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                ["sh", str(script), str(project)],
                check=True,
                env=env,
                capture_output=True,
                text=True,
            )

            owner_starts = [
                command
                for command in tmux_log.read_text("utf-8").splitlines()
                if command.startswith(
                    "new-window -d -t =agentchattr-team-up-server "
                )
            ]
            self.assertEqual(len(owner_starts), 5)

    def test_launcher_replaces_dead_wrapper_owner_without_duplicate_window(self):
        wrapper_targets = (
            "agentchattr-team-up-server:wrapper-claude-lead",
            "agentchattr-team-up-server:wrapper-gemini-video",
            "agentchattr-team-up-server:wrapper-codex-sol",
            "agentchattr-team-up-server:wrapper-codex-terra",
            "agentchattr-team-up-server:wrapper-codex-luna",
        )
        dead_owner = "agentchattr-team-up-server:wrapper-codex-luna"
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            script, project, env, tmux_state, tmux_log, _ = (
                self._make_wrapper_launcher_fixture(
                    root,
                    initial_tmux_targets=(
                        "agentchattr-team-up-server",
                        *wrapper_targets,
                    ),
                    dead_tmux_targets=(dead_owner,),
                )
            )

            subprocess.run(
                ["sh", str(script), str(project)],
                check=True,
                env=env,
                capture_output=True,
                text=True,
            )

            targets = tmux_state.read_text("utf-8").splitlines()
            self.assertEqual(targets.count(dead_owner), 1)
            commands = tmux_log.read_text("utf-8").splitlines()
            kill_command = (
                "kill-window -t "
                "=agentchattr-team-up-server:=wrapper-codex-luna"
            )
            self.assertIn(kill_command, commands)
            kill_index = commands.index(kill_command)
            restart_index = next(
                index
                for index, command in enumerate(commands)
                if command.startswith(
                    "new-window -d -t =agentchattr-team-up-server "
                    "-n wrapper-codex-luna "
                )
            )
            self.assertLess(kill_index, restart_index)

    def test_launcher_replaces_stale_visible_session_before_restarting_wrapper(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            script, project, env, tmux_state, tmux_log, _ = (
                self._make_wrapper_launcher_fixture(
                    root,
                    initial_tmux_targets=(
                        "agentchattr-team-up-server",
                        "agentchattr-codex-luna",
                    ),
                )
            )

            subprocess.run(
                ["sh", str(script), str(project)],
                check=True,
                env=env,
                capture_output=True,
                text=True,
            )

            commands = tmux_log.read_text("utf-8").splitlines()
            self.assertIn(
                "kill-session -t =agentchattr-codex-luna",
                commands,
            )
            kill_index = commands.index(
                "kill-session -t =agentchattr-codex-luna"
            )
            restart_index = next(
                index
                for index, command in enumerate(commands)
                if command.startswith(
                    "new-window -d -t =agentchattr-team-up-server "
                    "-n wrapper-codex-luna "
                )
            )
            self.assertLess(kill_index, restart_index)
            self.assertNotIn(
                "agentchattr-codex-luna",
                tmux_state.read_text("utf-8").splitlines(),
            )

    def test_launcher_restarts_dead_server_window_while_wrapper_owners_live(self):
        wrapper_targets = (
            "agentchattr-team-up-server:wrapper-claude-lead",
            "agentchattr-team-up-server:wrapper-gemini-video",
            "agentchattr-team-up-server:wrapper-codex-sol",
            "agentchattr-team-up-server:wrapper-codex-terra",
            "agentchattr-team-up-server:wrapper-codex-luna",
        )
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            script, project, env, tmux_state, tmux_log, _ = (
                self._make_wrapper_launcher_fixture(
                    root,
                    initial_tmux_targets=(
                        "agentchattr-team-up-server",
                        *wrapper_targets,
                    ),
                    server_listening=False,
                )
            )

            subprocess.run(
                ["sh", str(script), str(project)],
                check=True,
                env=env,
                capture_output=True,
                text=True,
            )

            targets = tmux_state.read_text("utf-8").splitlines()
            self.assertIn(
                "agentchattr-team-up-server:server",
                targets,
            )
            self.assertTrue(all(target in targets for target in wrapper_targets))
            server_starts = [
                command
                for command in tmux_log.read_text("utf-8").splitlines()
                if command.startswith(
                    "new-window -d -t =agentchattr-team-up-server "
                    "-n server "
                )
            ]
            self.assertEqual(len(server_starts), 1)

    def test_launcher_fails_before_wrappers_when_server_never_becomes_ready(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            script, project, env, tmux_state, _, _ = (
                self._make_wrapper_launcher_fixture(
                    root,
                    initial_tmux_targets=("agentchattr-team-up-server",),
                    server_listening=False,
                    server_becomes_ready=False,
                )
            )

            result = subprocess.run(
                ["sh", str(script), str(project)],
                check=False,
                env=env,
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(
                any(
                    ":wrapper-" in target
                    for target in tmux_state.read_text("utf-8").splitlines()
                )
            )

    def test_launcher_rejects_unrelated_listener_and_missing_agent_cast(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            script, project, env, tmux_state, _, _ = (
                self._make_wrapper_launcher_fixture(
                    root,
                    server_listening=True,
                    server_becomes_ready=False,
                    health_ready=False,
                )
            )
            result = subprocess.run(
                ["sh", str(script), str(project)],
                check=False,
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn("Team Up: http://", result.stdout)
            self.assertFalse(
                any(
                    ":wrapper-" in target
                    for target in tmux_state.read_text("utf-8").splitlines()
                )
            )

        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            script, project, env, tmux_state, _, _ = (
                self._make_wrapper_launcher_fixture(
                    root,
                    server_listening=True,
                    health_ready=True,
                    agents_ready=False,
                )
            )
            result = subprocess.run(
                ["sh", str(script), str(project)],
                check=False,
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn("Team Up: http://", result.stdout)
            self.assertTrue(
                any(
                    ":wrapper-" in target
                    for target in tmux_state.read_text("utf-8").splitlines()
                )
            )

    def test_launcher_timeout_prints_exact_blocked_identity_and_safe_reason(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            script, project, env, _, _, _ = self._make_wrapper_launcher_fixture(
                root,
                agents_ready=False,
                blocked_identity="gemini-video",
                blocked_reason="tool_approval",
            )
            env["RAW_PRIVATE_NONCE"] = "must-never-appear"

            result = subprocess.run(
                ["sh", str(script), str(project)],
                check=False,
                env=env,
                capture_output=True,
                text=True,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("gemini-video", result.stderr)
        self.assertIn("tool_approval", result.stderr)
        self.assertNotIn("must-never-appear", result.stdout + result.stderr)

    def test_launcher_preserves_similarly_prefixed_sessions_and_windows(self):
        real_tmux = shutil.which("tmux")
        if real_tmux is None:
            self.skipTest("tmux is required for the Team Up launcher")

        source_script = Path(__file__).parents[1] / "macos-linux" / "start_team_up.sh"
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            repo = root / "repo"
            script_dir = repo / "macos-linux"
            script_dir.mkdir(parents=True)
            script = script_dir / "start_team_up.sh"
            shutil.copy2(source_script, script)
            (repo / "requirements.txt").write_text("", encoding="utf-8")
            listen_state = root / "listening"
            python = repo / ".venv" / "bin" / "python"
            python.parent.mkdir(parents=True)
            python.write_text(
                "#!/bin/sh\n"
                "case \"$1\" in\n"
                "    -c) exit 0 ;;\n"
                f"    */run.py) : > \"{listen_state}\" ;;\n"
                "esac\n"
                "exec /bin/sleep 30\n",
                encoding="utf-8",
            )
            python.chmod(0o755)
            project = root / "project"
            project.mkdir()

            fake_bin = root / "bin"
            fake_bin.mkdir()
            (fake_bin / "lsof").write_text(
                "#!/bin/sh\n"
                "[ -f \"$TEAM_UP_LISTEN_STATE\" ]\n",
                encoding="utf-8",
            )
            (fake_bin / "sleep").write_text(
                "#!/bin/sh\nexit 0\n",
                encoding="utf-8",
            )
            (fake_bin / "tmux").write_text(
                "#!/bin/sh\n"
                "printf '%s\\n' \"$*\" >> \"$TEAM_UP_REAL_TMUX_LOG\"\n"
                "exec \"$TEAM_UP_REAL_TMUX\" -S \"$TEAM_UP_TMUX_SOCKET\" \"$@\"\n",
                encoding="utf-8",
            )
            for executable in fake_bin.iterdir():
                executable.chmod(0o755)

            socket_path = root / "tmux.sock"
            tmux_prefix = [real_tmux, "-S", str(socket_path)]
            tmux_log = root / "real-tmux.log"
            env = {
                **os.environ,
                "PATH": f"{fake_bin}:{os.environ['PATH']}",
                "TEAM_UP_REAL_TMUX": real_tmux,
                "TEAM_UP_TMUX_SOCKET": str(socket_path),
                "TEAM_UP_REAL_TMUX_LOG": str(tmux_log),
                "TEAM_UP_LISTEN_STATE": str(listen_state),
            }
            try:
                subprocess.run(
                    [
                        *tmux_prefix,
                        "new-session",
                        "-d",
                        "-s",
                        "agentchattr-team-up-server",
                        "-n",
                        "server-old",
                        "/bin/sleep",
                        "30",
                    ],
                    check=True,
                )
                subprocess.run(
                    [
                        *tmux_prefix,
                        "new-window",
                        "-d",
                        "-t",
                        "=agentchattr-team-up-server",
                        "-n",
                        "wrapper-codex-luna-old",
                        "/bin/sleep",
                        "30",
                    ],
                    check=True,
                )
                subprocess.run(
                    [
                        *tmux_prefix,
                        "new-session",
                        "-d",
                        "-s",
                        "agentchattr-codex-luna-2",
                        "/bin/sleep",
                        "30",
                    ],
                    check=True,
                )

                launcher_result = subprocess.run(
                    ["sh", str(script), str(project)],
                    check=False,
                    env=env,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(launcher_result.returncode, 0)

                commands = tmux_log.read_text("utf-8").splitlines()
                self.assertIn(
                    "has-session -t =agentchattr-codex-luna",
                    commands,
                )
                suffix_session = subprocess.run(
                    [
                        *tmux_prefix,
                        "has-session",
                        "-t",
                        "=agentchattr-codex-luna-2",
                    ],
                    check=False,
                )
                self.assertEqual(suffix_session.returncode, 0)
                windows = subprocess.run(
                    [
                        *tmux_prefix,
                        "list-windows",
                        "-t",
                        "=agentchattr-team-up-server",
                        "-F",
                        "#{window_name}",
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout.splitlines()
                self.assertEqual(windows.count("server"), 1)
                self.assertEqual(windows.count("server-old"), 1)
                self.assertEqual(windows.count("wrapper-codex-luna"), 1)
                self.assertEqual(
                    windows.count("wrapper-codex-luna-old"),
                    1,
                )
            finally:
                subprocess.run(
                    [*tmux_prefix, "kill-server"],
                    check=False,
                    capture_output=True,
                )

    def test_launcher_does_not_persist_raw_server_output(self):
        source_script = Path(__file__).parents[1] / "macos-linux" / "start_team_up.sh"

        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            repo = root / "repo"
            script_dir = repo / "macos-linux"
            script_dir.mkdir(parents=True)
            script = script_dir / "start_team_up.sh"
            shutil.copy2(source_script, script)
            (repo / "requirements.txt").write_text("", encoding="utf-8")
            python = repo / ".venv" / "bin" / "python"
            python.parent.mkdir(parents=True)
            python.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            python.chmod(0o755)
            project = root / "project"
            project.mkdir()

            fake_bin = root / "bin"
            fake_bin.mkdir()
            listen_state = root / "listening"
            (fake_bin / "lsof").write_text(
                "#!/bin/sh\n"
                "if [ -f \"$TEAM_UP_LISTEN_STATE\" ]; then exit 0; fi\n"
                ": > \"$TEAM_UP_LISTEN_STATE\"\n"
                "exit 1\n",
                encoding="utf-8",
            )
            (fake_bin / "tmux").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            (fake_bin / "nohup").write_text(
                "#!/bin/sh\nprintf '%s\\n' raw-server-output\n",
                encoding="utf-8",
            )
            for executable in fake_bin.iterdir():
                executable.chmod(0o755)

            env = {
                **os.environ,
                "PATH": f"{fake_bin}:{os.environ['PATH']}",
                "TEAM_UP_LISTEN_STATE": str(listen_state),
            }
            subprocess.run(
                ["sh", str(script), str(project)],
                check=True,
                env=env,
                capture_output=True,
                text=True,
            )

            self.assertFalse((repo / "logs" / "team-up" / "server.redacted.log").exists())

    def test_launcher_owns_server_in_named_tmux_session(self):
        source_script = Path(__file__).parents[1] / "macos-linux" / "start_team_up.sh"

        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            repo = root / "repo"
            script_dir = repo / "macos-linux"
            script_dir.mkdir(parents=True)
            script = script_dir / "start_team_up.sh"
            shutil.copy2(source_script, script)
            (repo / "requirements.txt").write_text("", encoding="utf-8")
            python = repo / ".venv" / "bin" / "python"
            python.parent.mkdir(parents=True)
            python.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            python.chmod(0o755)
            project = root / "project"
            project.mkdir()

            fake_bin = root / "bin"
            fake_bin.mkdir()
            listen_state = root / "listening"
            tmux_log = root / "tmux.log"
            (fake_bin / "lsof").write_text(
                "#!/bin/sh\n"
                "if [ -f \"$TEAM_UP_LISTEN_STATE\" ]; then exit 0; fi\n"
                ": > \"$TEAM_UP_LISTEN_STATE\"\n"
                "exit 1\n",
                encoding="utf-8",
            )
            (fake_bin / "tmux").write_text(
                "#!/bin/sh\n"
                "printf '%s\\n' \"$*\" >> \"$TEAM_UP_TMUX_LOG\"\n"
                "case \"$1\" in has-session) exit 1 ;; esac\n"
                "exit 0\n",
                encoding="utf-8",
            )
            for executable in fake_bin.iterdir():
                executable.chmod(0o755)

            env = {
                **os.environ,
                "PATH": f"{fake_bin}:{os.environ['PATH']}",
                "TEAM_UP_LISTEN_STATE": str(listen_state),
                "TEAM_UP_TMUX_LOG": str(tmux_log),
            }
            subprocess.run(
                ["sh", str(script), str(project)],
                check=True,
                env=env,
                capture_output=True,
                text=True,
            )

            tmux_commands = tmux_log.read_text("utf-8").splitlines()
            self.assertTrue(
                any(
                    command.startswith(
                        "new-session -d -s agentchattr-team-up-server "
                        "-n server "
                    )
                    for command in tmux_commands
                )
            )
            self.assertFalse((repo / ".pids" / "server.pid").exists())
            self.assertFalse((repo / "logs" / "team-up" / "server.redacted.log").exists())

    def test_launcher_model_override_targets_only_gemini_video(self):
        source_script = Path(__file__).parents[1] / "macos-linux" / "start_team_up.sh"

        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            repo = root / "repo"
            script_dir = repo / "macos-linux"
            script_dir.mkdir(parents=True)
            script = script_dir / "start_team_up.sh"
            shutil.copy2(source_script, script)
            (repo / "requirements.txt").write_text("", encoding="utf-8")
            python = repo / ".venv" / "bin" / "python"
            python.parent.mkdir(parents=True)
            python.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            python.chmod(0o755)
            project = root / "project"
            project.mkdir()

            fake_bin = root / "bin"
            fake_bin.mkdir()
            (fake_bin / "lsof").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            (fake_bin / "tmux").write_text(
                "#!/bin/sh\n"
                "printf '%s\\n' \"$*\" >> \"$TEAM_UP_TMUX_LOG\"\n"
                "case \"$1\" in has-session) exit 1 ;; esac\n"
                "exit 0\n",
                encoding="utf-8",
            )
            for executable in fake_bin.iterdir():
                executable.chmod(0o755)

            tmux_log = root / "tmux.log"
            env = {
                **os.environ,
                "PATH": f"{fake_bin}:{os.environ['PATH']}",
                "GEMINI_API_KEY": "must-not-reach-tmux",
                "TEAM_UP_GEMINI_MODEL": "gemini-2.5-flash",
                "TEAM_UP_GEMINI_ENV_FILE": "/tmp/working-gemini.env",
                "TEAM_UP_TMUX_LOG": str(tmux_log),
            }
            subprocess.run(
                ["sh", str(script), str(project)],
                check=True,
                env=env,
                capture_output=True,
                text=True,
            )

            invocations = [
                command
                for command in tmux_log.read_text("utf-8").splitlines()
                if command.startswith(
                    "new-window -d -t =agentchattr-team-up-server "
                )
            ]
            gemini_invocation = next(
                invocation for invocation in invocations
                if "wrapper.py" in invocation and "gemini-video" in invocation
            )
            other_invocations = [
                invocation for invocation in invocations
                if invocation != gemini_invocation
            ]
            gemini_args = shlex.split(gemini_invocation)
            model_index = gemini_args.index("--model")
            self.assertEqual(gemini_args[model_index + 1], "gemini-2.5-flash")
            env_file_index = gemini_args.index("--env-file")
            self.assertEqual(
                gemini_args[env_file_index + 1],
                "/tmp/working-gemini.env",
            )
            self.assertTrue(
                all(
                    "--model" not in shlex.split(invocation)
                    and "--env-file" not in shlex.split(invocation)
                    for invocation in other_invocations
                )
            )
            tmux_commands = tmux_log.read_text("utf-8").splitlines()
            self.assertIn("set-environment -gu GEMINI_API_KEY", tmux_commands)
            self.assertNotIn("must-not-reach-tmux", tmux_log.read_text("utf-8"))

    def test_server_startup_output_does_not_print_session_token(self):
        import app
        import mcp_bridge
        import run
        import uvicorn

        class FakeApp:
            def get(self, path):
                return lambda function: function

            def mount(self, path, application, name):
                return None

            def on_event(self, event):
                return lambda function: function

        marker = "SESSION_TOKEN_MUST_NOT_PRINT"
        fake_app = FakeApp()
        output = StringIO()
        with (
            mock.patch.object(app, "app", fake_app),
            mock.patch.object(app, "configure"),
            mock.patch.object(run.secrets, "token_hex", return_value=marker),
            mock.patch.object(run.threading.Thread, "start"),
            mock.patch.object(run.time, "sleep"),
            mock.patch.object(mcp_bridge, "_load_cursors"),
            mock.patch.object(mcp_bridge, "_load_roles"),
            mock.patch.object(uvicorn, "run"),
            redirect_stdout(output),
        ):
            run.main()

        self.assertNotIn(marker, output.getvalue())

if __name__ == "__main__":
    unittest.main()
