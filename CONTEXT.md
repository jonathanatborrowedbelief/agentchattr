# agentchattr Session Context

## Completed

- Added the permanent Team Up v2 runtime, semantic six-phase session template, stable role identities, provider-specific launch arguments, secret-safe credential loading, and fixed-caption lifecycle activity.
- Added authenticated activity telemetry and focused Python/Node coverage.
- Hardened the Team Up launcher so generated web session tokens are not written to server logs.
- Replaced the verified legacy `run.py` listener and launched the worktree server on `127.0.0.1:8300` with MCP HTTP on `127.0.0.1:8200`.
- Kept the web session token in memory only during verification; no credential values were printed or persisted.

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

The inherited Gemini credential in the verification shell returned HTTP 403, while the configured file credential returned `GEMINI_SMOKE_OK` on Flash. Until credential precedence is hardened, omit the inherited value when launching so the configured file is used.

## Status-feed semantics

- Lifecycle states are `IDLE`, `WAITING`, `WORKING`, `DONE`, and `BLOCKED`.
- Events use fixed server captions such as `Terminal activity`, `Task queued`, and `Response posted`; raw terminal text is not exposed.
- Recent activity is read-only and bounded.
- Final review found that activity-store state changes are not directly broadcast to WebSocket clients, so visible ordered transitions can be missed or become stale. This must be fixed before merge.

## Verification evidence

- Python suite: 34/36 passed. The two errors are pre-existing archive tests failing because `MessageStore` has no `_save` attribute.
- Node activity-status suite: 8/8 passed.
- Python compileall: passed.
- Team Up launcher shell syntax: passed.
- Provider versions: Claude Code `2.1.220`, Gemini CLI `0.52.0`, Codex CLI `0.144.6`.
- Initial `/api/status` verification showed all five configured identities online with the correct labels and roles.
- Session 1 verified the correct default cast and progression through Align, Video Triage, and into Scout. Claude and Gemini posted `SMOKE_OK`.
- Full six-phase completion was not verified. `codex-luna` later exited, and a second session reused `codex-sol` for both Scout and Integrator.
- Native video smoke was not verified. Gemini did not natively consume ignored `@data/team-up-smoke.mp4` and attempted shell fallbacks instead.
- Final high-capability review returned REQUEST CHANGES with three Important findings: missing direct lifecycle broadcasts, target-workspace role instructions not injected, and stale registration on post-registration startup failure.
- Detailed evidence: `.superpowers/sdd/2026-07-27-team-up-v2/smoke-report.md`.

## Current runtime

- `agentchattr-team-up-server` remains the persistent owner for the worktree server.
- `claude-lead`, `gemini-video`, `codex-sol`, and `codex-terra` remain launched.
- `codex-luna` is not durably online, so the permanent five-agent requirement is blocked.
- Existing Metricool, YAP, and unrelated tmux sessions were not terminated.

## Next

Do not merge yet. Fix the three Important review findings, diagnose the `codex-luna` startup exit, make native `@relative/path.mp4` analysis work without a shell fallback, and rerun all Task 5 gates. Once the full suite and live smoke are clean, merge `codex/team-up-v2` into `main` from `/Users/jonathan/Documents/agentchattr`.

## Blockers

- `codex-luna` exits after launch, breaking the five-agent roster and semantic default cast.
- Configured `gemini-2.5-pro` quota is exhausted; the file credential works with Flash.
- The native ignored-video path did not produce three visual observations in chat.
- Three Important source-review findings remain unresolved.
- Two pre-existing archive tests still error.
