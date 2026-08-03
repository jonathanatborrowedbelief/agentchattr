# Agent Chatter Social Workflows Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the five-agent Team Up launcher truthfully ready, keep exact identities stable across restarts, serialize the shared cast, and persist the `video-lab` and `publish-queue` workflows.

**Architecture:** The registry owns stable identity and provider state; wrappers report sanitized provider readiness; a private nonce canary validates the real queue-to-provider-to-`chat_send` path; the session store owns a persistent global cast lease and FIFO queue. Existing sessions/channels remain the user-facing surface.

**Tech Stack:** Python 3, FastAPI, tmux wrappers, JSON persistence, vanilla JavaScript, `unittest`/`pytest`, Node test harness.

## Global Constraints

- Work only in `/Users/jonathan/Documents/agentchattr/.worktrees/team-up-v2` on branch `codex/team-up-v2`.
- Preserve unrelated untracked `.pids/`; never stage or delete it.
- Exact dedicated identities are `claude-lead`, `gemini-video`, `codex-luna`, `codex-terra`, and `codex-sol`.
- Heartbeat/process existence never implies provider readiness.
- Never expose terminal text, secrets, canary nonces, or raw provider replies in health, chat, summaries, archives, or activity.
- New workflow starts fail closed until all five canaries pass. Existing Studio schedules are outside Agent Chatter and continue independently.
- No live social publishing, OAuth, credential changes, or media downloads belong in this plan.
- Use TDD, `apply_patch`, narrow tests first, and one focused commit per task.

---

## Task 1: Guarantee exact dedicated identity reacquisition

**Files:** `config.toml`, `registry.py`, `app.py`, `wrapper.py`, `tests/test_team_up_runtime.py`

- [ ] Add failing tests proving a dedicated identity restarts as the exact base name during the generic 30-second grace window, a second live registration gets HTTP 409, and generic multi-instance allocation still uses suffixes/reservations.
- [ ] Add `dedicated_identity = true` only to the five Team Up agents in `config.toml`.
- [ ] Add a typed `IdentityConflict` and retain the dedicated flag inside registry base configuration. The registry—not a caller parameter—must choose the dedicated path.
- [ ] In `RuntimeRegistry.register`, let a dedicated base claim only its exact name, bypass `_reserved`, and reject a truly live duplicate. In `deregister`, do not reserve dedicated names. Preserve all generic-family rename behavior.
- [ ] Map `IdentityConflict` to HTTP 409 in `app.register_agent`; keep unknown-base and generic responses unchanged.
- [ ] Ensure wrapper registration and heartbeat re-registration retain the configured exact identity rather than adopting a generated suffix.
- [ ] Run `python3 -m pytest tests/test_team_up_runtime.py -q`. Expected: pass.
- [ ] Commit `config.toml registry.py app.py wrapper.py tests/test_team_up_runtime.py` as `fix(team-up): stabilize dedicated identities`.

## Task 2: Separate provider readiness from heartbeat

**Files:** create `provider_readiness.py`; modify `registry.py`, `app.py`, `wrapper.py`, `wrapper_unix.py`, `tests/test_team_up_runtime.py`

- [ ] Add failing classifier tests for a usable prompt and four blockers: update dialog, trust screen, MCP startup failure, and tool approval. Unknown screens must remain `registered`, never ready.
- [ ] Implement the sanitized interface:

```python
ProviderState = Literal["registered", "provider_ready", "manual_action_required", "offline"]
def classify_provider_screen(provider: str, pane_text: str) -> tuple[ProviderState, str]: ...
```

Reason codes are allowlisted strings such as `update_dialog`; pane text is never returned.

- [ ] Add readiness fields to `Instance` and authenticated `RuntimeRegistry.report_provider_state(token, state, reason_code)`. Heartbeat updates presence only.
- [ ] Add a loopback/authenticated provider-state endpoint in `app.py`; reject unknown states/reasons and sender/token mismatches.
- [ ] Change `wrapper_unix.run_agent` to poll the child pane, classify it, report status, and start the queue watcher only after `provider_ready`.
- [ ] Change `/api/team-up/health` so each identity reports sanitized online/provider state and aggregate `ready` remains false for any non-ready identity.
- [ ] Test that raw pane strings and secret-shaped fixture text never appear in API results or activity.
- [ ] Run `python3 -m pytest tests/test_team_up_runtime.py tests/test_agent_activity.py -q`. Expected: pass.
- [ ] Commit as `feat(team-up): report provider readiness`.

## Task 3: Validate the production path with a private five-agent canary

**Files:** create `startup_canary.py`; modify `app.py`, `store.py`, `mcp_bridge.py`, `macos-linux/start_team_up.sh`; extend `tests/test_team_up_runtime.py`

- [ ] Write failing tests for all-five success, wrong sender, wrong/replayed nonce, timeout, manual-action result, and restart reset.
- [ ] Implement:

```python
class StartupCanary:
    PRIVATE_CHANNEL = "__team-up-startup-canary"
    def begin(self) -> None: ...
    def observe(self, message: dict) -> None: ...
    def snapshot(self) -> dict: ...
```

Generate one cryptographically random nonce per exact identity. Send through the unchanged `AgentTrigger.trigger_sync` production queue path. Success requires the matching authenticated sender to call `chat_send` with the exact nonce in the private channel.

- [ ] Hide the private channel from normal history, WebSocket broadcast, summaries, archives, all-channel MCP reads, sessions, and channel CRUD. Delete raw canary messages after observation; retain only identity/state/reason/timestamp.
- [ ] Construct/start the canary after all wrappers report provider-ready. Make team-up health ready only after the canary snapshot passes.
- [ ] Change `start_team_up.sh` to poll canary-complete health and print the exact blocked identity plus sanitized reason on timeout.
- [ ] Run `python3 -m pytest tests/test_team_up_runtime.py tests/test_archive_feature.py -q`. Expected: pass with no nonce leakage.
- [ ] Commit as `feat(team-up): add five-agent startup canary`.

## Task 4: Persist and serialize the shared cast lease

**Files:** `session_store.py`, `session_engine.py`, `app.py`, `static/sessions.js`, `static/channels.js`, `tests/test_team_up_session.py`

- [ ] Add failing tests: `video-lab` acquires `team-up-shared-cast`; `publish-queue` becomes `waiting_for_cast`; completion and interruption promote FIFO; restart preserves owner/queue; duplicate completion cannot double-promote.
- [ ] Extend `SessionStore.create(..., lease_key: str | None = None)`. Persist lease/queue in `session_runs.json` under the store lock.
- [ ] Add `get_lease_owner(lease_key)` and atomic `release_and_promote(session_id)`. Never invoke callbacks while holding a non-reentrant store lock.
- [ ] Trigger only lease owners. Recover active and queued sessions on restart without re-queuing an already delivered participant prompt.
- [ ] Return the queued session from the start-session API instead of false 409 when another workflow owns the cast.
- [ ] Render `waiting_for_cast` in session and channel UI.
- [ ] Run `python3 -m pytest tests/test_team_up_session.py -q` and `node --test tests/activity-status.test.js`. Expected: pass.
- [ ] Commit as `feat(sessions): serialize shared team-up cast`.

## Task 5: Seed persistent workflow channels and templates

**Files:** create `session_templates/video-lab.json`, `session_templates/publish-queue.json`; modify `app.py`, `session_store.py`, `static/channels.js`, `tests/test_team_up_session.py`; create `tests/test_social_workflow_templates.py`

- [ ] Raise template validation from six to seven phases without loosening role, prompt, or single-output validation.
- [ ] Create seven-phase templates using the exact five `team-up-v2` agent roles/default cast. Add a sixth `approver` role only to `publish-queue`, with `default_cast.approver = "Jonathan"`:
  - `video-lab`: intake/goal, visual teardown, evidence/decomposition, recreation decision, production package, integrate/QC, release.
  - `publish-queue`: import, preflight, creative QC, human approval, execute, reconcile, audit.
- [ ] Give both `default_channel` and `lease_key: "team-up-shared-cast"`. The human approval phase uses participant `approver`; because `Jonathan` is not a registered agent, the existing human-turn path must wait without queue-triggering an agent.
- [ ] Seed `video-lab` and `publish-queue` into loaded settings on every start while preserving user channels and the eight-channel cap. Treat them as protected operational channels in UI rename/delete controls.
- [ ] Test template validation, exact cast, prompts under validator limits, fresh-store reload, settings restart, default channel, and seven-phase advancement.
- [ ] Run `python3 -m pytest tests/test_team_up_session.py tests/test_social_workflow_templates.py -q`. Expected: pass.
- [ ] Commit as `feat(team-up): add social workflow channels`.

## Task 6: Full reliability smoke and operational handoff

**Files:** modify `CONTEXT.md`; test-only changes if failures reveal plan-owned defects

- [ ] Run sequentially:

```bash
python3 -m pytest tests/test_team_up_runtime.py tests/test_team_up_session.py tests/test_agent_activity.py tests/test_archive_feature.py tests/test_social_workflow_templates.py -q
node --test tests/activity-status.test.js
python3 -m pytest -q
```

- [ ] Launch the isolated worktree service, restart all five wrappers once inside the grace window, and verify no `-2` identities appear.
- [ ] Complete a five-nonce canary through actual queue injection and authenticated `chat_send`; verify health reports ready only afterward.
- [ ] Start one harmless fixture session in each channel; verify the second waits for the shared cast and promotes after the first ends. Do not execute media or publishing actions.
- [ ] Verify the private canary channel/nonces are absent from UI, history, archive, summaries, and MCP reads.
- [ ] Update `CONTEXT.md` with commits, commands, smoke evidence, remaining manual provider blockers, and the video-plan handoff.
- [ ] Commit only the context/test changes as `docs(team-up): record social workflow smoke`.

## Handoff gate

The video-lab plan may execute only after all five exact identities are `provider_ready`, the production-path canary passes, and the `video-lab` template can acquire the shared cast. Publishing implementation may proceed in parallel as code, but no `publish-queue` workflow start may bypass this gate.
