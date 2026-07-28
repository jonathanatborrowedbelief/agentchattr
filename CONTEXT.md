# agentchattr Session Context

## Status

Permanent Team Up v2 is implemented, reviewed, smoke-tested, and live from the
`codex/team-up-v2` worktree. The web UI is `http://127.0.0.1:8300`; MCP HTTP is
`http://127.0.0.1:8200`.

## Permanent cast

| Identity | Role | Preferred configuration | Current live model |
|---|---|---|---|
| `claude-lead` | Lead | Claude `opus`, high effort, auto permission mode | Claude `opus` |
| `gemini-video` | Video | `gemini-2.5-pro` | `gemini-3.1-flash-lite` quota fallback |
| `codex-luna` | Scout | `gpt-5.6-luna`, medium reasoning | configured model |
| `codex-terra` | Builder | `gpt-5.6-terra`, high reasoning | configured model |
| `codex-sol` | Integrator | `gpt-5.6-sol`, high reasoning | configured model |

The semantic default cast and six-phase template are in
`session_templates/team-up-v2.json`.

## Launcher

Control worktree:

`/Users/jonathan/Documents/agentchattr/.worktrees/team-up-v2`

Current verified command:

```sh
TEAM_UP_GEMINI_MODEL=gemini-3.1-flash-lite \
TEAM_UP_GEMINI_ENV_FILE=/Users/jonathan/Workspace/AG_Archive/ig_scraper_2026-05-07/.env \
sh macos-linux/start_team_up.sh /Users/jonathan/Documents/Codex
```

Preferred-model command, when Pro quota is available:

```sh
TEAM_UP_GEMINI_ENV_FILE=/Users/jonathan/Workspace/AG_Archive/ig_scraper_2026-05-07/.env \
sh macos-linux/start_team_up.sh /Users/jonathan/Documents/Codex
```

The runtime reads only `GEMINI_API_KEY` from the selected file. Explicit
credential overrides fail closed. Every configured credential key is stripped
from unrelated provider parents; tmux global/server environments do not retain
the Gemini key. Credential values and the localhost web token are never printed
or persisted by the launcher.

## Live ownership

- Durable owner session: `agentchattr-team-up-server`
- Owner windows: `server`, `wrapper-claude-lead`, `wrapper-gemini-video`,
  `wrapper-codex-sol`, `wrapper-codex-terra`, `wrapper-codex-luna`
- Visible sessions: `agentchattr-claude-lead`, `agentchattr-gemini-video`,
  `agentchattr-codex-sol`, `agentchattr-codex-terra`, `agentchattr-codex-luna`
- All five visible sessions are rooted in `/Users/jonathan/Documents/Codex`.
- Existing Metricool, YAP, and unrelated tmux sessions were not stopped.

## Workflow evidence

- Session 3 completed all six phases with the exact five-role cast.
- Claude planned and audited; Luna scouted; Terra built; Sol integrated/smoked.
- Gemini natively analyzed `@smoke-media/team-up-smoke.mp4` without shell tools
  and returned the ordered scenes `Red, Green, Blue`.
- Six ordered phase banners and one session-complete event were recorded.
- Chat evidence: phase messages 21, 24, 27, 29, 32, and 34; Terra identity
  correction message 36.
- The temporary video fixture was removed after the smoke.
- A clean relaunch verified autonomous `CLAUDE_AUTO_TRIGGER_OK` and
  `GEMINI_31_TRIGGER_OK` chatter responses without manual approval.
- The final reliability relaunch passed the exact service, MCP-port, and
  five-identity readiness gate, then verified `CLAUDE_FINAL_OK` and
  `GEMINI_FINAL_OK`.
- The post-lock clean relaunch verified live chatter responses
  `CLAUDE_LIVE_A08C13F_OK` and `GEMINI_LIVE_A08C13F_OK`.

## Activity feed

- States: `IDLE`, `WAITING`, `WORKING`, `BLOCKED`, `DONE`.
- Recent activity is read-only and bounded to eight events per identity.
- Captions are fixed server values such as `Task queued`, `Terminal activity`,
  and `Response posted`; raw terminal text is not exposed through status.
- Visible lifecycle changes broadcast immediately.

## Verification

- Focused runtime/session/activity Python suite: 59/59 passed.
- Node activity-status suite: 8/8 passed.
- Full Python discovery: 62/64 passed; the only two errors are pre-existing
  archive tests at `archive.py:355` because `MessageStore._save` does not exist.
- Python compileall, JavaScript syntax checks, launcher shell syntax, and
  `git diff --check`: passed.
- Provider versions: Claude Code `2.1.220`, Gemini CLI `0.52.0`, Codex CLI
  `0.144.6`.
- Session advancement is atomic against duplicate delayed messages.
- Queue delivery is per-trigger and at-least-once across startup, restart, and
  tmux injection failure; pending batches are never cleared on wrapper start.
  Producer appends and consumer claims share a cross-process queue lock.
- The launcher requires the exact Team Up health marker, both ports 8300/8200,
  and exactly the five heartbeat-online stable identities before printing
  success.
- Scoped credential, auto-mode, queue/reliability, and final repair reviews:
  PASS.

## Remaining external constraints

- The preferred `gemini-2.5-pro` credential quota is currently exhausted.
- Gemini CLI 0.52 no longer offers `gemini-2.5-flash` as an interactive manual
  model and routed that override to quota-blocked `gemini-3.5-flash`.
- The verified live fallback is `gemini-3.1-flash-lite`; the earlier native-video
  workflow passed on Gemini Flash.
- The two pre-existing archive test errors are outside Team Up v2.

## Next

Choose whether to merge `codex/team-up-v2` into its base branch, create a pull
request, or keep the worktree branch as-is.
