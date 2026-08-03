import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from agent_activity import AgentActivityStore
from agents import AgentTrigger


class FakeClock:
    def __init__(self):
        self.now = 1_000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class AgentActivityStoreTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.store = AgentActivityStore(clock=self.clock)

    def test_terminal_activity_lease_returns_to_waiting(self):
        self.store.mark_queued("codex-terra", channel="build")
        self.assertEqual(self.store.snapshot("codex-terra")["state"], "WAITING")

        self.store.mark_terminal("codex-terra", active=True)
        self.assertEqual(self.store.snapshot("codex-terra")["state"], "WORKING")

        self.clock.advance(9)
        self.assertEqual(self.store.snapshot("codex-terra")["state"], "WAITING")

        self.store.mark_done("codex-terra", "response_posted")
        self.assertEqual(self.store.snapshot("codex-terra")["state"], "DONE")

    def test_inactive_terminal_heartbeat_does_not_create_done(self):
        self.store.mark_queued("codex-terra")
        self.store.mark_terminal("codex-terra", active=True)

        self.store.mark_terminal("codex-terra", active=False)

        snapshot = self.store.snapshot("codex-terra")
        self.assertEqual(snapshot["state"], "WAITING")
        self.assertNotIn("DONE", [event["state"] for event in snapshot["recent_events"]])

    def test_recent_events_are_bounded_to_eight(self):
        reasons = [
            "chat_read",
            "response_posted",
            "tests_complete",
            "external_blocker",
        ]
        for index in range(12):
            reason = reasons[index % len(reasons)]
            if reason == "chat_read":
                self.store.mark_tool("codex-terra", reason)
            elif reason in ("response_posted", "tests_complete"):
                self.store.mark_done("codex-terra", reason)
            else:
                self.store.mark_blocked("codex-terra", reason)
            self.clock.advance(1)

        snapshot = self.store.snapshot("codex-terra")
        self.assertEqual(len(snapshot["recent_events"]), 8)
        self.assertEqual(snapshot["recent_events"][0]["time"], 1_004.0)

    def test_adjacent_duplicate_events_are_coalesced(self):
        self.store.mark_tool("codex-terra", "chat_read")
        self.clock.advance(2)
        self.store.mark_tool("codex-terra", "chat_read")

        events = self.store.snapshot("codex-terra")["recent_events"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["count"], 2)
        self.assertEqual(events[0]["time"], 1_002.0)

    def test_change_callback_fires_only_for_visible_snapshot_changes(self):
        changed = mock.Mock()
        self.store.on_change(changed)

        self.store.mark_queued("codex-terra")
        self.store.mark_done("codex-terra", "response_posted")
        with self.assertRaises(ValueError):
            self.store.mark_done("codex-terra", "not-allowlisted")
        self.store.purge_identity("missing-agent")

        self.assertEqual(changed.call_count, 2)

    def test_identity_migration_and_purge(self):
        self.store.mark_done("codex-terra", "tests_complete")

        self.store.migrate_identity("codex-terra", "codex-builder")

        self.assertEqual(self.store.snapshot("codex-terra")["state"], "IDLE")
        self.assertEqual(self.store.snapshot("codex-builder")["state"], "DONE")
        self.assertEqual(
            self.store.snapshot("codex-builder")["event"]["reason"],
            "tests_complete",
        )

        self.store.purge_identity("codex-builder")
        self.assertEqual(
            self.store.snapshot("codex-builder"),
            {"state": "IDLE", "event": None, "recent_events": []},
        )

    def test_reason_codes_are_allowlisted(self):
        with self.assertRaises(ValueError):
            self.store.mark_tool("codex-terra", "reading prompt from /tmp")
        with self.assertRaises(ValueError):
            self.store.mark_done("codex-terra", "DONE")

    def test_control_characters_are_rejected(self):
        with self.assertRaises(ValueError):
            self.store.mark_queued("codex\nterra")
        with self.assertRaises(ValueError):
            self.store.mark_queued("codex-terra", channel="build\nsecret")

    def test_captions_are_fixed_server_values(self):
        expected = {
            "task_queued": "Task queued",
            "terminal_activity": "Terminal activity",
            "chat_read": "Reading chat",
            "response_posted": "Response posted",
            "session_paused": "Session paused",
            "missing_cast": "Missing session cast",
            "external_blocker": "Blocked by external dependency",
            "tests_complete": "Tests complete",
        }

        for reason, caption in expected.items():
            if reason == "task_queued":
                self.store.mark_queued(reason)
            elif reason == "terminal_activity":
                self.store.mark_terminal(reason, active=True)
            elif reason == "chat_read":
                self.store.mark_tool(reason, reason)
            elif reason in ("session_paused", "missing_cast", "external_blocker"):
                self.store.mark_blocked(reason, reason)
            else:
                self.store.mark_done(reason, reason)
            event = self.store.snapshot(reason)["event"]
            self.assertEqual(event["reason"], reason)
            self.assertEqual(event["text"], caption)
            self.assertLessEqual(len(event["text"]), 160)


class FakeRegistry:
    def __init__(self):
        self.instance = {
            "name": "codex-terra",
            "label": "Codex Terra",
            "color": "#10a37f",
            "state": "active",
        }

    def get_all(self):
        return {"codex-terra": self.instance}

    def is_registered(self, name):
        return name == self.instance["name"]

    def is_agent_family(self, name):
        return name.startswith("codex")

    def resolve_token(self, token):
        return self.instance if token == "valid-token" else None

    def resolve_name(self, name):
        return name

    def get_bases(self):
        return {"codex": {}}

    def family_instance_count(self, name):
        return 1

    def get_instance(self, name):
        return self.instance if name == self.instance["name"] else None

    def get_family_instance(self, base):
        return self.instance if base == "codex" else None

    def is_pending(self, name):
        return False


class FakeMessageStore:
    def __init__(self):
        self.messages = []
        self.callback = None

    def on_message(self, callback):
        self.callback = callback

    def add(self, sender, text, **kwargs):
        message = {
            "id": len(self.messages) + 1,
            "sender": sender,
            "text": text,
            "type": kwargs.get("msg_type", "chat"),
            "time": "12:00:00",
            "channel": kwargs.get("channel", "general"),
        }
        self.messages.append(message)
        return message

    def get_by_id(self, message_id):
        return next((msg for msg in self.messages if msg["id"] == message_id), None)

    def get_recent(self, limit, channel=None):
        messages = self.messages
        if channel:
            messages = [msg for msg in messages if msg["channel"] == channel]
        return messages[-limit:]

    def get_since(self, message_id, channel=None):
        messages = [msg for msg in self.messages if msg["id"] > message_id]
        if channel:
            messages = [msg for msg in messages if msg["channel"] == channel]
        return messages


def authenticated_context():
    request = SimpleNamespace(headers={"authorization": "Bearer valid-token"})
    return SimpleNamespace(request_context=SimpleNamespace(request=request))


class AgentActivityIntegrationTests(unittest.TestCase):
    def setUp(self):
        import mcp_bridge

        self.clock = FakeClock()
        self.activity = AgentActivityStore(clock=self.clock)
        self.registry = FakeRegistry()
        self.messages = FakeMessageStore()
        self.mcp_patches = [
            mock.patch.object(mcp_bridge, "activity_store", self.activity, create=True),
            mock.patch.object(mcp_bridge, "registry", self.registry),
            mock.patch.object(mcp_bridge, "store", self.messages),
            mock.patch.object(mcp_bridge, "_presence", {}),
            mock.patch.object(mcp_bridge, "_activity", {}),
            mock.patch.object(mcp_bridge, "_activity_ts", {}),
            mock.patch.object(mcp_bridge, "_cursors", {}),
            mock.patch.object(mcp_bridge, "_empty_read_count", {}),
        ]
        for patcher in self.mcp_patches:
            patcher.start()

    def tearDown(self):
        for patcher in reversed(self.mcp_patches):
            patcher.stop()

    def test_queue_write_sets_waiting_and_status_excludes_supplied_text(self):
        secrets = {
            "message": "MESSAGE_SECRET_3e51",
            "prompt": "PROMPT_SECRET_b901",
            "command": "COMMAND_SECRET_7c22",
            "environment": "ENV_SECRET_a835",
        }
        with tempfile.TemporaryDirectory() as temporary_dir:
            trigger = AgentTrigger(
                self.registry,
                data_dir=temporary_dir,
                activity_store=self.activity,
            )
            trigger.trigger_sync(
                "codex-terra",
                message=f"user: {secrets['message']}",
                channel="build",
                prompt=(
                    f"{secrets['prompt']} {secrets['command']} "
                    f"{secrets['environment']}"
                ),
            )

            status = trigger.get_status()["codex-terra"]
            queued = json.loads(
                (Path(temporary_dir) / "codex-terra_queue.jsonl").read_text("utf-8")
            )

        self.assertEqual(status["state"], "WAITING")
        self.assertEqual(status["event"]["reason"], "task_queued")
        self.assertEqual(len(status["recent_events"]), 1)
        self.assertIn(secrets["message"], queued["text"])
        serialized_status = json.dumps(status)
        for supplied in secrets.values():
            self.assertNotIn(supplied, serialized_status)

    def test_waiting_and_done_changes_schedule_status_broadcast(self):
        import app

        scheduled = []

        def capture(coroutine, loop):
            scheduled.append((coroutine, loop))
            coroutine.close()
            return mock.Mock()

        event_loop = mock.Mock()
        with (
            mock.patch.object(app, "activity_store", self.activity, create=True),
            mock.patch.object(app, "broadcast_status", mock.AsyncMock()),
            mock.patch.object(
                app.asyncio,
                "run_coroutine_threadsafe",
                side_effect=capture,
            ),
        ):
            app.set_event_loop(event_loop)
            self.activity.mark_queued("codex-terra")
            self.activity.mark_done("codex-terra", "response_posted")
            with self.assertRaises(ValueError):
                self.activity.mark_done("codex-terra", "not-allowlisted")
            self.activity.purge_identity("missing-agent")
            app.set_event_loop(None)

        self.assertEqual(len(scheduled), 2)
        self.assertTrue(all(loop is event_loop for _, loop in scheduled))

    def test_authenticated_heartbeat_creates_working_lease_without_false_done(self):
        import app

        request = SimpleNamespace(
            headers={"authorization": "Bearer valid-token"},
            json=mock.AsyncMock(return_value={"active": True}),
        )
        with (
            mock.patch.object(app, "registry", self.registry),
            mock.patch.object(app, "activity_store", self.activity, create=True),
            mock.patch.object(app, "broadcast_status", mock.AsyncMock()),
        ):
            response = asyncio.run(app.heartbeat("spoofed-name", request))
            self.assertEqual(response["name"], "codex-terra")
            self.assertEqual(self.activity.snapshot("codex-terra")["state"], "WORKING")

            request.json = mock.AsyncMock(return_value={"active": False})
            asyncio.run(app.heartbeat("spoofed-name", request))

        snapshot = self.activity.snapshot("codex-terra")
        self.assertNotEqual(snapshot["state"], "DONE")
        self.assertNotIn("DONE", [event["state"] for event in snapshot["recent_events"]])

    def test_chat_read_records_working_and_chat_send_records_done(self):
        import mcp_bridge

        self.messages.add("user", "Do the bounded task", channel="build")
        read_result = mcp_bridge.chat_read(
            sender="spoofed-name",
            channel="build",
            ctx=authenticated_context(),
        )
        self.assertIn("Do the bounded task", read_result)
        self.assertEqual(self.activity.snapshot("codex-terra")["state"], "WORKING")
        self.assertEqual(
            self.activity.snapshot("codex-terra")["event"]["reason"],
            "chat_read",
        )

        send_result = mcp_bridge.chat_send(
            sender="spoofed-name",
            message="Completed",
            choices=[],
            channel="build",
            ctx=authenticated_context(),
        )
        self.assertIn("Sent", send_result)
        self.assertEqual(self.activity.snapshot("codex-terra")["state"], "DONE")
        self.assertEqual(
            self.activity.snapshot("codex-terra")["event"]["reason"],
            "response_posted",
        )

    def test_unauthenticated_chat_calls_do_not_create_activity_identity(self):
        import mcp_bridge

        self.messages.add("user", "Public context", channel="general")

        read_result = mcp_bridge.chat_read(
            sender="dashboard-user",
            channel="general",
            ctx=None,
        )
        send_result = mcp_bridge.chat_send(
            sender="dashboard-user",
            message="Public reply",
            choices=[],
            channel="general",
            ctx=None,
        )

        self.assertIn("Public context", read_result)
        self.assertIn("Sent", send_result)
        self.assertEqual(
            self.activity.snapshot("dashboard-user"),
            {"state": "IDLE", "event": None, "recent_events": []},
        )

    def test_unauthenticated_active_heartbeat_is_rejected_without_activity(self):
        import app

        request = SimpleNamespace(
            headers={},
            json=mock.AsyncMock(return_value={"active": True}),
        )
        with (
            mock.patch.object(app, "registry", self.registry),
            mock.patch.object(app, "activity_store", self.activity, create=True),
            mock.patch.object(app, "broadcast_status", mock.AsyncMock()),
        ):
            response = asyncio.run(app.heartbeat("dashboard-user", request))

        self.assertEqual(getattr(response, "status_code", 200), 403)
        self.assertEqual(
            self.activity.snapshot("dashboard-user"),
            {"state": "IDLE", "event": None, "recent_events": []},
        )

    def test_raw_provider_pane_text_is_rejected_without_activity_or_api_echo(self):
        import app

        pane_secret = "PANE_SECRET_63de"
        request = SimpleNamespace(
            headers={"authorization": "Bearer valid-token"},
            json=mock.AsyncMock(return_value={
                "state": "manual_action_required",
                "reason_code": f"tool approval: {pane_secret}",
            }),
        )
        with (
            mock.patch.object(app, "registry", self.registry),
            mock.patch.object(app, "activity_store", self.activity, create=True),
        ):
            response = asyncio.run(app.report_provider_state("codex-terra", request))

        self.assertEqual(response.status_code, 400)
        self.assertNotIn(pane_secret.encode(), response.body)
        self.assertNotIn(pane_secret, json.dumps(self.activity.snapshot("codex-terra")))

    def test_chat_activity_rejects_unauthenticated_invalid_state_and_reason(self):
        import mcp_bridge

        self.assertIn(
            "authenticated",
            mcp_bridge.chat_activity(
                sender="codex-terra",
                state="DONE",
                reason="tests_complete",
                ctx=None,
            ),
        )
        self.assertIn(
            "state",
            mcp_bridge.chat_activity(
                sender="codex-terra",
                state="WAITING",
                reason="task_queued",
                ctx=authenticated_context(),
            ),
        )
        secret_reason = "finished command ENV_SECRET_2081"
        invalid_reason = mcp_bridge.chat_activity(
            sender="codex-terra",
            state="DONE",
            reason=secret_reason,
            ctx=authenticated_context(),
        )
        self.assertIn("reason", invalid_reason)
        self.assertNotIn(secret_reason, invalid_reason)

        result = mcp_bridge.chat_activity(
            sender="spoofed-name",
            state="DONE",
            reason="tests_complete",
            ctx=authenticated_context(),
        )
        self.assertIn("recorded", result.lower())
        self.assertEqual(
            self.activity.snapshot("codex-terra")["event"]["reason"],
            "tests_complete",
        )

    def test_human_session_interruption_records_blocked(self):
        from session_engine import SessionEngine

        class FakeSessionStore:
            def __init__(self):
                self.paused = []
                self.session = {
                    "id": 7,
                    "template_id": "build",
                    "channel": "build",
                    "state": "active",
                    "current_phase": 0,
                    "current_turn": 0,
                    "cast": {"builder": "codex-terra"},
                }

            def get_active(self, channel):
                return self.session

            def get_template(self, template_id):
                return {"phases": [{"participants": ["builder"]}]}

            def pause(self, session_id):
                self.paused.append(session_id)

        sessions = FakeSessionStore()
        engine = SessionEngine(
            sessions,
            self.messages,
            mock.Mock(),
            self.registry,
            activity_store=self.activity,
        )

        engine._on_message(
            {
                "id": 1,
                "sender": "user",
                "type": "chat",
                "channel": "build",
            }
        )

        self.assertEqual(sessions.paused, [7])
        self.assertEqual(self.activity.snapshot("codex-terra")["state"], "BLOCKED")
        self.assertEqual(
            self.activity.snapshot("codex-terra")["event"]["reason"],
            "session_paused",
        )

    def test_session_trigger_records_one_queued_event(self):
        from session_engine import SessionEngine

        class FakeSessionStore:
            def get_template(self, template_id):
                return {
                    "phases": [
                        {
                            "name": "Build",
                            "prompt": "Build the bounded slice",
                            "participants": ["builder"],
                        }
                    ]
                }

            def set_waiting(self, session_id, agent):
                return None

        sessions = FakeSessionStore()
        with tempfile.TemporaryDirectory() as temporary_dir:
            trigger = AgentTrigger(
                self.registry,
                data_dir=temporary_dir,
                activity_store=self.activity,
            )
            engine = SessionEngine(
                sessions,
                self.messages,
                trigger,
                self.registry,
                activity_store=self.activity,
            )
            engine._trigger_current(
                {
                    "id": 8,
                    "template_id": "build",
                    "channel": "build",
                    "current_phase": 0,
                    "current_turn": 0,
                    "cast": {"builder": "codex-terra"},
                }
            )

        snapshot = self.activity.snapshot("codex-terra")
        self.assertEqual(snapshot["state"], "WAITING")
        self.assertEqual(len(snapshot["recent_events"]), 1)
        self.assertEqual(snapshot["event"]["count"], 1)

    def test_failed_session_queue_write_does_not_claim_waiting(self):
        from session_engine import SessionEngine

        class FakeSessionStore:
            def get_template(self, template_id):
                return {
                    "phases": [
                        {
                            "name": "Build",
                            "prompt": "Build the bounded slice",
                            "participants": ["builder"],
                        }
                    ]
                }

            def set_waiting(self, session_id, agent):
                return None

        with tempfile.TemporaryDirectory() as temporary_dir:
            invalid_data_dir = Path(temporary_dir) / "not-a-directory"
            invalid_data_dir.write_text("occupied", encoding="utf-8")
            trigger = AgentTrigger(
                self.registry,
                data_dir=invalid_data_dir,
                activity_store=self.activity,
            )
            engine = SessionEngine(
                FakeSessionStore(),
                self.messages,
                trigger,
                self.registry,
                activity_store=self.activity,
            )

            engine._trigger_current(
                {
                    "id": 9,
                    "template_id": "build",
                    "channel": "build",
                    "current_phase": 0,
                    "current_turn": 0,
                    "cast": {"builder": "codex-terra"},
                }
            )

        self.assertEqual(
            self.activity.snapshot("codex-terra"),
            {"state": "IDLE", "event": None, "recent_events": []},
        )

    def test_missing_cast_records_blocked(self):
        from session_engine import SessionEngine

        class FakeSessionStore:
            def __init__(self):
                self.interrupted = []

            def get_template(self, template_id):
                return {
                    "phases": [
                        {
                            "name": "Build",
                            "prompt": "Build the bounded slice",
                            "participants": ["builder"],
                        }
                    ]
                }

            def interrupt(self, session_id, reason):
                self.interrupted.append((session_id, reason))

        sessions = FakeSessionStore()
        engine = SessionEngine(
            sessions,
            self.messages,
            mock.Mock(),
            self.registry,
            activity_store=self.activity,
        )
        engine._trigger_current(
            {
                "id": 8,
                "template_id": "build",
                "channel": "build",
                "current_phase": 0,
                "current_turn": 0,
                "cast": {},
            }
        )

        self.assertEqual(sessions.interrupted, [(8, "no agent for role 'builder'")])
        self.assertEqual(self.activity.snapshot("builder")["state"], "BLOCKED")


if __name__ == "__main__":
    unittest.main()
