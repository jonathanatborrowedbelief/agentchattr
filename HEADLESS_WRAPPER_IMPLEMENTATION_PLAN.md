# Explicit Headless Wrapper Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development and superpowers:systematic-debugging. Execute this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an explicit, tested non-attaching Unix wrapper mode suitable for later systemd supervision while preserving current interactive Mac behavior.

**Architecture:** Thread one `headless: bool` from the `wrapper.py` CLI into `wrapper_unix.run_agent()`. Interactive mode keeps the existing tmux attach flow; headless mode skips terminal attachment and supervises the child tmux session through the existing condition loop. This slice does not create VPS services or modify the live runtime.

**Tech Stack:** Python 3, argparse, tmux, unittest/mock.

## Global Constraints

- Worktree: `/Users/jonathan/Documents/agentchattr/.worktrees/codex-local-team-up-stabilize` on `codex/local-team-up-stabilize`.
- The live runtime is healthy. Do not restart, message, attach to, inject into, or modify any live Team Up or other tmux session.
- Ownership: `wrapper.py`, `wrapper_unix.py`, a new focused root test file `test_wrapper_unix_headless.py`, `CONTEXT.md`, and this plan only.
- Do not touch `wrapper_windows.py`, provider readiness/canary logic, authentication, config files, launch scripts, Hermes, or the VPS.
- Default behavior must remain interactive for existing Mac launchers.
- Headless mode must not weaken queue-delivery readiness gates or restart behavior.
- Use a unique temporary tmux socket or `TMUX_TMPDIR` for any integration smoke; never use the default live tmux server.
- Do not commit, push, merge, switch, stage, or clean.

---

### Task 1: Specify headless supervision behavior

**Files:**
- Create: `test_wrapper_unix_headless.py`
- Read: `wrapper.py`
- Read: `wrapper_unix.py`

**Interfaces:**
- New CLI flag: `python wrapper.py <identity> --headless`.
- New parameter: `wrapper_unix.run_agent(..., headless: bool = False)`.

- [ ] Before writing tests, name the production break each test catches.
- [ ] Add a test proving `headless=True` creates the child tmux session, never calls `tmux attach-session`, supervises until the mocked session disappears, and returns when `no_restart=True`.
- [ ] Add a test proving the default/`headless=False` path still invokes `tmux attach-session` exactly once.
- [ ] Add a test proving `wrapper.py` parses `--headless` and passes `headless=True` only on Unix; Windows behavior remains unchanged.
- [ ] Run the focused test and verify it fails for the missing interface/behavior, not due to fixture errors.

### Task 2: Implement the minimum explicit mode

**Files:**
- Modify: `wrapper.py`
- Modify: `wrapper_unix.py`
- Test: `test_wrapper_unix_headless.py`

**Interfaces:**
- Consumes: `args.headless` from the wrapper CLI.
- Produces: an explicit non-attaching supervision path with all existing watcher/readiness semantics intact.

- [ ] Add `--headless` as a false-by-default CLI flag with help text stating that it supervises tmux without attaching a terminal.
- [ ] Pass `headless` only to the Unix `run_agent` implementation.
- [ ] Add `headless: bool = False` to `wrapper_unix.run_agent`.
- [ ] In headless mode, skip only the `attach-session` call and interactive detach messaging; enter the existing `_session_exists` supervision loop immediately.
- [ ] Preserve child exit detection, `no_restart`, three-second restart behavior, readiness monitor lifecycle, queue watcher lifecycle, and KeyboardInterrupt cleanup.
- [ ] Run the focused tests and the existing provider-readiness/runtime tests available in this worktree.

### Task 3: Prove non-interactive tmux operation

**Files:**
- Update: `CONTEXT.md`
- Create receipts only under a unique `/tmp/agentchattr-headless-smoke-*` directory.

**Interfaces:**
- Consumes: a disposable tmux socket/runtime path and a short-lived local shell command.
- Produces: a redacted receipt proving the wrapper starts, supervises, and exits without a TTY attachment.

- [ ] Use `mktemp -d` and an isolated `TMUX_TMPDIR` or `tmux -S` boundary that cannot see live sessions.
- [ ] Run a bounded headless smoke around a harmless short-lived command; do not connect it to agentchattr or a provider account.
- [ ] Verify there is no `open terminal failed`, no attach attempt, no orphan tmux server/session, and the wrapper exits according to `no_restart=True`.
- [ ] Run focused tests, `python -m compileall` on changed Python files, and `git diff --check`.
- [ ] Update `CONTEXT.md` with implementation result, exact tests, remaining systemd work, and confirmation that the live runtime was untouched.

## Acceptance Gate

Pass only when automated tests prove both paths, the isolated no-TTY smoke exits cleanly without an orphan, and the already-running Team Up health remains unchanged. Systemd unit creation and VPS installation are separate later tasks.
