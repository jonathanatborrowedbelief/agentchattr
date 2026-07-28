# Team Up v2 smoke report — 2026-07-27

Status: **PASS — live runtime ready**

## Runtime

- Branch: `codex/team-up-v2`
- Control worktree: `/Users/jonathan/Documents/agentchattr/.worktrees/team-up-v2`
- Target workspace: `/Users/jonathan/Documents/Codex`
- Web: `http://127.0.0.1:8300`
- MCP HTTP: `http://127.0.0.1:8200`
- Durable tmux owner: `agentchattr-team-up-server`
- Owner windows: `server`, `wrapper-claude-lead`, `wrapper-gemini-video`, `wrapper-codex-sol`, `wrapper-codex-terra`, `wrapper-codex-luna`
- Visible role sessions: `agentchattr-claude-lead`, `agentchattr-gemini-video`, `agentchattr-codex-sol`, `agentchattr-codex-terra`, `agentchattr-codex-luna`

All five role panes were rooted in `/Users/jonathan/Documents/Codex`, survived an idempotent launcher rerun, and remained available after the session completed. Metricool, YAP, and unrelated tmux sessions were not restarted or terminated.

## Cast and six-phase session

Session 3 used the exact semantic cast:

| Role | Identity |
|---|---|
| Lead | `claude-lead` |
| Video | `gemini-video` |
| Scout | `codex-luna` |
| Builder | `codex-terra` |
| Integrator | `codex-sol` |

The chat recorded six ordered phase banners and one session-complete event:

1. Align + Plan — `claude-lead`, message 21
2. Video Triage — `gemini-video`, message 24
3. Scout — `codex-luna`, message 27
4. Build — `codex-terra`, message 29
5. Integrate + Smoke — `codex-sol`, message 32
6. Review + Done — `claude-lead`, message 34

Terra's phase message came from the correct stable sender but used generic `codex` in its body. Claude correctly flagged that one done-criterion defect. Terra then posted the exact correction in message 36:

`codex-terra | OpenAI GPT-5 (Codex) | Builder | SMOKE_OK`

That satisfied Claude's stated final blocker without rerunning a phase.

## Native video evidence

- Temporary fixture: unignored relative path `@smoke-media/team-up-smoke.mp4`
- Fixture: six seconds, three solid-color scenes
- Gemini constraint: no shell, ffprobe, ffmpeg, copying, or metadata inference
- Gemini result: `Red, Green, Blue`
- Chat evidence: message 24 from exact sender `gemini-video`

The ordered scene content was not present in the filename or metadata. Claude accepted the result as native multimodal evidence. The fixture was removed after verification, restoring the target workspace to its pre-smoke file state.

## Credentials and model

- Preferred configured model remains `gemini-2.5-pro`.
- Pro was quota-blocked.
- Session 3 native-video override: `gemini-2.5-flash`.
- Gemini CLI 0.52 no longer exposes `gemini-2.5-flash` as an interactive
  manual model and routed a clean relaunch to quota-blocked
  `gemini-3.5-flash`.
- Current verified interactive fallback: `gemini-3.1-flash-lite`.
- `TEAM_UP_GEMINI_ENV_FILE` selects a credential source by path without printing or copying the credential.
- The working local source was `/Users/jonathan/Workspace/AG_Archive/ig_scraper_2026-05-07/.env`.
- The shared `.env.master` key was stale/quota-blocked for this CLI flow.
- The localhost web token and both Gemini values remained in memory only and were never printed or persisted by the runtime.
- A final clean relaunch verified `CLAUDE_AUTO_TRIGGER_OK` and
  `GEMINI_31_TRIGGER_OK` without manual approval. Exact stable tmux session
  names and all six owner windows remained alive after the stability wait.
- The post-review reliability relaunch required the exact health marker, MCP
  listener, and exact five-agent cast, then verified `CLAUDE_FINAL_OK` and
  `GEMINI_FINAL_OK`.

## Activity feed

After completion `/api/status` reported all five exact identities available with their configured roles and `DONE` state. Recent activity remained bounded to eight fixed-caption events per identity, including `Task queued`, `Terminal activity`, `Tool activity`, and `Response posted`; raw terminal text was not exposed.

## Automated verification

| Check | Result |
|---|---|
| Focused Python runtime/session/activity suite | **58/58 passed** |
| Node activity-status suite | **8/8 passed** |
| Python full discovery | **61/63 passed; 2 pre-existing errors** |
| Python compileall | **Passed** |
| JavaScript syntax checks | **Passed** |
| Launcher shell syntax | **Passed** |
| `git diff --check` | **Passed** |

The two full-suite errors are unchanged archive-feature failures at `archive.py:355`: `MessageStore` has no `_save` attribute.

## Review history

- Final seven-finding repair review: PASS.
- Durable-wrapper review found and fixed server-pane recovery, exact tmux targeting, and dead-owner replacement.
- Re-review after exact session/window fixes: PASS.
- Live smoke then exposed and fixed non-interactive wrapper ownership, Gemini credential-source override, and selected-environment isolation.
- Final credential review verified fail-closed runtime overrides, cross-provider
  credential stripping, tmux cleanup, and secret-safe per-session injection:
  PASS.
- Final Claude auto-mode review: PASS.
- Final full-branch review found and repaired atomic phase advancement,
  per-trigger at-least-once queue delivery, exact health/readiness validation,
  and `api_key_env` isolation. Scoped reliability re-review: PASS.

No credential values, registration tokens, web session tokens, raw prompts, or unfiltered terminal buffers were written to this report.
