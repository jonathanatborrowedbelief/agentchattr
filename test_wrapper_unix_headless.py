"""Focused behavior tests for explicit Unix headless wrapper supervision."""

from contextlib import ExitStack
from pathlib import Path
from types import ModuleType, SimpleNamespace
import json
import os
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from unittest import mock

import wrapper
import wrapper_unix


class _DormantThread:
    """Keep wrapper background loops from starting during CLI-boundary tests."""

    def __init__(self, *args, **kwargs):
        pass

    def start(self):
        pass


class HeadlessUnixRunAgentTests(unittest.TestCase):
    def _run_agent(self, **overrides):
        arguments = {
            "command": "/bin/true",
            "extra_args": [],
            "cwd": "/tmp",
            "env": {},
            "queue_file": Path("/tmp/headless-test-queue.jsonl"),
            "agent": "headless-test",
            "no_restart": True,
            "start_watcher": lambda inject_fn: None,
            "session_name": "agentchattr-headless-test",
        }
        arguments.update(overrides)
        return wrapper_unix.run_agent(**arguments)

    def test_headless_supervises_child_without_attaching_until_it_exits(self):
        """Catch headless attaching or returning before the child disappears."""
        completed = SimpleNamespace(returncode=0)
        with (
            mock.patch.object(wrapper_unix, "_check_tmux"),
            mock.patch.object(
                wrapper_unix,
                "_session_exists",
                side_effect=[True, True, False],
            ) as session_exists,
            mock.patch.object(wrapper_unix.time, "sleep") as sleep,
            mock.patch.object(
                wrapper_unix.subprocess,
                "run",
                return_value=completed,
            ) as run,
        ):
            self._run_agent(headless=True)

        tmux_commands = [call.args[0] for call in run.call_args_list]
        self.assertTrue(any(command[1] == "new-session" for command in tmux_commands))
        self.assertFalse(any(command[1] == "attach-session" for command in tmux_commands))
        self.assertEqual(session_exists.call_count, 3)
        sleep.assert_called_once_with(1)

    def test_interactive_mode_still_attaches_once(self):
        """Catch the headless branch accidentally suppressing default attachment."""
        completed = SimpleNamespace(returncode=0)
        with (
            mock.patch.object(wrapper_unix, "_check_tmux"),
            mock.patch.object(wrapper_unix, "_session_exists", return_value=False),
            mock.patch.object(wrapper_unix.time, "sleep"),
            mock.patch.object(
                wrapper_unix.subprocess,
                "run",
                return_value=completed,
            ) as run,
        ):
            self._run_agent(headless=False)

        attach_calls = [
            call
            for call in run.call_args_list
            if call.args[0][1] == "attach-session"
        ]
        self.assertEqual(len(attach_calls), 1)


class HeadlessWrapperCliTests(unittest.TestCase):
    def _run_cli(self, platform: str, run_agent):
        with tempfile.TemporaryDirectory() as temporary_dir:
            config = {
                "server": {"data_dir": temporary_dir, "port": 8300},
                "agents": {
                    "test-agent": {
                        "provider": "claude",
                        "command": "python3",
                        "cwd": temporary_dir,
                    },
                },
                "mcp": {"http_port": 8200, "sse_port": 8201},
            }
            registration = {
                "name": "test-agent",
                "token": "test-token",
                "slot": 1,
            }
            cleanup = mock.Mock()
            argv = ["wrapper.py", "test-agent", "--headless", "--no-restart"]
            activity_checker = mock.Mock(return_value=False)

            patches = [
                mock.patch("config_loader.load_config", return_value=config),
                mock.patch.object(
                    wrapper,
                    "_register_configured_identity_with_retry",
                    return_value=registration,
                ),
                mock.patch.object(
                    wrapper,
                    "_build_provider_launch",
                    return_value=([], {}, {}, None),
                ),
                mock.patch.object(wrapper.shutil, "which", return_value="/usr/bin/python3"),
                mock.patch.object(wrapper.threading, "Thread", _DormantThread),
                mock.patch.object(wrapper.sys, "platform", platform),
                mock.patch.object(sys, "argv", argv),
            ]
            if platform == "win32":
                windows_module = ModuleType("wrapper_windows")
                windows_module.get_activity_checker = mock.Mock(
                    return_value=activity_checker,
                )
                windows_module.run_agent = run_agent
                patches.append(mock.patch.dict(
                    sys.modules,
                    {"wrapper_windows": windows_module},
                ))
            else:
                patches.extend([
                    mock.patch("wrapper_unix.get_activity_checker", return_value=activity_checker),
                    mock.patch("wrapper_unix.run_agent", run_agent),
                ])

            with ExitStack() as stack:
                for patcher in patches:
                    stack.enter_context(patcher)
                wrapper._run_main(cleanup)

        return run_agent.call_args.kwargs

    def test_headless_flag_is_forwarded_only_to_unix(self):
        """Catch an unparsed Unix flag or a Windows run_agent contract change."""
        unix_run_agent = mock.Mock()
        unix_kwargs = self._run_cli("linux", unix_run_agent)
        self.assertIs(unix_kwargs["headless"], True)
        self.assertNotIn("--headless", unix_kwargs["extra_args"])

        windows_run_agent = mock.Mock()
        windows_kwargs = self._run_cli("win32", windows_run_agent)
        self.assertNotIn("headless", windows_kwargs)
        self.assertNotIn("--headless", windows_kwargs["extra_args"])


@unittest.skipIf(sys.platform == "win32", "SIGTERM is a Unix process contract")
class HeadlessWrapperSignalTests(unittest.TestCase):
    def test_sigterm_unwinds_main_and_deregisters_authenticated_identity_once(self):
        """Catch SIGTERM bypassing main's authenticated registration cleanup."""
        with tempfile.TemporaryDirectory() as temporary_dir:
            temporary_path = Path(temporary_dir)
            ready_marker = temporary_path / "ready"
            cleanup_marker = temporary_path / "cleanup.jsonl"
            environment = os.environ.copy()
            environment.update({
                "WRAPPER_TEST_READY": str(ready_marker),
                "WRAPPER_TEST_CLEANUP": str(cleanup_marker),
            })
            child_code = textwrap.dedent(
                """
                import json
                import os
                from pathlib import Path
                import signal
                import sys

                import wrapper

                def fake_run_main(cleanup):
                    cleanup.install(8317, "sigterm-test", "authenticated-test-token")
                    Path(os.environ["WRAPPER_TEST_READY"]).write_text("ready", "utf-8")
                    signal.pause()
                    raise AssertionError("SIGTERM did not exit the wrapper")

                def fake_deregister(server_port, name, token):
                    payload = {"server_port": server_port, "name": name, "token": token}
                    with Path(os.environ["WRAPPER_TEST_CLEANUP"]).open("a", encoding="utf-8") as stream:
                        stream.write(json.dumps(payload) + "\\n")

                wrapper._run_main = fake_run_main
                wrapper._deregister_instance = fake_deregister
                sys.argv = ["wrapper.py", "sigterm-test", "--headless", "--no-restart"]
                wrapper.main()
                """
            )
            process = subprocess.Popen(
                [sys.executable, "-c", child_code],
                cwd=Path(wrapper.__file__).parent,
                env=environment,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            try:
                deadline = time.monotonic() + 5
                while not ready_marker.exists():
                    returncode = process.poll()
                    if returncode is not None:
                        self.fail(f"wrapper exited before SIGTERM with {returncode}")
                    if time.monotonic() >= deadline:
                        self.fail("wrapper did not signal readiness before SIGTERM")
                    time.sleep(0.01)

                os.kill(process.pid, signal.SIGTERM)
                returncode = process.wait(timeout=5)

                cleanup_records = [
                    json.loads(line)
                    for line in (
                        cleanup_marker.read_text("utf-8").splitlines()
                        if cleanup_marker.exists()
                        else []
                    )
                ]
                self.assertEqual(
                    (returncode, cleanup_records),
                    (0, [{
                        "server_port": 8317,
                        "name": "sigterm-test",
                        "token": "authenticated-test-token",
                    }]),
                )
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
