# VPS Service Scaffold Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development. Execute this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create tested, secret-free systemd and configuration templates for an isolated agentchattr VPS pilot without changing the VPS or Hermes.

**Architecture:** The agentchattr server runs directly under systemd. Five instance workers use the new `--headless --no-restart` wrapper mode, one runtime/tmux boundary per identity, and systemd as the sole restart supervisor. A small Python readiness command supports server ordering and provider-aware health without exposing payloads.

**Tech Stack:** systemd unit files, Python 3.12+, TOML, unittest, agentchattr `/healthz`.

## Global Constraints

- Worktree: `/Users/jonathan/Documents/agentchattr/.worktrees/codex-local-team-up-stabilize` on `codex/local-team-up-stabilize`.
- Do not SSH, copy files to, install on, or mutate the VPS. Do not touch Hermes.
- Do not touch the healthy live Team Up runtime.
- Ownership: `deploy/vps/**`, `test_vps_service_scaffold.py`, `CONTEXT.md`, and this plan only.
- Templates contain no token, password, OAuth data, private canary content, or real secret value.
- agentchattr binds only `127.0.0.1:8300`, `127.0.0.1:8200`, and `127.0.0.1:8201`.
- Paths are fixed: code `/opt/agentchattr/current`; config `/etc/agentchattr`; state `/var/lib/agentchattr`; backups `/var/backups/agentchattr`.
- Dedicated user/group is `agentchattr`; no Hermes user, volume, token, Docker network, service, timer, or backup path is referenced.
- Workers use normal provider approval behavior. No auto-approve, permission bypass, YOLO, or dangerous sandbox flag.
- Systemd workers use `--headless --no-restart`; systemd owns restart policy.
- Every worker gets its own `RuntimeDirectory`/`TMUX_TMPDIR` and absolute role worktree/CLI home.
- Do not commit, push, merge, stage, switch, or clean.

---

### Task 1: Build the bounded readiness command

**Files:**
- Create: `deploy/vps/wait_ready.py`
- Create: `test_vps_service_scaffold.py`

**Interfaces:**
- CLI: `python wait_ready.py --url http://127.0.0.1:8300/healthz --mode server|team --timeout-seconds N`.
- Exit `0`: selected contract is ready; exit nonzero: timeout, malformed response, wrong service, missing/extra identity, non-ready provider, or failed/incomplete canary.

- [ ] Write tests first for server-ready, exact-five team-ready, extra identity, missing identity, provider-not-ready, canary incomplete/failed, malformed JSON, HTTP error, and bounded timeout.
- [ ] Verify RED failures name missing behavior rather than fixture errors.
- [ ] Implement with Python standard library only; never log response bodies or canary data.
- [ ] Require service name `agentchattr-team-up-v2` and the exact identities `claude-lead`, `gemini-video`, `codex-sol`, `codex-terra`, `codex-luna` in team mode.
- [ ] Use condition polling with a bounded deadline; no fixed uninterruptible sleep longer than one second.
- [ ] Run focused tests to GREEN.

### Task 2: Add isolated server and worker units

**Files:**
- Create: `deploy/vps/systemd/agentchattr-server.service`
- Create: `deploy/vps/systemd/agentchattr-worker@.service`
- Create: `deploy/vps/systemd/agentchattr-team-up.target`
- Create: `deploy/vps/systemd/agentchattr-health.service`
- Create: `deploy/vps/systemd/agentchattr-health.timer`
- Test: `test_vps_service_scaffold.py`

**Interfaces:**
- Server starts `/opt/agentchattr/current/.venv/bin/python /opt/agentchattr/current/run.py`.
- Worker instance starts `/opt/agentchattr/current/.venv/bin/python /opt/agentchattr/current/wrapper.py %i --headless --no-restart`.
- Health check calls `wait_ready.py` in team mode.

- [ ] Add failing behavioral/contract tests that parse unit sections and assert exact executable, user/group, loopback ordering, writable paths, runtime isolation, restart ownership, stop cleanup, hardening, and identity target list.
- [ ] Server: `User=agentchattr`, `Group=agentchattr`, `UMask=0077`, `Restart=on-failure`, `NoNewPrivileges=true`, `PrivateTmp=true`, `ProtectSystem=strict`, no capabilities, and only `/var/lib/agentchattr` writable.
- [ ] Worker: require/after server; run readiness preflight in server mode; set role-specific `HOME=/var/lib/agentchattr/home/%i`, `RuntimeDirectory=agentchattr-%i`, and `TMUX_TMPDIR=/run/agentchattr-%i`.
- [ ] Worker: `Restart=always`, `RestartSec=5`, `KillMode=control-group`, bounded stop timeout, and an `ExecStop` tmux kill using the instance's isolated runtime.
- [ ] Team target enumerates exactly five worker instances but is not enabled by any install script; pilot activation remains one identity at a time.
- [ ] Health timer runs provider-aware team mode every minute and does not send messages or manually trigger/retry a canary.
- [ ] Include conservative generic hardening that does not block required outbound provider/API network access or Node JIT.
- [ ] Run focused tests to GREEN.

### Task 3: Add a secret-free VPS configuration template

**Files:**
- Create: `deploy/vps/config.vps.toml.example`
- Create: `deploy/vps/README.md`
- Test: `test_vps_service_scaffold.py`

**Interfaces:**
- Config server/data/uploads paths point only to the isolated VPS contract.
- Provider identities point to `/var/lib/agentchattr/worktrees/<identity>` and dedicated CLI homes supplied by systemd.

- [ ] Add failing tests for loopback binding, exact ports, absolute per-role worktrees, isolated state/upload paths, exact five identities, no generic duplicate agents, no auto-approval/bypass flags, and no secret literals.
- [ ] Use the proven local role/model lineup; freeze Gemini to the currently proven live override `gemini-3.1-flash-lite` and document that choice.
- [ ] Point Gemini's credential source to a root-provisioned `0600` file under `/etc/agentchattr/secrets/` without including a value.
- [ ] Document staged activation: server, Claude lead, Codex Sol, Gemini video, Codex Terra, Codex Luna; check Hermes health and resource reserve after each.
- [ ] Document the no-swap/2-CPU/7.8-GiB preflight and stop adding providers below the 2-GiB available-memory reserve.
- [ ] Document SSH tunneling, localhost-only verification, per-role authentication, log inspection, stop behavior, and rollback without including destructive retirement commands.
- [ ] State that backup/restore automation and actual installation remain later gated slices.

### Task 4: Validate the complete scaffold

**Files:**
- Update: `CONTEXT.md`

**Interfaces:**
- Produces: locally reviewable, secret-free deploy inputs; performs no installation.

- [ ] Run all scaffold tests, relevant headless-wrapper tests, Python compile checks, TOML parse checks, and `git diff --check`.
- [ ] Scan `deploy/vps` for private paths, known secret-key patterns, dangerous flags, non-loopback binds, Hermes service/container names, and unresolved placeholders.
- [ ] Confirm a unit stop has both cgroup cleanup and an explicit isolated tmux-session cleanup contract.
- [ ] Update `CONTEXT.md` with validation evidence and remaining live-deployment gates.

## Acceptance Gate

Pass only when tests prove the scaffold is loopback-only, secret-free, independently owned, systemd-supervised, exact-five-role, and unable to collide through shared tmux runtime paths. No VPS readiness claim is permitted from local scaffold validation alone.
