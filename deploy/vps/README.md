# Isolated VPS pilot scaffold

This directory is a reviewable, secret-free scaffold. It does not install,
enable, start, stop, or modify anything on a VPS. Actual deployment, service
activation, backup automation, and restore testing remain separately approved
gates.

## Fixed isolation contract

- Code: `/opt/agentchattr/current`
- Configuration: `/etc/agentchattr/config.toml`
- Credential files: `/etc/agentchattr/secrets/`
- State and provider homes: `/var/lib/agentchattr`
- Backups: `/var/backups/agentchattr`
- Service account: `agentchattr:agentchattr`
- Listeners: loopback-only ports `8300`, `8200`, and `8201`

The server and workers bind-mount the VPS configuration over the repository
`config.toml`. Every worker has a separate systemd runtime directory,
`TMUX_TMPDIR`, HOME, worktree, and stable identity. The wrapper uses
`--headless --no-restart`; systemd is the only restart supervisor. Provider
approval behavior remains at each CLI's normal default.

Gemini is intentionally frozen to the proven pilot fallback
`gemini-3.1-flash-lite`. Its credential source is the root-provisioned
`/etc/agentchattr/secrets/gemini-video.env`, created with mode `0600` and made
readable only to the `agentchattr` service account. Populate it out of band;
never place its value in this repository, a unit, a command line, or a journal.

## Preflight gates

Before copying or starting anything, confirm the proposed host still has:

- exactly 2 CPUs available to the pilot;
- approximately 7.8 GiB total memory;
- no swap configured; and
- at least 2 GiB available memory reserved after every activation step.

Review `nproc`, `free -h`, and `swapon --show`. Stop adding providers whenever
available memory would fall below 2 GiB. Check Hermes health and its resource
reserve after every step; this pilot must not share or alter any Hermes user,
volume, token, container, network, service, timer, or backup path.

Before activation, provision the dedicated account and the fixed directories,
place a reviewed release at `/opt/agentchattr/current`, create one clean role
worktree under `/var/lib/agentchattr/worktrees/` for each exact identity, install
each provider CLI at the absolute path in the TOML, and authenticate each role
under its own HOME. Copy the reviewed TOML to
`/etc/agentchattr/config.toml`. Validate ownership and modes before continuing.

## Staged activation

Do not start the aggregate target during the pilot. Activate one unit at a time
in this order, checking service status, logs, provider authentication, Hermes
health, available memory, and localhost readiness after each:

1. `agentchattr-server.service`
2. `agentchattr-worker@claude-lead.service`
3. `agentchattr-worker@codex-sol.service`
4. `agentchattr-worker@gemini-video.service`
5. `agentchattr-worker@codex-terra.service`
6. `agentchattr-worker@codex-luna.service`

Use `systemctl status` and `journalctl -u` for the exact unit being evaluated.
The server gate is:

```sh
/opt/agentchattr/current/.venv/bin/python \
  /opt/agentchattr/current/deploy/vps/wait_ready.py \
  --url http://127.0.0.1:8300/healthz --mode server --timeout-seconds 60
```

After all five providers are online, run team mode once. It reads sanitized
`/healthz` state and allows the server-owned private canary to proceed; it does
not send messages or manually trigger or retry a canary. Only after that passes
may the aggregate target and minute health timer be considered for activation.

## Private access and operations

Keep all listeners on loopback. Access the UI through an SSH tunnel such as:

```sh
ssh -N -L 8300:127.0.0.1:8300 pilot.example.invalid
```

Then verify through `http://127.0.0.1:8300` on the operator machine. Do not add
a public bind, reverse proxy, firewall exception, or shared container network
for this pilot.

Stopping a worker invokes both `KillMode=control-group` and an explicit tmux
kill scoped by that identity's `TMUX_TMPDIR`. Inspect the unit journal after a
stop and confirm its isolated runtime directory has no remaining session.

For rollback, stop the health timer, stop workers in reverse activation order,
then stop the server. Re-point `/opt/agentchattr/current` and restore the prior
reviewed configuration/state snapshot using the host's approved release and
backup procedures. Do not delete the service account, state tree, worktrees, or
backups during pilot rollback.

Automated backup/restore, retention, production monitoring, unit installation,
and any VPS execution are intentionally deferred.
