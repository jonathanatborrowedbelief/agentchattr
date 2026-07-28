import os
import shutil
import signal
import subprocess
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from wrapper import _merge_launch_args, _resolve_mcp_inject, _resolve_provider


class TeamUpRuntimeTests(unittest.TestCase):
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

    def test_selected_environment_reaches_tmux_for_inherited_values(self):
        from wrapper import _merge_selected_session_env
        from wrapper_unix import _build_tmux_new_session_command

        session_env = _merge_selected_session_env(
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

    def test_launcher_skips_a_live_wrapper_pid_when_tmux_is_not_ready(self):
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
            (fake_bin / "tmux").write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
            (fake_bin / "nohup").write_text(
                "#!/bin/sh\nexec sleep 30\n",
                encoding="utf-8",
            )
            for executable in fake_bin.iterdir():
                executable.chmod(0o755)

            env = {
                **os.environ,
                "PATH": f"{fake_bin}:{os.environ['PATH']}",
            }
            started_pids: list[int] = []
            try:
                subprocess.run(["sh", str(script), str(project)], check=True, env=env, capture_output=True, text=True)
                first_pids = {path.name: path.read_text("utf-8") for path in (repo / ".pids").glob("*.pid")}
                started_pids = [int(pid) for pid in first_pids.values()]
                subprocess.run(["sh", str(script), str(project)], check=True, env=env, capture_output=True, text=True)
                second_pids = {path.name: path.read_text("utf-8") for path in (repo / ".pids").glob("*.pid")}
                self.assertEqual(second_pids, first_pids)
            finally:
                for pid in started_pids:
                    try:
                        os.kill(pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass

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
            python.write_text(
                "#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$TEAM_UP_PYTHON_LOG\"\n",
                encoding="utf-8",
            )
            python.chmod(0o755)
            project = root / "project"
            project.mkdir()

            fake_bin = root / "bin"
            fake_bin.mkdir()
            (fake_bin / "lsof").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            (fake_bin / "tmux").write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
            for executable in fake_bin.iterdir():
                executable.chmod(0o755)

            python_log = root / "python.log"
            env = {
                **os.environ,
                "PATH": f"{fake_bin}:{os.environ['PATH']}",
                "TEAM_UP_GEMINI_MODEL": "gemini-2.5-flash",
                "TEAM_UP_PYTHON_LOG": str(python_log),
            }
            subprocess.run(
                ["sh", str(script), str(project)],
                check=True,
                env=env,
                capture_output=True,
                text=True,
            )
            for _ in range(20):
                if python_log.exists() and len(python_log.read_text("utf-8").splitlines()) == 5:
                    break
                time.sleep(0.01)

            invocations = python_log.read_text("utf-8").splitlines()
            gemini_invocation = next(
                invocation for invocation in invocations
                if "wrapper.py gemini-video " in invocation
            )
            other_invocations = [
                invocation for invocation in invocations
                if "wrapper.py gemini-video " not in invocation
            ]
            self.assertIn("--model gemini-2.5-flash", gemini_invocation)
            self.assertTrue(all("--model" not in invocation for invocation in other_invocations))

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
