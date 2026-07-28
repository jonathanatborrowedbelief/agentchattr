# agentchattr Session Context

## Completed

- Added the permanent Team Up v2 runtime, semantic six-phase session template, stable role identities, provider-specific launch arguments, secret-safe credential loading, and fixed-caption lifecycle activity.
- Added authenticated activity telemetry and focused Python/Node coverage.
- Hardened the Team Up launcher so generated web session tokens are not written to server logs.
- Replaced the verified legacy `run.py` listener and launched the worktree server on `127.0.0.1:8300` with MCP HTTP on `127.0.0.1:8200`.
- Kept the web session token in memory only during verification; no credential values were printed or persisted.
- Completed the final repair wave: detached agents restart, lifecycle changes broadcast directly, role rules load from the control root, post-registration failures deregister exactly once, explicit credential files override inherited values, the server is tmux-owned, and Gemini Video supports a launcher-only model override.

## Permanent roles and models

| Identity | Role | Configured model |
|---|---|---|
| `claude-lead` | Lead | Claude `opus`, high effort |
| `gemini-video` | Video | `gemini-2.5-pro` |
| `codex-luna` | Scout | `gpt-5.6-luna`, medium reasoning |
| `codex-terra` | Builder | `gpt-5.6-terra`, high reasoning |
| `codex-sol` | Integrator | `gpt-5.6-sol`, high reasoning |

## Launcher and credentials

- Launcher: `macos-linux/start_team_up.sh`
- Intended target command: `sh macos-linux/start_team_up.sh /Users/jonathan/Documents/Codex`
- Verified worktree smoke command: `env -u GEMINI_API_KEY sh macos-linux/start_team_up.sh /Users/jonathan/Documents/agentchattr/.worktrees/team-up-v2`
- Gemini credential source: `~/Workspace/AG_Shared/.env.master`
- Credential variable: `GEMINI_API_KEY`
- Never print or persist the credential value or the localhost web session token.

The configured credential file now overrides a stale inherited value when it supplies a non-empty selected key. `TEAM_UP_GEMINI_MODEL=gemini-2.5-flash` can temporarily override Gemini Video while `gemini-2.5-pro` remains the configured preference.

## Status-feed semantics

- Lifecycle states are `IDLE`, `WAITING`, `WORKING`, `DONE`, and `BLOCKED`.
- Events use fixed server captions such as `Terminal activity`, `Task queued`, and `Response posted`; raw terminal text is not exposed.
- Recent activity is read-only and bounded.
- Visible activity-store changes now schedule the existing status broadcast from any thread; invalid and visible no-op changes do not broadcast.

## Verification evidence

- Required focused Python suite: 38/38 passed.
- Node activity-status suite: 8/8 passed.
- Python compileall: passed.
- JavaScript syntax checks for `activity-status.js`, `chat.js`, and `sessions.js`: passed.
- Team Up launcher shell syntax: passed.
- `git diff --check`: passed.
- Broader explicit Python suite: 45/47 passed. The two errors are pre-existing archive tests failing because `MessageStore` has no `_save` attribute.
- Provider versions: Claude Code `2.1.220`, Gemini CLI `0.52.0`, Codex CLI `0.144.6`.
- Initial `/api/status` verification showed all five configured identities online with the correct labels and roles.
- Session 1 verified the correct default cast and progression through Align, Video Triage, and into Scout. Claude and Gemini posted `SMOKE_OK`.
- Full six-phase completion was not verified before the final repair wave. The detached-session restart regression is now fixed and covered, but the live five-agent smoke has not been rerun.
- Native video smoke was not verified. Gemini did not natively consume ignored `@data/team-up-smoke.mp4` and attempted shell fallbacks instead.
- The final review findings for direct lifecycle broadcasts, target-workspace role instructions, and stale post-registration identities are repaired and covered by regressions.
- Detailed evidence: `.superpowers/sdd/2026-07-27-team-up-v2/smoke-report.md`.

## Current runtime

- `agentchattr-team-up-server` remains the persistent owner for the worktree server.
- `claude-lead`, `gemini-video`, `codex-sol`, and `codex-terra` remain launched.
- `codex-luna` is not durably online, so the permanent five-agent requirement is blocked.
- Existing Metricool, YAP, and unrelated tmux sessions were not terminated.

## Next

Rerun the five-agent live smoke using the tmux-owned server and, while Pro quota remains unavailable, the Flash launcher override. Verify the full six-phase session and native `@relative/path.mp4` analysis before merging `codex/team-up-v2`.

## Blockers

- The repaired runtime has not yet completed a fresh five-agent live smoke.
- Configured `gemini-2.5-pro` quota was exhausted in the prior smoke; the launcher now supports the verified operational Flash override.
- The native ignored-video path did not produce three visual observations in chat.
- Two pre-existing archive tests still error.
