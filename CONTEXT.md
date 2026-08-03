# agentchattr Session Context

## Status

Permanent Team Up v2 and the social-workflow templates are implemented and
reviewed on `codex/team-up-v2`. The automated Task 6 reliability gates pass,
but the required live production-path smoke remains blocked after the third and
final authorized wrapper restart.
The web UI is `http://127.0.0.1:8300`; MCP HTTP is
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
- Task 6 restarted the isolated server on the current branch and attempted the
  five-wrapper relaunch inside the identity grace window. The abrupt owner-pane
  stop left live registrations, so the immediate replacements were correctly
  rejected rather than suffixed. After the 60-second crash cleanup, all five
  wrappers re-registered as exactly `claude-lead`, `gemini-video`, `codex-luna`,
  `codex-terra`, and `codex-sol`; no `-2` identity appeared.
- Commit `15c0cf5` recognizes the real provider-specific Claude, Gemini, and
  Codex composers with multiline horizontal-whitespace patterns. It also keeps
  unrelated project MCPs out of Claude Lead's strict config and disables the
  optional global `magic` and `apify` MCPs only for the three dedicated Codex
  wrappers.
- One graceful five-wrapper restart after `15c0cf5` brought all five exact
  identities online as `provider_ready/ready_prompt`, with no `-2` identities.
  The real private canary passed for `claude-lead` and `gemini-video`, then
  blocked on `response_timeout` for `codex-luna`, `codex-terra`, and
  `codex-sol`.
- Read-only, nonce-free diagnosis found all three Codex panes back at their real
  composer prompts with no detected MCP transport, unknown-tool, or approval
  error. Their queue files had no pending records, so the canary deliveries were
  claimed but produced no authenticated `chat_send` response before timeout.
- Commit `110c7a3` sets `inject_delay = 1.0` only for `codex-luna`,
  `codex-terra`, and `codex-sol`, preventing Enter from racing multiline paste
  ingestion. The permanent local `Always allow` permission for
  `agentchattr.chat_send` was applied before the final restart.
- The single authorized final restart retained exactly the five stable
  identities with no `-2`. Claude and all three Codex wrappers reported
  `provider_ready/ready_prompt`; Gemini reported `registered/unknown_screen`.
  The new canary passed only `claude-lead`; `gemini-video` and all three Codex
  identities blocked on `response_timeout`. Their queues had no pending records,
  and the Codex panes returned to ready composers without a visible MCP or
  approval error.
- Commit `ba1c5fd` replaces long multiline `tmux send-keys -l` streaming with
  a uniquely named stdin-loaded tmux buffer, bracketed `paste-buffer -p -d`,
  then delayed Enter. Prompt text never enters process arguments; failed paste
  cleans the buffer and propagates failure so the inflight queue remains
  retryable.
- The third and final authorized restart retained the exact five identities
  with no `-2`. Claude and Gemini reported `provider_ready/ready_prompt`; all
  three Codex wrappers reported `manual_action_required/tool_approval`. The
  canary passed `claude-lead`, blocked `gemini-video` on `nonce_mismatch`, and
  blocked Luna, Terra, and Sol on `tool_approval`.
- Because the production-path readiness gate stayed closed, no `video-lab` or
  `publish-queue` fixture session was started and no media or publishing action
  ran. The shared-cast live wait/promotion and live private-canary surface audit
  remain pending rather than being bypassed.

## Activity feed

- States: `IDLE`, `WAITING`, `WORKING`, `BLOCKED`, `DONE`.
- Recent activity is read-only and bounded to eight events per identity.
- Captions are fixed server values such as `Task queued`, `Terminal activity`,
  and `Response posted`; raw terminal text is not exposed through status.
- Visible lifecycle changes broadcast immediately.

## Verification

- Task 6 focused runtime/session/activity/archive/social-template suite:
  `127 passed, 16 subtests passed`.
- Node activity-status suite: 8/8 passed.
- Full Python discovery: `127 passed, 16 subtests passed`.
- Archive regression suite: 8/8 passed. Commit `60fc4db` replaces the removed
  `MessageStore._save()` call with a supported bulk flush after releasing the
  non-reentrant store lock, and adds a reload-based breadcrumb persistence test.
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

- Live Task 6 blocker after the third and final restart: Gemini returned a
  nonce mismatch, while all three Codex providers stopped at the authenticated
  `chat_send` tool approval gate. No further restart loop is authorized.
- The preferred `gemini-2.5-pro` credential quota is currently exhausted.
- Gemini CLI 0.52 no longer offers `gemini-2.5-flash` as an interactive manual
  model and routed that override to quota-blocked `gemini-3.5-flash`.
- The verified live fallback is `gemini-3.1-flash-lite`; the earlier native-video
  workflow passed on Gemini Flash.
- The archive baseline regression is repaired in `60fc4db`.

## Next

Resolve Gemini's exact nonce echo and the recurring Codex `chat_send` approval
gate without weakening the canary, then require all five exact identities to
pass the real private nonce canary.
Then run harmless `video-lab` and `publish-queue` fixtures to prove the second
waits for `team-up-shared-cast` and promotes after the first ends, and verify the
private channel/nonces are absent from UI, history, archive, summaries, and MCP
reads.

The video-lab plan may execute only after that canary passes and `video-lab`
acquires the shared cast. Publishing code may proceed independently, but no
`publish-queue` workflow start may bypass this gate.
