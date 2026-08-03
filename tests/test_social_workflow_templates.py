import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import app
from session_engine import SessionEngine
from session_store import SessionStore, validate_session_template


ROOT = Path(__file__).parents[1]
TEMPLATES_DIR = ROOT / "session_templates"
AGENT_ROLES = ["lead", "video", "scout", "builder", "integrator"]
DEFAULT_CAST = {
    "lead": "claude-lead",
    "video": "gemini-video",
    "scout": "codex-luna",
    "builder": "codex-terra",
    "integrator": "codex-sol",
}


class _Messages:
    def __init__(self):
        self.callbacks = []

    def on_message(self, callback):
        self.callbacks.append(callback)

    def add(self, *args, **kwargs):
        return None


class _Trigger:
    def __init__(self):
        self.calls = []

    def trigger_sync(self, agent, channel, prompt):
        self.calls.append((agent, channel, prompt))


class _Registry:
    def __init__(self, names):
        self.names = set(names)

    def is_registered(self, name):
        return name in self.names


class _Request:
    def __init__(self, body):
        self.body = body

    async def json(self):
        return self.body


class _ApiSessionStore:
    def __init__(self, template):
        self.template = template

    def get_template(self, template_id):
        return self.template if template_id == self.template["id"] else None


class _ApiRegistry:
    def get_active_names(self):
        return list(DEFAULT_CAST.values())


class _ApiEngine:
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


class _ApiMessages:
    def add(self, *args, **kwargs):
        return None


class SocialWorkflowTemplateTests(unittest.TestCase):
    def test_seven_phase_templates_have_the_required_cast_and_prompts(self):
        expected = {
            "video-lab": [
                "Intake + Goal",
                "Visual Teardown",
                "Evidence + Decomposition",
                "Recreation Decision",
                "Production Package",
                "Integrate + QC",
                "Release",
            ],
            "publish-queue": [
                "Import",
                "Preflight",
                "Creative QC",
                "Human Approval",
                "Execute",
                "Reconcile",
                "Audit",
            ],
        }

        for template_id, phase_names in expected.items():
            with self.subTest(template_id=template_id):
                template = json.loads((TEMPLATES_DIR / f"{template_id}.json").read_text("utf-8"))
                self.assertEqual(validate_session_template(template), [])
                self.assertEqual(template["default_channel"], template_id)
                self.assertEqual(template["lease_key"], "team-up-shared-cast")
                self.assertEqual([phase["name"] for phase in template["phases"]], phase_names)
                self.assertEqual(len(template["phases"]), 7)
                self.assertTrue(all(len(phase["prompt"]) <= 200 for phase in template["phases"]))
                self.assertEqual(sum(bool(phase.get("is_output")) for phase in template["phases"]), 1)

                expected_roles = AGENT_ROLES if template_id == "video-lab" else [*AGENT_ROLES, "approver"]
                self.assertEqual(template["roles"], expected_roles)
                expected_cast = dict(DEFAULT_CAST)
                if template_id == "publish-queue":
                    expected_cast["approver"] = "Jonathan"
                self.assertEqual(template["default_cast"], expected_cast)
                if template_id == "publish-queue":
                    self.assertEqual(template["human_roles"], ["approver"])

    def test_template_validator_accepts_seven_phases_but_rejects_eight(self):
        phases = [
            {"name": f"Phase {index}", "participants": ["lead"], "prompt": "Work."}
            for index in range(1, 8)
        ]
        phases[-1]["is_output"] = True
        template = {"name": "Seven", "roles": ["lead"], "phases": phases}

        self.assertEqual(validate_session_template(template), [])
        template["phases"].append(
            {"name": "Phase 8", "participants": ["lead"], "prompt": "Work."}
        )
        self.assertIn("Too many phases (8, max 7)", validate_session_template(template))

    def test_session_store_loads_both_templates_after_restart(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            path = Path(temporary_dir) / "session_runs.json"
            initial = SessionStore(str(path), templates_dir=str(TEMPLATES_DIR))
            self.assertEqual(initial.get_template("video-lab")["default_channel"], "video-lab")
            self.assertEqual(initial.get_template("publish-queue")["default_channel"], "publish-queue")

            restarted = SessionStore(str(path), templates_dir=str(TEMPLATES_DIR))
            self.assertEqual(restarted.get_template("video-lab")["lease_key"], "team-up-shared-cast")
            self.assertEqual(restarted.get_template("publish-queue")["default_cast"]["approver"], "Jonathan")


class SocialWorkflowSettingsTests(unittest.TestCase):
    def test_load_settings_seeds_protected_channels_and_preserves_user_channels_on_restart(self):
        defaults = {
            "title": "agentchattr",
            "username": "user",
            "font": "sans",
            "channels": ["general"],
            "history_limit": "all",
            "contrast": "normal",
            "custom_roles": [],
        }
        with tempfile.TemporaryDirectory() as temporary_dir:
            settings_path = Path(temporary_dir) / "settings.json"
            settings_path.write_text(json.dumps({"channels": ["general", "client-work"]}), encoding="utf-8")
            configuration = {"server": {"data_dir": temporary_dir}}
            with mock.patch.object(app, "config", configuration), mock.patch.object(app, "room_settings", dict(defaults)):
                app._load_settings()
                self.assertEqual(app.room_settings["channels"], ["general", "client-work", "video-lab", "publish-queue"])
                app._save_settings()

                app.room_settings = dict(defaults)
                app._load_settings()
                self.assertEqual(app.room_settings["channels"], ["general", "client-work", "video-lab", "publish-queue"])
                self.assertEqual(len(app.room_settings["channels"]), 4)


class SocialWorkflowEngineTests(unittest.TestCase):
    def test_video_lab_advances_all_seven_phases_to_release(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            sessions = SessionStore(
                str(Path(temporary_dir) / "session_runs.json"),
                templates_dir=str(TEMPLATES_DIR),
            )
            trigger = _Trigger()
            engine = SessionEngine(
                sessions,
                _Messages(),
                trigger,
                registry=_Registry(DEFAULT_CAST.values()),
            )
            session = engine.start_session(
                "video-lab",
                "video-lab",
                DEFAULT_CAST,
                "user",
                lease_key="team-up-shared-cast",
            )

            for message_id in range(1, 8):
                current = sessions.get(session["id"])
                self.assertEqual(current["current_phase"], message_id - 1)
                engine._advance_current(current, message_id)

            completed = sessions.get(session["id"])
            self.assertEqual(completed["state"], "complete")
            self.assertEqual(completed["output_message_id"], 7)
            self.assertEqual(
                [call[0] for call in trigger.calls],
                ["claude-lead", "gemini-video", "codex-luna", "claude-lead", "codex-terra", "codex-sol", "claude-lead"],
            )

    def test_human_approval_waits_without_triggering_jonathan_then_advances(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            sessions = SessionStore(
                str(Path(temporary_dir) / "session_runs.json"),
                templates_dir=str(TEMPLATES_DIR),
            )
            trigger = _Trigger()
            engine = SessionEngine(
                sessions,
                _Messages(),
                trigger,
                registry=_Registry(DEFAULT_CAST.values()),
            )
            session = engine.start_session(
                "publish-queue",
                "publish-queue",
                {**DEFAULT_CAST, "approver": "Jonathan"},
                "user",
                lease_key="team-up-shared-cast",
            )

            for phase_index in range(3):
                current = sessions.get(session["id"])
                phase = sessions.get_template("publish-queue")["phases"][phase_index]
                agent = current["cast"][phase["participants"][0]]
                engine._advance_current(current, phase_index + 1)

            waiting = sessions.get(session["id"])
            self.assertEqual(waiting["current_phase"], 3)
            self.assertEqual(waiting["state"], "waiting")
            self.assertEqual(waiting["waiting_on"], "Jonathan")
            self.assertNotIn("Jonathan", [call[0] for call in trigger.calls])

            engine._advance_current(waiting, 4)
            advanced = sessions.get(session["id"])
            self.assertEqual(advanced["current_phase"], 4)
            self.assertEqual(advanced["waiting_on"], "codex-terra")


class SocialWorkflowStartApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_start_preserves_the_publish_template_human_approver(self):
        template = json.loads((TEMPLATES_DIR / "publish-queue.json").read_text("utf-8"))
        engine = _ApiEngine()
        with mock.patch.multiple(
            app,
            session_store=_ApiSessionStore(template),
            session_engine=engine,
            registry=_ApiRegistry(),
            store=_ApiMessages(),
        ):
            response = await app.start_session(_Request({"template_id": "publish-queue"}))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(engine.started["cast"]["approver"], "Jonathan")

    async def test_start_uses_template_default_channel_and_lease_key(self):
        template = json.loads((TEMPLATES_DIR / "video-lab.json").read_text("utf-8"))
        engine = _ApiEngine()
        with mock.patch.multiple(
            app,
            session_store=_ApiSessionStore(template),
            session_engine=engine,
            registry=_ApiRegistry(),
            store=_ApiMessages(),
        ):
            response = await app.start_session(_Request({"template_id": "video-lab"}))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(engine.started["channel"], "video-lab")
        self.assertEqual(engine.started["lease_key"], "team-up-shared-cast")
