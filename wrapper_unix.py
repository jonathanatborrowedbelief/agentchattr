"""Mac/Linux agent injection — uses tmux send-keys to type into the agent CLI.

Called by wrapper.py on Mac and Linux. Requires tmux to be installed.
  - Mac:   brew install tmux
  - Linux: apt install tmux  (or yum, pacman, etc.)

How it works:
  1. Creates a tmux session running the agent CLI
  2. Queue watcher sends keystrokes via 'tmux send-keys'
  3. Wrapper attaches to the session so you see the full TUI
  4. Ctrl+B, D to detach (agent keeps running in background)
"""

import shlex
import shutil
import subprocess
import sys
import threading
import time

from provider_readiness import classify_provider_screen


def _session_exists(session_name: str) -> bool:
    """Return True while the tmux session is still alive."""
    result = subprocess.run(
        ["tmux", "has-session", "-t", session_name],
        capture_output=True,
    )
    return result.returncode == 0


def _check_tmux():
    """Verify tmux is installed, exit with helpful message if not."""
    if shutil.which("tmux"):
        return
    print("\n  Error: tmux is required for auto-trigger on Mac/Linux.")
    if sys.platform == "darwin":
        print("  Install: brew install tmux")
    else:
        print("  Install: apt install tmux  (or yum/pacman equivalent)")
    sys.exit(1)


def inject(text: str, *, tmux_session: str, delay: float = 0.3):
    """Send text + Enter to a tmux session via send-keys."""
    # Use -l to send text literally (avoids misinterpreting as key names),
    # then send Enter as a separate key press
    typed = subprocess.run(
        ["tmux", "send-keys", "-t", tmux_session, "-l", text],
        capture_output=True,
    )
    if typed.returncode != 0:
        raise RuntimeError("tmux injection failed before prompt submission")
    # Let TUI process the text before sending Enter (matches Windows wrapper)
    time.sleep(delay)
    submitted = subprocess.run(
        ["tmux", "send-keys", "-t", tmux_session, "Enter"],
        capture_output=True,
    )
    if submitted.returncode != 0:
        raise RuntimeError("tmux injection failed during prompt submission")
    return True


def get_activity_checker(session_name, trigger_flag=None):
    """Return a callable that detects tmux pane output by hashing content."""
    last_hash = [None]

    def check():
        # External trigger: queue watcher injected a message
        if trigger_flag is not None and trigger_flag[0]:
            trigger_flag[0] = False
            return True
        try:
            result = subprocess.run(
                ["tmux", "capture-pane", "-t", session_name, "-p"],
                capture_output=True, timeout=2,
            )
            h = hash(result.stdout)
            changed = last_hash[0] is not None and h != last_hash[0]
            last_hash[0] = h
            return changed
        except Exception:
            return False

    return check


def _build_tmux_new_session_command(session_name, abs_cwd, agent_cmd, inject_env=None):
    """Build a tmux command that injects environment values per session."""
    tmux_command = ["tmux", "new-session", "-d", "-s", session_name, "-c", abs_cwd]
    for key, value in (inject_env or {}).items():
        tmux_command.extend(["-e", f"{key}={value}"])
    tmux_command.append(agent_cmd)
    return tmux_command


def _capture_pane_text(session_name: str) -> str | None:
    """Read a pane locally for readiness classification without logging it."""
    try:
        result = subprocess.run(
            ["tmux", "capture-pane", "-t", session_name, "-p"],
            capture_output=True,
            timeout=2,
        )
        if result.returncode != 0:
            return None
        return result.stdout.decode("utf-8", errors="replace")
    except Exception:
        return None


class _ProviderDeliveryGate:
    """Keep a long-lived queue watcher closed unless its child is ready."""

    def __init__(self, inject_fn, report_provider_state):
        self._inject_fn = inject_fn
        self._report_provider_state = report_provider_state
        self._ready = threading.Event()
        self._lock = threading.Lock()
        self._last_report = None

    def report(self, state, reason_code):
        with self._lock:
            if state == "provider_ready":
                self._ready.set()
            else:
                self._ready.clear()
            report = (state, reason_code)
            if report == self._last_report:
                return
            self._last_report = report
        self._report_provider_state(state, reason_code)

    def inject(self, prompt):
        with self._lock:
            if not self._ready.is_set():
                return False
            return self._inject_fn(prompt)


def _monitor_provider_readiness(
    session_name,
    provider,
    *,
    report_provider_state,
    start_watcher,
    inject_fn,
    poll_interval: float = 1,
    session_exists=_session_exists,
):
    """Poll one child pane and start queued delivery only after a ready prompt."""
    last_report = None
    watcher_started = False
    was_ready = False
    while session_exists(session_name):
        pane_text = _capture_pane_text(session_name)
        if not session_exists(session_name):
            break
        if pane_text is None:
            report = ("offline", "provider_offline")
        else:
            report = classify_provider_screen(provider, pane_text)
        if report != last_report:
            report_provider_state(*report)
            last_report = report
        if report[0] == "provider_ready" and not watcher_started:
            start_watcher(inject_fn)
            watcher_started = True
        was_ready = was_ready or report[0] == "provider_ready"
        time.sleep(poll_interval)
    if last_report != ("offline", "provider_offline"):
        report_provider_state("offline", "provider_offline")
    return was_ready


def run_agent(
    command,
    extra_args,
    cwd,
    env,
    queue_file,
    agent,
    no_restart,
    start_watcher,
    strip_env=None,
    pid_holder=None,
    session_name=None,
    inject_env=None,
    inject_delay: float = 0.3,
    provider: str | None = None,
    report_provider_state=None,
    readiness_poll_interval: float = 1,
):
    """Run agent inside a tmux session, inject via tmux send-keys."""
    _check_tmux()

    session_name = session_name or f"agentchattr-{agent}"
    agent_cmd = " ".join(
        [shlex.quote(command)] + [shlex.quote(a) for a in extra_args]
    )

    # Build an env(1) prefix only for unsetting variables. Values injected
    # into the session use tmux's -e flag below so secrets never enter the
    # shell command string.
    env_parts = []
    if strip_env:
        env_parts.extend(f"-u {shlex.quote(v)}" for v in strip_env)
    if env_parts:
        agent_cmd = f"env {' '.join(env_parts)} {agent_cmd}"

    # Resolve cwd to absolute path (tmux -c needs it)
    from pathlib import Path
    abs_cwd = str(Path(cwd).resolve())

    # The queue watcher is long-lived across child restarts. Its injector is
    # therefore gated per child session, not merely at first startup.
    inject_fn = lambda text: inject(text, tmux_session=session_name, delay=inject_delay)
    delivery_gate = (
        _ProviderDeliveryGate(inject_fn, report_provider_state)
        if report_provider_state is not None and provider
        else None
    )
    delivery_inject_fn = delivery_gate.inject if delivery_gate else inject_fn
    watcher_started = False
    watcher_lock = threading.Lock()
    child_session_active = None

    def start_watcher_once():
        nonlocal watcher_started
        with watcher_lock:
            if watcher_started:
                return
            start_watcher(delivery_inject_fn)
            watcher_started = True

    print(f"  Using tmux session: {session_name}")
    print(f"  Detach: Ctrl+B, D  (agent keeps running)")
    print(f"  Reattach: tmux attach -t {session_name}\n")

    while True:
        try:
            # Clean up stale session from a previous crash
            subprocess.run(
                ["tmux", "kill-session", "-t", session_name],
                capture_output=True,
            )

            # Create tmux session running the agent CLI
            tmux_command = _build_tmux_new_session_command(
                session_name, abs_cwd, agent_cmd, inject_env,
            )
            result = subprocess.run(tmux_command, env=env)
            if result.returncode != 0:
                if delivery_gate:
                    delivery_gate.report("offline", "provider_offline")
                print(f"  Error: failed to create tmux session (exit {result.returncode})")
                break
            if report_provider_state is None:
                start_watcher_once()
            elif provider:
                child_session_active = threading.Event()
                child_session_active.set()
                active_session = child_session_active
                threading.Thread(
                    target=_monitor_provider_readiness,
                    args=(session_name, provider),
                    kwargs={
                        "report_provider_state": delivery_gate.report,
                        "start_watcher": lambda _: start_watcher_once(),
                        "inject_fn": inject_fn,
                        "poll_interval": readiness_poll_interval,
                        "session_exists": lambda _, active_session=active_session: (
                            active_session.is_set()
                            and _session_exists(session_name)
                        ),
                    },
                    daemon=True,
                ).start()

            # Attach — blocks until agent exits or user detaches (Ctrl+B, D)
            subprocess.run(["tmux", "attach-session", "-t", session_name])

            # Check: did the agent exit, or did the user just detach?
            if _session_exists(session_name):
                # Session still alive — user detached, agent running in background.
                # Keep the wrapper alive so the local proxy and heartbeats survive.
                print(f"\n  Detached. {agent.capitalize()} still running in tmux.")
                print(f"  Reattach: tmux attach -t {session_name}")
                while _session_exists(session_name):
                    time.sleep(1)

            # Session gone — agent exited
            if child_session_active is not None:
                child_session_active.clear()
            if delivery_gate:
                delivery_gate.report("offline", "provider_offline")
            if no_restart:
                break

            print(f"\n  {agent.capitalize()} exited.")
            print(f"  Restarting in 3s... (Ctrl+C to quit)")
            time.sleep(3)
        except KeyboardInterrupt:
            if child_session_active is not None:
                child_session_active.clear()
            if delivery_gate:
                delivery_gate.report("offline", "provider_offline")
            # Kill the tmux session on Ctrl+C
            subprocess.run(
                ["tmux", "kill-session", "-t", session_name],
                capture_output=True,
            )
            break
