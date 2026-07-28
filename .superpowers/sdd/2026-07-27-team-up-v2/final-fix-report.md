# Team Up v2 Final Fix Evidence

## Repairs

- Detached tmux sessions now enter the existing bounded restart path unless `--no-restart` is set.
- `AgentActivityStore` fires one secret-free callback only for visible snapshot changes; the FastAPI event loop schedules `broadcast_status()` for queue, chat, explicit activity, terminal, identity, and session lifecycle mutations.
- The five stable agents declare control-root `instructions_file` values. UTF-8 role text is capped at 16 KiB, injected under `ROLE INSTRUCTIONS:` on every trigger, and invalid files fail before registration.
- Registration cleanup is installed immediately after registration and attempts authenticated deregistration exactly once on return, `SystemExit`, or exception.
- A non-empty selected value in `env_file` overrides inherited environment; inherited non-empty values remain fallback when the file or key is unavailable.
- `start_team_up.sh` owns `run.py` in `agentchattr-team-up-server`; no server log or server PID file is created, and startup output does not print the web session token.
- `gemini-2.5-pro` remains configured. `TEAM_UP_GEMINI_MODEL` affects only Gemini Video, and runtime model merging leaves one effective `--model` flag.

## TDD evidence

- Initial focused RED: 37 tests ran; 8 failed and 5 errored on the seven missing behaviors.
- Stable-agent config RED mutation: 1 test ran and failed when `codex-luna` lacked `instructions_file`.
- Focused GREEN:
  - `.venv/bin/python -m unittest tests.test_team_up_runtime tests.test_agent_activity -v`
  - 38 tests ran; 38 passed.

## Required validation

- `node --test tests/activity-status.test.js`: 8 tests passed.
- `.venv/bin/python -m compileall -q .`: exit 0.
- `node --check static/activity-status.js`: exit 0.
- `node --check static/chat.js`: exit 0.
- `node --check static/sessions.js`: exit 0.
- `sh -n macos-linux/start_team_up.sh`: exit 0.
- `git diff --check`: exit 0.

## Broader check and residual blockers

- Explicit full Python module run: 47 tests ran; 45 passed and 2 errored.
- Both errors are pre-existing archive failures at `archive.py:355`: `MessageStore` has no `_save`.
- A fresh live five-agent/full six-phase/native-video smoke was not run in this repair wave. No existing Team Up, Metricool, YAP, or unrelated tmux session was stopped or mutated.
- Preferred Gemini Pro quota was blocked in the prior smoke; the new launcher-only Flash override is available for the next smoke.
