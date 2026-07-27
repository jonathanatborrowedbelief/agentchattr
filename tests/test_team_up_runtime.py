import os
import shutil
import signal
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from wrapper import _merge_launch_args, _resolve_mcp_inject, _resolve_provider


class TeamUpRuntimeTests(unittest.TestCase):
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

            inherited = _load_selected_env(
                env_file=home_relative,
                keys=["GEMINI_API_KEY"],
                environ={"GEMINI_API_KEY": "inherited-secret"},
            )
            self.assertEqual(inherited, {"GEMINI_API_KEY": "inherited-secret"})

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

if __name__ == "__main__":
    unittest.main()
