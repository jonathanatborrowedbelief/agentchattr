"""Behavior and contract tests for the local-only VPS deployment scaffold."""

from contextlib import contextmanager
from copy import deepcopy
import configparser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
import tomllib
import unittest


ROOT = Path(__file__).resolve().parent
WAIT_READY = ROOT / "deploy" / "vps" / "wait_ready.py"
EXPECTED_IDENTITIES = {
    "claude-lead",
    "gemini-video",
    "codex-sol",
    "codex-terra",
    "codex-luna",
}
SYSTEMD_DIR = ROOT / "deploy" / "vps" / "systemd"
VPS_CONFIG = ROOT / "deploy" / "vps" / "config.vps.toml.example"


def _team_health() -> dict:
    return {
        "service": "agentchattr-team-up-v2",
        "ready": True,
        "agents": {
            identity: {
                "online": True,
                "provider_state": "provider_ready",
                "reason_code": "ready_prompt",
            }
            for identity in EXPECTED_IDENTITIES
        },
        "canary": {
            "state": "passed",
            "complete": True,
            "agents": {
                identity: {
                    "state": "passed",
                    "reason": "response_verified",
                }
                for identity in EXPECTED_IDENTITIES
            },
        },
    }


@contextmanager
def _health_server(body: bytes, status: int = 200):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/healthz"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)


class WaitReadyCliTests(unittest.TestCase):
    def _run(
        self,
        *,
        payload: dict | None = None,
        raw_body: bytes | None = None,
        status: int = 200,
        mode: str,
        timeout_seconds: str = "0.05",
    ) -> tuple[subprocess.CompletedProcess[str], float]:
        body = raw_body if raw_body is not None else json.dumps(payload).encode()
        with _health_server(body, status=status) as url:
            started = time.monotonic()
            result = subprocess.run(
                [
                    sys.executable,
                    str(WAIT_READY),
                    "--url",
                    url,
                    "--mode",
                    mode,
                    "--timeout-seconds",
                    timeout_seconds,
                ],
                capture_output=True,
                text=True,
                timeout=2,
            )
            elapsed = time.monotonic() - started
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "")
        return result, elapsed

    def test_server_mode_accepts_exact_service_before_team_ready(self):
        """Catch server ordering being coupled to provider/canary readiness."""
        result, _ = self._run(
            payload={"service": "agentchattr-team-up-v2", "ready": False},
            mode="server",
        )
        self.assertEqual(result.returncode, 0)

    def test_server_mode_rejects_the_wrong_service(self):
        """Catch an unrelated process on port 8300 satisfying ordering."""
        result, _ = self._run(
            payload={"service": "unrelated-service", "ready": True},
            mode="server",
        )
        self.assertNotEqual(result.returncode, 0)

    def test_team_mode_accepts_exact_ready_cast_and_passed_canary(self):
        """Catch the complete five-provider success contract being rejected."""
        result, _ = self._run(payload=_team_health(), mode="team")
        self.assertEqual(result.returncode, 0)

    def test_team_mode_rejects_extra_identity(self):
        """Catch a suffixed or unrelated identity entering the pilot cast."""
        payload = _team_health()
        payload["agents"]["codex-sol-2"] = deepcopy(payload["agents"]["codex-sol"])
        result, _ = self._run(payload=payload, mode="team")
        self.assertNotEqual(result.returncode, 0)

    def test_team_mode_rejects_missing_identity(self):
        """Catch aggregate readiness passing with an incomplete cast."""
        payload = _team_health()
        del payload["agents"]["codex-luna"]
        result, _ = self._run(payload=payload, mode="team")
        self.assertNotEqual(result.returncode, 0)

    def test_team_mode_rejects_non_ready_provider(self):
        """Catch online presence being mistaken for provider readiness."""
        payload = _team_health()
        payload["agents"]["claude-lead"] = {
            "online": True,
            "provider_state": "registered",
            "reason_code": "unknown_screen",
        }
        result, _ = self._run(payload=payload, mode="team")
        self.assertNotEqual(result.returncode, 0)

    def test_team_mode_rejects_incomplete_or_failed_canary(self):
        """Catch readiness passing before every private canary response verifies."""
        fixtures = []
        incomplete = _team_health()
        incomplete["canary"]["complete"] = False
        fixtures.append(incomplete)
        failed = _team_health()
        failed["canary"]["state"] = "blocked"
        failed["canary"]["agents"]["gemini-video"] = {
            "state": "blocked",
            "reason": "response_timeout",
        }
        fixtures.append(failed)

        for payload in fixtures:
            with self.subTest(canary_state=payload["canary"]["state"]):
                result, _ = self._run(payload=payload, mode="team")
                self.assertNotEqual(result.returncode, 0)

    def test_malformed_json_fails_silently(self):
        """Catch malformed response data being accepted or printed."""
        result, _ = self._run(raw_body=b"not-json", mode="team")
        self.assertNotEqual(result.returncode, 0)

    def test_http_error_fails_silently(self):
        """Catch HTTP response bodies leaking through readiness diagnostics."""
        result, _ = self._run(
            raw_body=b"private upstream detail",
            status=503,
            mode="server",
        )
        self.assertNotEqual(result.returncode, 0)

    def test_timeout_is_bounded_and_polls_transient_failure(self):
        """Catch one-shot checks or unbounded waits replacing deadline polling."""
        result, elapsed = self._run(
            raw_body=b"temporary failure",
            status=503,
            mode="server",
            timeout_seconds="0.2",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertGreaterEqual(elapsed, 0.15)
        self.assertLess(elapsed, 1.5)


def _unit(name: str) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(
        interpolation=None,
        strict=True,
        empty_lines_in_values=False,
    )
    parser.optionxform = str
    with (SYSTEMD_DIR / name).open("r", encoding="utf-8") as stream:
        parser.read_file(stream)
    return parser


def _words(value: str) -> set[str]:
    return set(value.split())


class VpsSystemdUnitTests(unittest.TestCase):
    def test_server_unit_uses_fixed_runtime_and_bounded_privileges(self):
        """Catch server execution as the wrong user/path or with broad writes."""
        service = _unit("agentchattr-server.service")["Service"]
        self.assertEqual(
            service["ExecStart"],
            "/opt/agentchattr/current/.venv/bin/python /opt/agentchattr/current/run.py",
        )
        self.assertEqual(service["WorkingDirectory"], "/opt/agentchattr/current")
        self.assertEqual(service["User"], "agentchattr")
        self.assertEqual(service["Group"], "agentchattr")
        self.assertEqual(service["UMask"], "0077")
        self.assertEqual(service["Restart"], "on-failure")
        self.assertEqual(service["NoNewPrivileges"], "true")
        self.assertEqual(service["PrivateTmp"], "true")
        self.assertEqual(service["ProtectSystem"], "strict")
        self.assertEqual(service["ReadWritePaths"], "/var/lib/agentchattr")
        self.assertEqual(service["CapabilityBoundingSet"], "")
        self.assertEqual(service["AmbientCapabilities"], "")
        self.assertEqual(
            service["BindReadOnlyPaths"],
            "/etc/agentchattr/config.toml:/opt/agentchattr/current/config.toml",
        )

    def test_worker_waits_for_server_and_uses_headless_single_restart_owner(self):
        """Catch workers racing startup or nesting wrapper restart supervision."""
        unit = _unit("agentchattr-worker@.service")
        dependencies = unit["Unit"]
        service = unit["Service"]
        self.assertEqual(dependencies["Requires"], "agentchattr-server.service")
        self.assertIn("agentchattr-server.service", _words(dependencies["After"]))
        self.assertEqual(
            service["ExecStartPre"],
            "/opt/agentchattr/current/.venv/bin/python "
            "/opt/agentchattr/current/deploy/vps/wait_ready.py "
            "--url http://127.0.0.1:8300/healthz --mode server --timeout-seconds 60",
        )
        self.assertEqual(
            service["ExecStart"],
            "/opt/agentchattr/current/.venv/bin/python "
            "/opt/agentchattr/current/wrapper.py %i --headless --no-restart",
        )
        self.assertEqual(service["Restart"], "always")
        self.assertEqual(service["RestartSec"], "5")

    def test_worker_isolates_home_tmux_runtime_and_stop_cleanup(self):
        """Catch providers sharing CLI state/socket paths or surviving stop."""
        service = _unit("agentchattr-worker@.service")["Service"]
        environment = _words(service["Environment"])
        self.assertEqual(environment, {
            "HOME=/var/lib/agentchattr/home/%i",
            "TMUX_TMPDIR=/run/agentchattr-%i",
        })
        self.assertEqual(service["RuntimeDirectory"], "agentchattr-%i")
        self.assertEqual(service["RuntimeDirectoryMode"], "0700")
        self.assertEqual(service["KillMode"], "control-group")
        self.assertEqual(service["TimeoutStopSec"], "30")
        self.assertEqual(
            service["ExecStop"],
            "-/usr/bin/env TMUX_TMPDIR=/run/agentchattr-%i "
            "/usr/bin/tmux kill-session -t agentchattr-%i",
        )

    def test_worker_hardening_keeps_only_required_state_and_network_families(self):
        """Catch broad filesystem access or hardening that blocks API network/JIT."""
        service = _unit("agentchattr-worker@.service")["Service"]
        self.assertEqual(service["User"], "agentchattr")
        self.assertEqual(service["Group"], "agentchattr")
        self.assertEqual(service["UMask"], "0077")
        self.assertEqual(service["NoNewPrivileges"], "true")
        self.assertEqual(service["PrivateTmp"], "true")
        self.assertEqual(service["ProtectSystem"], "strict")
        self.assertEqual(
            _words(service["ReadWritePaths"]),
            {"/var/lib/agentchattr", "/run/agentchattr-%i"},
        )
        self.assertEqual(
            _words(service["RestrictAddressFamilies"]),
            {"AF_UNIX", "AF_INET", "AF_INET6"},
        )
        self.assertNotIn("MemoryDenyWriteExecute", service)
        self.assertEqual(service["CapabilityBoundingSet"], "")
        self.assertEqual(service["AmbientCapabilities"], "")

    def test_team_target_enumerates_only_the_five_stable_workers(self):
        """Catch duplicate/generic identities or implicit boot enablement."""
        unit = _unit("agentchattr-team-up.target")
        expected_units = {
            f"agentchattr-worker@{identity}.service"
            for identity in EXPECTED_IDENTITIES
        }
        self.assertEqual(_words(unit["Unit"]["Wants"]), expected_units)
        self.assertEqual(_words(unit["Unit"]["After"]), expected_units)
        self.assertNotIn("Install", unit)

    def test_health_timer_runs_only_provider_aware_team_readiness_each_minute(self):
        """Catch the timer sending messages, retrying canaries, or using weak health."""
        health = _unit("agentchattr-health.service")["Service"]
        timer = _unit("agentchattr-health.timer")["Timer"]
        self.assertEqual(health["Type"], "oneshot")
        self.assertEqual(health["User"], "agentchattr")
        self.assertEqual(
            health["ExecStart"],
            "/opt/agentchattr/current/.venv/bin/python "
            "/opt/agentchattr/current/deploy/vps/wait_ready.py "
            "--url http://127.0.0.1:8300/healthz --mode team --timeout-seconds 30",
        )
        self.assertEqual(timer["OnUnitActiveSec"], "1min")
        self.assertEqual(timer["Unit"], "agentchattr-health.service")
        self.assertNotIn("ExecStart", timer)


class VpsConfigTemplateTests(unittest.TestCase):
    def _config(self) -> dict:
        with VPS_CONFIG.open("rb") as stream:
            return tomllib.load(stream)

    def test_config_binds_loopback_exact_ports_and_isolated_state(self):
        """Catch public listeners or data/uploads escaping the VPS boundary."""
        config = self._config()
        self.assertEqual(config["server"], {
            "host": "127.0.0.1",
            "port": 8300,
            "data_dir": "/var/lib/agentchattr/data",
        })
        self.assertEqual(config["mcp"], {"http_port": 8200, "sse_port": 8201})
        self.assertEqual(
            config["images"]["upload_dir"],
            "/var/lib/agentchattr/uploads",
        )

    def test_config_contains_only_exact_dedicated_role_worktrees(self):
        """Catch generic duplicates, suffix collisions, or shared worktrees."""
        agents = self._config()["agents"]
        self.assertEqual(set(agents), EXPECTED_IDENTITIES)
        for identity, agent in agents.items():
            with self.subTest(identity=identity):
                self.assertIs(agent["dedicated_identity"], True)
                self.assertEqual(
                    agent["cwd"],
                    f"/var/lib/agentchattr/worktrees/{identity}",
                )
                self.assertTrue(Path(agent["command"]).is_absolute())

    def test_config_uses_proven_role_models_without_approval_bypass(self):
        """Catch model drift or unsafe non-interactive approval behavior."""
        agents = self._config()["agents"]
        expected = {
            "claude-lead": ("claude", "Lead", "opus"),
            "gemini-video": ("gemini", "Video", "gemini-3.1-flash-lite"),
            "codex-sol": ("codex", "Integrator", "gpt-5.6-sol"),
            "codex-terra": ("codex", "Builder", "gpt-5.6-terra"),
            "codex-luna": ("codex", "Scout", "gpt-5.6-luna"),
        }
        forbidden = {
            "--dangerously-bypass-approvals-and-sandbox",
            "--permission-mode",
            "--yolo",
            "--full-auto",
        }
        for identity, (provider, role, model) in expected.items():
            with self.subTest(identity=identity):
                agent = agents[identity]
                launch_args = agent["launch_args"]
                self.assertEqual(agent["provider"], provider)
                self.assertEqual(agent["role"], role)
                self.assertIn("--model", launch_args)
                self.assertEqual(
                    launch_args[launch_args.index("--model") + 1],
                    model,
                )
                self.assertTrue(forbidden.isdisjoint(launch_args))

    def test_gemini_credential_contract_is_path_only_and_secret_free(self):
        """Catch an embedded credential or credential source outside /etc."""
        config = self._config()
        gemini = config["agents"]["gemini-video"]
        self.assertEqual(
            gemini["env_file"],
            "/etc/agentchattr/secrets/gemini-video.env",
        )
        self.assertEqual(gemini["env_keys"], ["GEMINI_API_KEY"])
        raw = VPS_CONFIG.read_text("utf-8")
        self.assertNotRegex(
            raw,
            r"(?im)(api[_-]?key|token|password)\s*=\s*['\"][^'\"]+",
        )


if __name__ == "__main__":
    unittest.main()
