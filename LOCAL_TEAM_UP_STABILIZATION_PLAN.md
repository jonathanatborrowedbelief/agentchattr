# Local Team Up Stabilization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:systematic-debugging before changing code or runtime state. Execute this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore the canonical five-provider Team Up runtime to provider-aware readiness and a passed private canary without touching legacy sessions or weakening safety gates.

**Architecture:** Diagnose the existing `agentchattr-team-up-server` plus five provider sessions in place. Repair only the Claude lead failure path, add the smallest tested code fix only if evidence proves a product defect, then verify the existing provider-aware `/healthz` and private nonce canary.

**Tech Stack:** Python, tmux, agentchattr HTTP health endpoint, pytest/unittest, shell.

## Global Constraints

- Worktree: `/Users/jonathan/Documents/agentchattr/.worktrees/codex-local-team-up-stabilize` on `codex/local-team-up-stabilize`.
- The live runtime uses `/Users/jonathan/Documents/agentchattr/.worktrees/team-up-v2`; do not edit that dirty worktree.
- Do not touch Hermes or the VPS.
- Do not stop, rename, or delete legacy, Metricool, Yap, or non-Team-Up tmux sessions.
- Do not restart the Team Up server or the four healthy providers unless evidence makes it unavoidable; stop and report first if so.
- A targeted restart of `agentchattr-claude-lead` is allowed only after preserving its pane tail and proving the session is the failing canonical Claude provider.
- Never print tokens, environment values, OAuth data, private canary payloads, or chat contents.
- Do not weaken provider readiness, authentication, nonce validation, or approval behavior.
- Do not use `--dangerously-bypass-approvals-and-sandbox` in any new launcher.
- Do not commit, push, merge, switch the parent checkout, or clean any worktree.

---

### Task 1: Capture a bounded failure snapshot

**Files:**
- Read: `CONTEXT.md`
- Read: `macos-linux/start_team_up.sh`
- Read: `provider_readiness.py`
- Read: `wrapper_unix.py`
- Read: `app.py`
- Read: `startup_canary.py`
- Create only if needed: `/tmp/agentchattr-stabilize-<timestamp>/` diagnostic receipts

**Interfaces:**
- Consumes: live tmux metadata and `http://127.0.0.1:8300/healthz`.
- Produces: a redacted diagnosis identifying whether Claude is at a trust prompt, login prompt, dead CLI, wrong session, or classifier mismatch.

- [ ] Read the listed source and the latest Team Up notes in `CONTEXT.md`.
- [ ] Record `tmux list-panes -a` metadata and the last 120 lines of only `agentchattr-claude-lead`; redact sensitive content in the report.
- [ ] Record the provider-state subset of `/healthz` with `jq`, omitting canary payload data.
- [ ] Confirm port ownership for `8300`, `8200`, `8201`, and the five provider proxy ports.
- [ ] Confirm the canonical Claude wrapper/server command lines without printing environment values.
- [ ] State the root-cause hypothesis and the exact evidence that would falsify it before mutating anything.

### Task 2: Repair Claude lead with the smallest reversible action

**Files:**
- Modify only if a tested product defect is proven: `provider_readiness.py`, `wrapper_unix.py`, `macos-linux/start_team_up.sh`, and their directly corresponding tests.
- Do not modify live config files, generated provider configs, or the dirty Team Up worktree.

**Interfaces:**
- Consumes: Task 1 diagnosis.
- Produces: a Claude lead provider that reports `provider_ready/ready_prompt`, or a precise blocker requiring Jonathan.

- [ ] If Claude shows a trust/login/permission prompt, use the existing documented recovery flow; do not automate credentials or accept a new security boundary.
- [ ] If the CLI is wedged and no human prompt is present, preserve the pane tail, target only `agentchattr-claude-lead`, and recreate it through the existing canonical launcher/config.
- [ ] If the screen is actually ready but misclassified, write a failing unit test containing only a synthetic redacted screen fixture.
- [ ] Run that narrow test and verify it fails for the expected classifier reason.
- [ ] Implement the minimum classifier/wrapper fix without broadening readiness patterns.
- [ ] Run the narrow test and all directly related provider-readiness/canary tests.
- [ ] If a source fix is required by the live runtime, stop and report the tested patch plus exact safe application step; do not copy it into the dirty runtime worktree.

### Task 3: Verify aggregate readiness and recovery

**Files:**
- Update: `CONTEXT.md` only with the confirmed result/blocker and next action.

**Interfaces:**
- Consumes: five online provider identities.
- Produces: redacted health receipt showing exact provider states and canary disposition.

- [ ] Poll `/healthz` until every exact identity is online and `provider_ready/ready_prompt`, using a bounded timeout.
- [ ] Allow the existing authenticated private canary to run; never echo, log, retry manually, or expose its opaque nonce payload.
- [ ] Require all five exact identities in the canary result and `ready=true`.
- [ ] Confirm no `-2` duplicate identities appeared and no unrelated tmux session changed.
- [ ] Run `git diff --check` and the relevant test suite if code changed.
- [ ] Write a short report with: root cause, runtime action, changed files, commands, tests, final health, blocker if any, and explicit confirmation that no other session was touched.

## Acceptance Gate

Pass only when `/healthz` reports all five exact identities ready and the private five-agent canary passed. If human login/trust approval is required, return `BLOCKED` without bypassing it. If a code patch is needed, the task may return `DONE_WITH_CONCERNS` after tests pass but before applying it to the dirty live worktree.
