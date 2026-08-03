# Task 2 Report: Provider readiness

## Status

Complete. Provider readiness is a distinct authenticated state from heartbeat
presence. Unix wrappers classify only local tmux pane text and send allowlisted
state/reason pairs; queue delivery begins only after `provider_ready`.

## Changed files

- `provider_readiness.py` — fail-closed classifier and state/reason allowlist.
- `registry.py` — readiness fields and token-bound state reports.
- `app.py` — loopback provider-state endpoint and sanitized Team Up health.
- `wrapper.py` / `wrapper_unix.py` — authenticated state reporting and readiness-gated queue watcher.
- `tests/test_team_up_runtime.py` / `tests/test_agent_activity.py` — classifier, auth, heartbeat independence, health, queue-gating, and no-echo coverage.

## Commit

`feat(team-up): report provider readiness`

## Validation

```text
$ python3 -m pytest tests/test_team_up_runtime.py tests/test_agent_activity.py -q
................................................................ [ 95%]
...                                                                      [100%]
68 passed, 7 subtests passed in 13.72s
```

`git diff --check` passed.

## Self-review

- Unknown panes resolve to `registered` / `unknown_screen`; pane text never leaves the wrapper process.
- The endpoint is loopback-gated, token-authenticated, rejects sender/token mismatches, and validates state/reason pairs.
- Heartbeats update only presence/activity; they do not change provider readiness.
- Health emits fixed `online`, `provider_state`, and `reason_code` fields for the permanent identities; any non-ready identity makes aggregate readiness false.
- `.pids/` was left unmodified and unstaged.

## Concerns

None. Existing archive test failures remain outside this task and were not run as part of the focused suite.
