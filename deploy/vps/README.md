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
- Node: `/opt/agentchattr/toolchain/node/bin/node`
- Provider commands: `/opt/agentchattr/toolchain/npm/node_modules/.bin/`

The server and workers bind-mount the VPS configuration over the repository
`config.toml`. Every worker has a separate systemd runtime directory,
`TMUX_TMPDIR`, HOME, worktree, and stable identity. The wrapper uses
`--headless --no-restart`; systemd is the only restart supervisor. Provider
approval behavior remains at each CLI's normal default.

Gemini is intentionally frozen to the proven pilot fallback
`gemini-3.1-flash-lite`. Its credential source is the root-provisioned
`/etc/agentchattr/secrets/gemini-video.env`. The secret directory is
`root:agentchattr 0750`; each secret file is `agentchattr:agentchattr 0600`.
Populate it out of band;
never place its value in this repository, a unit, a command line, or a journal.

## Pinned isolated install

The reviewed release carries the exact Python environment in
`requirements.vps.lock`, the Node/npm archive and provider integrity metadata in
`toolchain.vps.lock.toml`, and a fully resolved npm dependency graph in
`npm-toolchain/package-lock.json`. Install nothing under `/usr/local/bin`, and
do not use the host's Node, npm, or provider CLIs.

`build_release.py must not be used for VPS`: deploy a full `git archive` of the
reviewed commit so every lockfile, unit, and deploy input remains present.

After the dedicated account, release, and `/opt/agentchattr/toolchain` directory
exist, fetch the Node archive URL recorded in `toolchain.vps.lock.toml`, verify
its recorded SHA-256, and extract it as root without preserving an
archive-created parent directory:

```sh
cd /tmp
curl -fLO https://nodejs.org/dist/v22.22.3/node-v22.22.3-linux-x64.tar.xz
printf '%s  %s\n' \
  '2e5d13569282d016861fae7c8f935e741693c269101a5bebcf761a5376d1f99f' \
  node-v22.22.3-linux-x64.tar.xz | sha256sum -c -
sudo install -d -o root -g root -m 0755 /opt/agentchattr/toolchain/node
sudo tar -xJf node-v22.22.3-linux-x64.tar.xz --strip-components=1 \
  -C /opt/agentchattr/toolchain/node
```

Stage the release, virtual environment, and toolchain as root. Only state,
provider homes, and worktrees under `/var/lib/agentchattr` are service-owned;
the release and both `/opt/agentchattr/toolchain/{node,npm}` trees must remain
`root:root` and non-writable by the service account. Create the isolated Python
environment from the exact local pins, then stage the lock-respecting npm
project at its deployment prefix. The npm command is
deliberately `npm ci --omit=dev --ignore-scripts`: it uses the committed
package lock and never runs package lifecycle scripts during installation.

```sh
sudo /opt/agentchattr/current/.venv/bin/pip install \
  -r /opt/agentchattr/current/deploy/vps/requirements.vps.lock
sudo install -d -o root -g root -m 0755 /opt/agentchattr/toolchain/npm
sudo install -o root -g root -m 0644 \
  /opt/agentchattr/current/deploy/vps/npm-toolchain/package.json \
  /opt/agentchattr/current/deploy/vps/npm-toolchain/package-lock.json \
  /opt/agentchattr/toolchain/npm/
sudo env PATH=/opt/agentchattr/toolchain/node/bin:/usr/bin:/bin \
  /opt/agentchattr/toolchain/node/bin/npm ci --prefix /opt/agentchattr/toolchain/npm --omit=dev --ignore-scripts
sudo chown -R root:root /opt/agentchattr/current /opt/agentchattr/toolchain
sudo chmod -R go-w /opt/agentchattr/current /opt/agentchattr/toolchain
```

Version-only Python pins are an outstanding blocker for `--require-hashes`.
Do not claim the first VPS write is ready until every Python requirement has
artifact hashes and the install command is updated to enforce them.

Before `npm ci`, compare each provider's registry `dist.integrity` with the
corresponding value in `toolchain.vps.lock.toml`; the committed
`package-lock.json` also pins all npm transitives. Provider commands are
absolute, deterministic deployment paths under
`/opt/agentchattr/toolchain/npm/node_modules/.bin`, and worker PATH contains
only that directory, the pinned Node bin, `/usr/bin`, and `/bin`.

## Per-role authentication and status

Provider login is a human gate. It must be completed interactively for the
dedicated role HOME before enabling that role's systemd worker; never automate
browser consent, paste credentials into a command, or record login output.
Hermes credential reuse is forbidden: do not copy, mount, source, or reuse any
Hermes token, OAuth state, environment file, CLI home, or container volume.

For Claude lead, run the exact isolated command as the service account, then
check its status:

```sh
sudo -u agentchattr env HOME=/var/lib/agentchattr/home/claude-lead \
  PATH=/opt/agentchattr/toolchain/npm/node_modules/.bin:/opt/agentchattr/toolchain/node/bin:/usr/bin:/bin \
  /opt/agentchattr/toolchain/npm/node_modules/.bin/claude auth login
sudo -u agentchattr env HOME=/var/lib/agentchattr/home/claude-lead \
  PATH=/opt/agentchattr/toolchain/npm/node_modules/.bin:/opt/agentchattr/toolchain/node/bin:/usr/bin:/bin \
  /opt/agentchattr/toolchain/npm/node_modules/.bin/claude auth status
```

For each Codex role (`codex-sol`, `codex-terra`, then `codex-luna`), substitute
the role in HOME and complete the same human-gated login/status procedure:

```sh
sudo -u agentchattr env HOME=/var/lib/agentchattr/home/codex-sol \
  PATH=/opt/agentchattr/toolchain/npm/node_modules/.bin:/opt/agentchattr/toolchain/node/bin:/usr/bin:/bin \
  /opt/agentchattr/toolchain/npm/node_modules/.bin/codex login
sudo -u agentchattr env HOME=/var/lib/agentchattr/home/codex-sol \
  PATH=/opt/agentchattr/toolchain/npm/node_modules/.bin:/opt/agentchattr/toolchain/node/bin:/usr/bin:/bin \
  /opt/agentchattr/toolchain/npm/node_modules/.bin/codex login status
```

Gemini's role credential is instead provisioned by a human into the dedicated
`0600` `/etc/agentchattr/secrets/gemini-video.env` file. Do not reuse Hermes or
another role's credential. Confirm the isolated executable before starting the
Gemini worker:

```sh
sudo -u agentchattr env HOME=/var/lib/agentchattr/home/gemini-video \
  PATH=/opt/agentchattr/toolchain/npm/node_modules/.bin:/opt/agentchattr/toolchain/node/bin:/usr/bin:/bin \
  /opt/agentchattr/toolchain/npm/node_modules/.bin/gemini --version
```

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
the pinned provider CLI set under `/opt/agentchattr/toolchain/npm`, and
authenticate each role under its own HOME through the human gate above. Copy the reviewed TOML to
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

The aggregate target and health timer intentionally have no `[Install]` section
and must remain disabled during this pilot. Start only the reviewed server and
one worker units explicitly in the staged order above; do not enable the target
or timer as a convenience shortcut.

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
