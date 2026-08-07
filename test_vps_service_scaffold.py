"""Behavior and contract tests for the local-only VPS deployment scaffold."""

from contextlib import contextmanager
from copy import deepcopy
import configparser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import socket
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
VPS_REQUIREMENTS_LOCK = ROOT / "deploy" / "vps" / "requirements.vps.lock"
VPS_TOOLCHAIN_LOCK = ROOT / "deploy" / "vps" / "toolchain.vps.lock.toml"
NPM_TOOLCHAIN_DIR = ROOT / "deploy" / "vps" / "npm-toolchain"
NPM_TOOLCHAIN_PACKAGE = NPM_TOOLCHAIN_DIR / "package.json"
NPM_TOOLCHAIN_LOCK = NPM_TOOLCHAIN_DIR / "package-lock.json"
TOOLCHAIN_NODE_BIN = "/opt/agentchattr/toolchain/node/bin"
TOOLCHAIN_NPM_BIN = "/opt/agentchattr/toolchain/npm/node_modules/.bin"
EXPECTED_NPM_DEPENDENCIES = {
    "@anthropic-ai/claude-code": "2.1.224",
    "@google/gemini-cli": "0.53.1",
    "@openai/codex": "0.146.0",
    "npm": "10.9.8",
}
EXPECTED_REQUIREMENTS = (
    "annotated-doc==0.0.4",
    "annotated-types==0.8.0",
    "anyio==4.14.2",
    "attrs==26.1.0",
    "certifi==2026.7.22",
    "cffi==2.1.0",
    "click==8.4.2",
    "cryptography==49.0.0",
    "fastapi==0.139.2",
    "h11==0.16.0",
    "httpcore==1.0.9",
    "httptools==0.8.0",
    "httpx==0.28.1",
    "httpx-sse==0.4.3",
    "idna==3.18",
    "jsonschema==4.26.0",
    "jsonschema-specifications==2025.9.1",
    "mcp==1.28.1",
    "pycparser==3.0",
    "pydantic==2.13.4",
    "pydantic-settings==2.14.2",
    "pydantic_core==2.46.4",
    "PyJWT==2.13.0",
    "python-dotenv==1.2.2",
    "python-multipart==0.0.32",
    "PyYAML==6.0.3",
    "referencing==0.37.0",
    "rpds-py==2026.6.3",
    "sse-starlette==3.4.6",
    "starlette==1.3.1",
    "typing-inspection==0.4.2",
    "typing_extensions==4.16.0",
    "uvicorn==0.51.0",
    "uvloop==0.22.1",
    "watchfiles==1.2.0",
    "websockets==16.1.1",
)


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


@contextmanager
def _tcp_endpoints(listening: tuple[bool, ...]):
    sockets = []
    try:
        for accepts_connections in listening:
            listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(("127.0.0.1", 0))
            if accepts_connections:
                listener.listen()
            sockets.append(listener)
        yield tuple(listener.getsockname()[1] for listener in sockets)
    finally:
        for listener in sockets:
            listener.close()


class WaitReadyCliTests(unittest.TestCase):
    def _run(
        self,
        *,
        payload: dict | None = None,
        raw_body: bytes | None = None,
        status: int = 200,
        mode: str,
        timeout_seconds: str = "0.05",
        listener_ports: tuple[int, ...] = (),
    ) -> tuple[subprocess.CompletedProcess[str], float]:
        body = raw_body if raw_body is not None else json.dumps(payload).encode()
        with _health_server(body, status=status) as url:
            started = time.monotonic()
            command = [
                    sys.executable,
                    str(WAIT_READY),
                    "--url",
                    url,
                    "--mode",
                    mode,
                    "--timeout-seconds",
                    timeout_seconds,
                ]
            if listener_ports:
                self.assertEqual(len(listener_ports), 2)
                command.extend(("--mcp-http-port", str(listener_ports[0])))
                command.extend(("--mcp-sse-port", str(listener_ports[1])))
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=2,
            )
            elapsed = time.monotonic() - started
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "")
        return result, elapsed

    def test_server_mode_accepts_health_only_when_both_tcp_listeners_accept(self):
        """Catch either required MCP listener being omitted from server readiness."""
        with _tcp_endpoints((True, True)) as ports:
            result, _ = self._run(
                payload={"service": "agentchattr-team-up-v2", "ready": False},
                mode="server",
                listener_ports=ports,
            )
        self.assertEqual(result.returncode, 0)

        with _tcp_endpoints((True, False)) as ports:
            result, _ = self._run(
                payload={"service": "agentchattr-team-up-v2", "ready": False},
                mode="server",
                listener_ports=ports,
            )
        self.assertNotEqual(result.returncode, 0)

    def test_server_mode_accepts_exact_service_before_team_ready(self):
        """Catch server ordering being coupled to provider/canary readiness."""
        with _tcp_endpoints((True, True)) as ports:
            result, _ = self._run(
                payload={"service": "agentchattr-team-up-v2", "ready": False},
                mode="server",
                listener_ports=ports,
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


def _normalized_pins(requirements: tuple[str, ...]) -> dict[str, str]:
    pins = {}
    for requirement in requirements:
        name, separator, version = requirement.partition("==")
        if separator != "==":
            raise AssertionError(f"requirement is not exactly pinned: {requirement}")
        normalized_name = re.sub(r"[-_.]+", "-", name.partition("[")[0]).lower()
        if normalized_name in pins:
            raise AssertionError(f"duplicate requirement: {normalized_name}")
        pins[normalized_name] = version
    return pins


class VpsToolchainLockTests(unittest.TestCase):
    def test_requirements_lock_matches_the_known_working_local_environment(self):
        """Catch Python dependency drift or an unhashed artifact entering the VPS lock."""
        logical_lines = []
        buffered = ""
        for raw_line in VPS_REQUIREMENTS_LOCK.read_text("utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            buffered += line.removesuffix("\\").strip() + " "
            if not line.endswith("\\"):
                logical_lines.append(buffered.strip())
                buffered = ""
        self.assertEqual(buffered, "")
        requirements = tuple(line.split()[0] for line in logical_lines)
        self.assertEqual(
            _normalized_pins(requirements),
            _normalized_pins(EXPECTED_REQUIREMENTS),
        )
        for requirement, line in zip(requirements, logical_lines, strict=True):
            with self.subTest(requirement=requirement):
                hashes = re.findall(r"--hash=sha256:([0-9a-f]{64})(?:\s|$)", line)
                self.assertGreaterEqual(len(hashes), 1)
                self.assertEqual(len(hashes), len(set(hashes)))

    def test_toolchain_lock_pins_node_and_every_provider_package_integrity(self):
        """Catch an unverified Node archive or provider package substitution."""
        with VPS_TOOLCHAIN_LOCK.open("rb") as stream:
            lock = tomllib.load(stream)

        self.assertEqual(
            lock["node"],
            {
                "version": "22.22.3",
                "platform": "linux-x64",
                "url": "https://nodejs.org/dist/v22.22.3/"
                "node-v22.22.3-linux-x64.tar.xz",
                "sha256": "2e5d13569282d016861fae7c8f935e741693c269101a5bebcf761a5376d1f99f",
            },
        )
        self.assertEqual(
            lock["npm"],
            {
                "version": "10.9.8",
                "tarball": "https://registry.npmjs.org/npm/-/npm-10.9.8.tgz",
                "integrity": "sha512-fYwb6ODSmHkqrJQQaCxY3M2lPf/mpgC7ik0HSzzIwG5CGtabRp4bNqikatvCoT42"
                "b5INQSqudVH0R7yVmC9hVg==",
                "prefix": "/opt/agentchattr/toolchain/npm",
                "bin_dir": TOOLCHAIN_NPM_BIN,
            },
        )
        self.assertEqual(
            lock["package"],
            [
                {
                    "name": "@anthropic-ai/claude-code",
                    "version": "2.1.224",
                    "integrity": "sha512-qvc2GFWIe3KrTgzx9hkOjHznpp6kmYSOC6o6F/"
                    "62u1lPPDtSrd+l6ZKYQ47idBmT/2eb/xQ/IoiP8zJBlpt53A==",
                },
                {
                    "name": "@openai/codex",
                    "version": "0.146.0",
                    "integrity": "sha512-yG3sPWNda/2YAIQIDq9MrrjoCTIQ7rxYM5IasrG3VBcuhCLTkgeg/"
                    "JzqmJq1V98RE4MJ5jCxDXXQlOjrditFRw==",
                },
                {
                    "name": "@google/gemini-cli",
                    "version": "0.53.1",
                    "integrity": "sha512-xBGdD/tl05gsTpD2oV1Bq0NCb4BBeTnjSbKxHtwOB7nt1QMaqWYJ9WsOE"
                    "sQQhQ2P1v0UJth1F17SAXvdZ5mASw==",
                },
            ],
        )

    def test_npm_toolchain_manifest_and_lock_pin_root_dependency_versions(self):
        """Catch a transitive dependency lock being omitted or root versions drifting."""
        package = json.loads(NPM_TOOLCHAIN_PACKAGE.read_text("utf-8"))
        lock = json.loads(NPM_TOOLCHAIN_LOCK.read_text("utf-8"))
        self.assertEqual(package["private"], True)
        self.assertEqual(package["engines"], {"node": "22.22.3"})
        self.assertEqual(package["dependencies"], EXPECTED_NPM_DEPENDENCIES)
        self.assertEqual(lock["lockfileVersion"], 3)
        self.assertEqual(lock["packages"][""]["dependencies"], EXPECTED_NPM_DEPENDENCIES)
        for package_name, version in EXPECTED_NPM_DEPENDENCIES.items():
            with self.subTest(package=package_name):
                self.assertEqual(
                    lock["packages"][f"node_modules/{package_name}"]["version"],
                    version,
                )
                self.assertIn(
                    "integrity",
                    lock["packages"][f"node_modules/{package_name}"],
                )


class VpsSystemdUnitTests(unittest.TestCase):
    def test_server_unit_uses_fixed_runtime_and_bounded_privileges(self):
        """Catch server execution as the wrong user/path or with broad writes."""
        unit = _unit("agentchattr-server.service")
        service = unit["Service"]
        self.assertEqual(
            service["ExecStart"],
            "/opt/agentchattr/current/.venv/bin/python /opt/agentchattr/current/run.py",
        )
        self.assertEqual(service["WorkingDirectory"], "/opt/agentchattr/current")
        self.assertEqual(service["User"], "agentchattr")
        self.assertEqual(service["Group"], "agentchattr")
        self.assertEqual(service["UMask"], "0077")
        self.assertEqual(service["Restart"], "on-failure")
        self.assertEqual(unit["Unit"]["StartLimitIntervalSec"], "300")
        self.assertEqual(unit["Unit"]["StartLimitBurst"], "5")
        self.assertEqual(service["MemoryHigh"], "512M")
        self.assertEqual(service["MemoryMax"], "768M")
        self.assertEqual(service["CPUQuota"], "100%")
        self.assertEqual(service["TasksMax"], "256")
        self.assertEqual(service["LimitNOFILE"], "8192")
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
            "--url http://127.0.0.1:8300/healthz --mode server --timeout-seconds 60 "
            "--listener-host 127.0.0.1 --mcp-http-port 8200 --mcp-sse-port 8201",
        )
        self.assertEqual(
            service["ExecStart"],
            "/opt/agentchattr/current/.venv/bin/python "
            "/opt/agentchattr/current/wrapper.py %i --headless --no-restart",
        )
        self.assertEqual(service["Restart"], "always")
        self.assertEqual(service["RestartSec"], "5")
        self.assertEqual(dependencies["StartLimitIntervalSec"], "300")
        self.assertEqual(dependencies["StartLimitBurst"], "5")
        self.assertEqual(service["MemoryHigh"], "1024M")
        self.assertEqual(service["MemoryMax"], "1536M")
        self.assertEqual(service["CPUQuota"], "150%")
        self.assertEqual(service["TasksMax"], "512")
        self.assertEqual(service["LimitNOFILE"], "8192")

    def test_worker_isolates_home_tmux_runtime_and_stop_cleanup(self):
        """Catch providers sharing CLI state/socket paths or surviving stop."""
        service = _unit("agentchattr-worker@.service")["Service"]
        environment = _words(service["Environment"])
        self.assertEqual(environment, {
            "HOME=/var/lib/agentchattr/home/%i",
            f"PATH={TOOLCHAIN_NPM_BIN}:{TOOLCHAIN_NODE_BIN}:/usr/bin:/bin",
            "SHELL=/bin/bash",
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
        timer_unit = _unit("agentchattr-health.timer")
        timer = timer_unit["Timer"]
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
        self.assertNotIn("Install", timer_unit)


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

    def test_config_uses_only_the_pinned_isolated_provider_commands(self):
        """Catch provider commands drifting back to shared /usr/local/bin tools."""
        agents = self._config()["agents"]
        expected_commands = {
            "claude-lead": f"{TOOLCHAIN_NPM_BIN}/claude",
            "gemini-video": f"{TOOLCHAIN_NPM_BIN}/gemini",
            "codex-sol": f"{TOOLCHAIN_NPM_BIN}/codex",
            "codex-terra": f"{TOOLCHAIN_NPM_BIN}/codex",
            "codex-luna": f"{TOOLCHAIN_NPM_BIN}/codex",
        }
        self.assertEqual(
            {identity: agent["command"] for identity, agent in agents.items()},
            expected_commands,
        )
        self.assertNotIn("/usr/local/bin", VPS_CONFIG.read_text("utf-8"))

    def test_readme_requires_isolated_pinned_install_and_human_provider_login(self):
        """Catch install/auth guidance that reuses Hermes credentials or automates login."""
        readme = (ROOT / "deploy" / "vps" / "README.md").read_text("utf-8")
        for required in (
            "requirements.vps.lock",
            "toolchain.vps.lock.toml",
            "/opt/agentchattr/toolchain/npm/node_modules/.bin",
            "npm ci --omit=dev --ignore-scripts",
            "node_modules/@anthropic-ai/claude-code/install.cjs",
            "already-installed locked optional package",
            "Hermes credential reuse is forbidden",
            "human gate",
            "claude auth login",
            "claude auth status",
            "codex login",
            "codex login status",
            "gemini --version",
            "agentchattr:agentchattr 0600",
            "root:agentchattr 0750",
            "build_release.py must not be used for VPS",
            "full `git archive`",
            "chown -R root:root",
            "chmod -R go-w",
            "--require-hashes",
        ):
            with self.subTest(required=required):
                self.assertIn(required, readme)
        self.assertNotIn(
            "sudo -u agentchattr /opt/agentchattr/current/.venv/bin/pip install",
            readme,
        )
        self.assertNotIn(
            "sudo -u agentchattr env PATH=/opt/agentchattr/toolchain/node/bin",
            readme,
        )
        self.assertRegex(
            readme,
            r"\.venv/bin/(?:python -m pip|pip) install \\\n"
            r"\s+--require-hashes \\\n"
            r"\s+-r /opt/agentchattr/current/deploy/vps/requirements\.vps\.lock",
        )
        self.assertNotIn("Version-only Python pins are an outstanding blocker", readme)

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
