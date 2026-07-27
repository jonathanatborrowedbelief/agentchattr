import json
import subprocess
import unittest
from pathlib import Path
from unittest import mock

import app
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

    def start_session(self, template_id, channel, cast, started_by, goal):
        self.started = {
            "template_id": template_id,
            "channel": channel,
            "cast": cast,
            "started_by": started_by,
            "goal": goal,
        }
        return {"id": 1, **self.started}

    def emit_current_phase_banner(self, session):
        return None


class _MessageStore:
    def add(self, *args, **kwargs):
        return None


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


if __name__ == "__main__":
    unittest.main()
