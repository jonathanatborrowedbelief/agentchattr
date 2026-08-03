import json
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import app
from session_engine import SessionEngine
from session_store import SessionStore, validate_session_template


ROOT = Path(__file__).parents[1]
TEMPLATE_PATH = ROOT / "session_templates" / "team-up-v2.json"
ROLES = ["lead", "video", "scout", "builder", "integrator"]
DEFAULT_CAST = {
    "lead": "claude-lead",
    "video": "gemini-video",
    "scout": "codex-luna",
    "builder": "codex-terra",
    "integrator": "codex-sol",
}


class _Request:
    def __init__(self, body):
        self._body = body

    async def json(self):
        return self._body


class _SessionStore:
    def __init__(self, template):
        self.template = template

    def get_template(self, template_id):
        return self.template if template_id == self.template["id"] else None


class _Registry:
    def __init__(self, agents):
        self.agents = agents

    def get_active_names(self):
        return list(self.agents)


class _SessionEngine:
    def __init__(self):
        self.started = None

    def start_session(self, template_id, channel, cast, started_by, goal, lease_key=None):
        self.started = {
            "template_id": template_id,
            "channel": channel,
            "cast": cast,
            "started_by": started_by,
            "goal": goal,
            "lease_key": lease_key,
        }
        return {"id": 1, **self.started}

    def emit_current_phase_banner(self, session):
        return None


class _MessageStore:
    def add(self, *args, **kwargs):
        return None


class _RecordingMessageStore:
    def __init__(self):
        self.callbacks = []
        self.added = []

    def on_message(self, callback):
        self.callbacks.append(callback)

    def add(self, *args, **kwargs):
        self.added.append(kwargs)


class _RecordingTrigger:
    def __init__(self):
        self.calls = []

    def trigger_sync(self, agent, channel, prompt):
        self.calls.append((agent, channel, prompt))


class _AgentRegistry:
    def __init__(self, agents):
        self.agents = set(agents)

    def is_registered(self, agent):
        return agent in self.agents


class TeamUpTemplateTests(unittest.TestCase):
    def test_template_is_valid_and_uses_every_role_with_one_output(self):
        self.assertTrue(TEMPLATE_PATH.exists(), "Team Up v2 template must exist")
        template = json.loads(TEMPLATE_PATH.read_text("utf-8"))

        self.assertEqual(validate_session_template(template), [])
        self.assertEqual(template["roles"], ROLES)
        self.assertEqual(template["default_cast"], DEFAULT_CAST)
        self.assertEqual(len(template["phases"]), 6)
        self.assertEqual(
            sum(bool(phase.get("is_output")) for phase in template["phases"]),
            1,
        )
        self.assertEqual(
            {role for phase in template["phases"] for role in phase["participants"]},
            set(ROLES),
        )

        with self.subTest("SessionStore loads the template"):
            store = SessionStore(":memory:", templates_dir=str(TEMPLATE_PATH.parent))
            self.assertEqual(store.get_template("team-up-v2")["default_cast"], DEFAULT_CAST)


class TeamUpBackendCastingTests(unittest.IsolatedAsyncioTestCase):
    async def _start_without_cast(self, template, online_agents):
        engine = _SessionEngine()
        request = _Request(
            {
                "template_id": template["id"],
                "channel": "general",
                "goal": "Ship the approved goal",
                "started_by": "user",
            }
        )
        with mock.patch.multiple(
            app,
            session_store=_SessionStore(template),
            session_engine=engine,
            registry=_Registry(online_agents),
            store=_MessageStore(),
        ):
            response = await app.start_session(request)
        return json.loads(response.body), engine.started

    async def test_no_explicit_cast_uses_semantic_defaults_not_registry_order(self):
        template = {"id": "team-up-v2", "roles": ROLES, "default_cast": DEFAULT_CAST}
        registry_order = [
            "codex-terra",
            "codex-sol",
            "codex-luna",
            "gemini-video",
            "claude-lead",
        ]

        response, started = await self._start_without_cast(template, registry_order)

        self.assertEqual(response["cast"], DEFAULT_CAST)
        self.assertEqual(started["cast"], DEFAULT_CAST)
        self.assertEqual(started["goal"], "Ship the approved goal")
        self.assertEqual(started["lease_key"], "team-up-shared-cast")

    async def test_missing_preferred_agents_fall_back_before_reusing(self):
        template = {
            "id": "fallback",
            "roles": ["alpha", "beta", "gamma", "delta"],
            "default_cast": {
                "alpha": "preferred-alpha",
                "beta": "offline-beta",
                "gamma": "preferred-gamma",
                "delta": "offline-delta",
            },
        }
        online = ["fallback-agent", "preferred-gamma", "preferred-alpha"]

        response, _ = await self._start_without_cast(template, online)

        self.assertEqual(
            response["cast"],
            {
                "alpha": "preferred-alpha",
                "beta": "fallback-agent",
                "gamma": "preferred-gamma",
                "delta": "fallback-agent",
            },
        )
        self.assertEqual(len(set(response["cast"].values())), len(online))


class TeamUpFrontendCastingTests(unittest.TestCase):
    def test_launcher_auto_cast_uses_semantic_defaults(self):
        script = """
const fs = require('fs');
const vm = require('vm');
const context = {
  window: {_messageRenderers: {}, escapeHtml: value => value},
  Hub: {on() {}},
  Store: {watch() {}},
  console,
  setTimeout,
  clearTimeout,
  fetch: async () => ({ok: true, json: async () => []}),
  alert() {},
  WebSocket: {OPEN: 1}
};
vm.createContext(context);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), context);
const cast = vm.runInContext(
  `_autoCast(
    ["lead", "video", "scout", "builder", "integrator"],
    ["codex-terra", "codex-sol", "codex-luna", "gemini-video", "claude-lead"],
    ${JSON.stringify(JSON.parse(process.argv[2]))}
  )`,
  context
);
process.stdout.write(JSON.stringify(cast));
"""
        result = subprocess.run(
            [
                "node",
                "-e",
                script,
                str(ROOT / "static" / "sessions.js"),
                json.dumps(DEFAULT_CAST),
            ],
            check=True,
            capture_output=True,
            text=True,
        )

        self.assertEqual(json.loads(result.stdout), DEFAULT_CAST)


class TeamUpSessionAdvancementTests(unittest.TestCase):
    def test_duplicate_expected_agent_messages_advance_only_one_phase(self):
        pending_timers = []

        class DeferredTimer:
            def __init__(self, interval, function, args=None, kwargs=None):
                self.function = function
                self.args = args or ()
                self.kwargs = kwargs or {}

            def start(self):
                pending_timers.append(self)

            def run(self):
                self.function(*self.args, **self.kwargs)

        template = {
            "id": "duplicate-delay",
            "name": "Duplicate delay",
            "roles": ["lead", "output"],
            "phases": [
                {
                    "name": "Plan",
                    "prompt": "Plan.",
                    "participants": ["lead"],
                },
                {
                    "name": "Output",
                    "prompt": "Deliver.",
                    "participants": ["output"],
                    "is_output": True,
                },
            ],
        }

        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            templates_dir = root / "templates"
            templates_dir.mkdir()
            (templates_dir / "duplicate-delay.json").write_text(
                json.dumps(template),
                encoding="utf-8",
            )
            sessions = SessionStore(
                str(root / "sessions.json"),
                templates_dir=str(templates_dir),
            )
            messages = _RecordingMessageStore()
            trigger = _RecordingTrigger()
            engine = SessionEngine(
                sessions,
                messages,
                trigger,
                registry=_AgentRegistry({"claude-lead", "codex-sol"}),
            )
            session = engine.start_session(
                "duplicate-delay",
                "general",
                {"lead": "claude-lead", "output": "codex-sol"},
                "user",
            )

            with mock.patch("session_engine.threading.Timer", DeferredTimer):
                engine._on_message(
                    {
                        "id": 101,
                        "sender": "claude-lead",
                        "type": "chat",
                        "channel": "general",
                    }
                )
                engine._on_message(
                    {
                        "id": 102,
                        "sender": "claude-lead",
                        "type": "chat",
                        "channel": "general",
                    }
                )

            self.assertEqual(len(pending_timers), 2)
            for timer in list(pending_timers):
                timer.run()

            current = sessions.get(session["id"])
            self.assertEqual(current["current_phase"], 1)
            self.assertEqual(current["current_turn"], 0)
            self.assertEqual(current["state"], "waiting")
            self.assertEqual(
                [call[0] for call in trigger.calls],
                ["claude-lead", "codex-sol"],
            )
            self.assertEqual(
                [message["text"] for message in messages.added],
                ["Phase: Output"],
            )

            pending_timers.clear()
            with mock.patch("session_engine.threading.Timer", DeferredTimer):
                engine._on_message(
                    {
                        "id": 103,
                        "sender": "codex-sol",
                        "type": "chat",
                        "channel": "general",
                    }
                )
            self.assertEqual(len(pending_timers), 1)
            pending_timers[0].run()

            completed = sessions.get(session["id"])
            self.assertEqual(completed["state"], "complete")
            self.assertEqual(completed["output_message_id"], 103)


class SharedCastLeaseTests(unittest.TestCase):
    def _store(self, root):
        templates_dir = root / "templates"
        templates_dir.mkdir()
        for template_id in ("video-lab", "publish-queue"):
            (templates_dir / f"{template_id}.json").write_text(
                json.dumps({
                    "id": template_id,
                    "name": template_id,
                    "roles": ["lead"],
                    "phases": [{"name": "Work", "prompt": "Work.", "participants": ["lead"]}],
                }),
                encoding="utf-8",
            )
        return SessionStore(str(root / "session_runs.json"), templates_dir=str(templates_dir))

    def test_shared_cast_owner_and_fifo_waiter_persist_across_restart(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            store = self._store(root)
            owner = store.create("video-lab", "video", {"lead": "claude-lead"}, "user", lease_key="team-up-shared-cast")
            queued = store.create("publish-queue", "publish", {"lead": "claude-lead"}, "user", lease_key="team-up-shared-cast")

            self.assertEqual(store.get_lease_owner("team-up-shared-cast"), owner["id"])
            self.assertEqual(queued["state"], "waiting_for_cast")

            restarted = SessionStore(str(root / "session_runs.json"), templates_dir=str(root / "templates"))
            self.assertEqual(restarted.get_lease_owner("team-up-shared-cast"), owner["id"])
            self.assertEqual(restarted.get(queued["id"])["state"], "waiting_for_cast")

    def test_engine_completion_terminalizes_and_promotes_in_one_persisted_handoff(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            store = self._store(root)
            messages = _RecordingMessageStore()
            trigger = _RecordingTrigger()
            engine = SessionEngine(store, messages, trigger, registry=_AgentRegistry({"claude-lead"}))
            first = engine.start_session("video-lab", "video", {"lead": "claude-lead"}, "user", lease_key="team-up-shared-cast")
            second = engine.start_session("publish-queue", "publish", {"lead": "claude-lead"}, "user", lease_key="team-up-shared-cast")
            saved = []
            original_save = store._save

            def record_save():
                original_save()
                saved.append(json.loads((root / "session_runs.json").read_text("utf-8")))

            store._save = record_save
            engine._advance_current(first, 101)

            handoff = saved[0]
            self.assertEqual(handoff["leases"]["team-up-shared-cast"]["owner"], second["id"])
            self.assertEqual(handoff["sessions"][0]["state"], "complete")
            self.assertEqual(store.get(second["id"])["state"], "waiting")
            self.assertEqual([call[0] for call in trigger.calls], ["claude-lead", "claude-lead"])

    def test_engine_interruption_promotes_fifo_once_and_duplicate_end_does_not(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            store = self._store(root)
            messages = _RecordingMessageStore()
            trigger = _RecordingTrigger()
            engine = SessionEngine(store, messages, trigger, registry=_AgentRegistry({"claude-lead"}))
            first = engine.start_session("video-lab", "video", {"lead": "claude-lead"}, "user", lease_key="team-up-shared-cast")
            second = engine.start_session("publish-queue", "publish", {"lead": "claude-lead"}, "user", lease_key="team-up-shared-cast")
            third = engine.start_session("video-lab", "review", {"lead": "claude-lead"}, "user", lease_key="team-up-shared-cast")

            ended = engine.end_session(first["id"])
            duplicate = engine.end_session(first["id"])

            self.assertEqual(ended["state"], "interrupted")
            self.assertIsNone(duplicate)
            self.assertEqual(store.get_lease_owner("team-up-shared-cast"), second["id"])
            self.assertEqual(store.get(second["id"])["state"], "waiting")
            self.assertEqual(store.get(third["id"])["state"], "waiting_for_cast")
            self.assertEqual([call[0] for call in trigger.calls], ["claude-lead", "claude-lead"])

    def test_restart_recovers_legacy_terminal_owner_and_prompts_fifo_waiter(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            store = self._store(root)
            first = store.create("video-lab", "video", {"lead": "claude-lead"}, "user", lease_key="team-up-shared-cast")
            second = store.create("publish-queue", "publish", {"lead": "claude-lead"}, "user", lease_key="team-up-shared-cast")
            path = root / "session_runs.json"
            raw = json.loads(path.read_text("utf-8"))
            raw["sessions"][0]["state"] = "complete"
            path.write_text(json.dumps(raw), encoding="utf-8")

            restarted = SessionStore(str(path), templates_dir=str(root / "templates"))
            trigger = _RecordingTrigger()
            engine = SessionEngine(restarted, _RecordingMessageStore(), trigger, registry=_AgentRegistry({"claude-lead"}))
            engine.resume_active_sessions()

            self.assertEqual(restarted.get_lease_owner("team-up-shared-cast"), second["id"])
            self.assertEqual(restarted.get(second["id"])["state"], "waiting")
            self.assertEqual([call[0] for call in trigger.calls], ["claude-lead"])

    def test_trigger_claim_cannot_resurrect_owner_ended_during_interleaving(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            store = self._store(root)
            owner = store.create("video-lab", "video", {"lead": "claude-lead"}, "user", lease_key="team-up-shared-cast")
            queued = store.create("publish-queue", "publish", {"lead": "claude-lead"}, "user", lease_key="team-up-shared-cast")
            trigger = _RecordingTrigger()
            engine = SessionEngine(store, _RecordingMessageStore(), trigger, registry=_AgentRegistry({"claude-lead"}))
            claim_entered = threading.Event()
            allow_old_claim = threading.Event()
            original_claim = store.claim_waiting

            def pause_old_claim(session_id, agent):
                if session_id == owner["id"]:
                    claim_entered.set()
                    allow_old_claim.wait(timeout=1)
                return original_claim(session_id, agent)

            store.claim_waiting = pause_old_claim
            runner = threading.Thread(target=engine._trigger_current, args=(owner,))
            runner.start()
            self.assertTrue(claim_entered.wait(timeout=1))
            engine.end_session(owner["id"])
            allow_old_claim.set()
            runner.join(timeout=1)

            self.assertFalse(runner.is_alive())
            self.assertEqual(store.get(owner["id"])["state"], "interrupted")
            self.assertEqual(store.get(queued["id"])["state"], "waiting")
            self.assertEqual([call[0] for call in trigger.calls], ["claude-lead"])

    def test_trigger_dispatch_is_cancelled_when_owner_ends_after_claim(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            store = self._store(root)
            owner = store.create("video-lab", "video", {"lead": "claude-lead"}, "user", lease_key="team-up-shared-cast")
            queued = store.create("publish-queue", "publish", {"lead": "claude-lead"}, "user", lease_key="team-up-shared-cast")
            trigger = _RecordingTrigger()
            engine = SessionEngine(store, _RecordingMessageStore(), trigger, registry=_AgentRegistry({"claude-lead"}))
            claim_returned = threading.Event()
            allow_dispatch = threading.Event()
            original_claim = engine._claim_waiting

            def pause_after_old_claim(session, agent):
                claimed = original_claim(session, agent)
                if session["id"] == owner["id"]:
                    claim_returned.set()
                    allow_dispatch.wait(timeout=1)
                return claimed

            engine._claim_waiting = pause_after_old_claim
            runner = threading.Thread(target=engine._trigger_current, args=(owner,))
            runner.start()
            self.assertTrue(claim_returned.wait(timeout=1))
            engine.end_session(owner["id"])
            allow_dispatch.set()
            runner.join(timeout=1)

            self.assertFalse(runner.is_alive())
            self.assertEqual(store.get(owner["id"])["state"], "interrupted")
            self.assertEqual(store.get(queued["id"])["state"], "waiting")
            self.assertEqual([call[0] for call in trigger.calls], ["claude-lead"])

    def test_only_owner_triggers_and_restart_does_not_retrigger_waiter(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            store = self._store(root)
            messages = _RecordingMessageStore()
            trigger = _RecordingTrigger()
            engine = SessionEngine(store, messages, trigger, registry=_AgentRegistry({"claude-lead"}))

            owner = engine.start_session("video-lab", "video", {"lead": "claude-lead"}, "user", lease_key="team-up-shared-cast")
            queued = engine.start_session("publish-queue", "publish", {"lead": "claude-lead"}, "user", lease_key="team-up-shared-cast")
            engine.resume_active_sessions()

            self.assertEqual(queued["state"], "waiting_for_cast")
            self.assertEqual([call[0] for call in trigger.calls], ["claude-lead"])

            _, promoted = store.terminalize_and_promote(owner["id"], "complete")
            engine._trigger_current(promoted)
            self.assertEqual([call[0] for call in trigger.calls], ["claude-lead", "claude-lead"])


class SharedCastStartApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_start_api_returns_queued_session_instead_of_conflict(self):
        template = {"id": "publish-queue", "roles": ["lead"], "default_cast": {"lead": "claude-lead"}}
        engine = _SessionEngine()
        engine.start_session = lambda *args, **kwargs: {
            "id": 2,
            "template_id": "publish-queue",
            "channel": "publish",
            "state": "waiting_for_cast",
        }
        request = _Request({"template_id": "publish-queue", "channel": "publish", "cast": {"lead": "claude-lead"}})
        with mock.patch.multiple(
            app,
            session_store=_SessionStore(template),
            session_engine=engine,
            registry=_Registry(["claude-lead"]),
            store=_MessageStore(),
        ):
            response = await app.start_session(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.body)["state"], "waiting_for_cast")


if __name__ == "__main__":
    unittest.main()
