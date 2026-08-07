# VPS Sidecar Preflight — 2026-08-07

**Mode:** Read-only. No package, user, file, service, timer, firewall, container, or authentication state was changed.

## Result

Hermes is healthy and the VPS can host an agentchattr pilot, but it is not ready for a five-provider cutover yet. The host lacks Node and all three provider CLIs, has no `agentchattr` account, and has only two CPUs with no swap. Deployment must bring providers online one at a time and measure actual memory/CPU before enabling the next role.

## Confirmed facts

| Check | Result |
|---|---|
| Hermes health | All checks green: container, Telegram gateway, build script, backup freshness, SSH hardening, fail2ban, firewall, dashboard local health |
| OS | Ubuntu 24.04.4 LTS, x86_64, kernel 6.8 |
| Capacity | 2 CPUs; 7.8 GiB RAM; 6.8 GiB available during preflight; no swap |
| Disk | 96 GiB root volume; 46 GiB available; 53% used |
| Load/uptime | 50 days uptime; load average 0.00/0.00/0.00 |
| Installed base | Python 3.12.3, tmux 3.4, Git 2.43.0 |
| Missing | `rg`, `node`, `npm`, `claude`, `codex`, `gemini`, `unzip` |
| Available helpers | `curl`, `jq`, `lsof`, `tar`, `sha256sum`, `systemd-run`, `loginctl`, Python `venv` |
| Ubuntu Node candidate | Node 18.19.1 / npm 9.2.0; below the chosen Node 22 toolchain, so do not install the distro Node package |
| agentchattr account | Absent |
| Candidate ports | `8200`, `8201`, and `8300` free |
| Existing host ports | SSH `22`; Hermes Docker proxy `32772`; resolver/monitoring loopback ports |
| Hermes exposure | Docker proxy binds `32772` on all interfaces; `DOCKER-USER` firewall drops the container port publicly; health check confirms tunnel-only use |
| Media pipeline | `media-pipeline.timer` exists and continues its approximately 90-second polling cadence |
| OOM evidence | No kernel OOM-kill record found in the last 30 days |
| Backup | Current Hermes backup reported fresh by `hermes-check.sh` |

## Deployment implications

1. Do not copy the Mac launchers directly. Implement/test explicit headless wrapper behavior first.
2. Create a locked `agentchattr` Unix account and isolated directories only during the deployment slice.
3. Install a pinned Node 22 runtime and pinned Claude/Codex/Gemini CLI versions under the agentchattr boundary; do not use Ubuntu's Node 18 candidate or reuse Hermes' container/tokens. Initial version-parity candidates from the working Mac are Node 22.22.3, npm 10.9.8, Claude Code 2.1.224, Codex CLI 0.146.0, and Gemini CLI 0.53.1.
4. Establish provider authentication separately for the new user without printing or backing up tokens in plaintext.
5. Start server-only, then Claude lead, then one Codex role, then Gemini, then remaining Codex roles.
6. After each provider starts, record service RSS, child-process RSS, CPU, open files, heartbeat, and Hermes health.
7. Initial systemd limits in the design are provisional. With 7.8 GiB RAM and no swap, five workers cannot each receive a realistic independent 2 GiB hard allocation.
8. Keep all agentchattr listeners on `127.0.0.1`; do not rely on the Hermes firewall exception used by Docker port `32772`.
9. Preserve at least 2 GiB of available memory for Hermes, the media timer, SSH, and the OS during the pilot. Stop adding providers if the reserve is crossed or any OOM/restart signal appears.
10. Do not modify the existing `media-pipeline.timer`, Hermes firewall rules, container, backup, or dashboard binding.

## Read-only evidence commands

```bash
ssh -o BatchMode=yes -o ConnectTimeout=10 hermes hermes-check.sh

ssh hermes '
  uname -a
  cat /etc/os-release
  nproc
  free -h
  df -h / /opt /var
  uptime
'

ssh hermes '
  command -v python3 tmux git rg claude codex gemini node npm
  python3 --version
  tmux -V
  git --version
  ss -lntup
'

ssh hermes '
  systemctl list-units --type=service --all --no-pager
  systemctl list-timers --all --no-pager
  docker ps --format "{{.Names}}|{{.Ports}}|{{.Status}}"
  getent passwd agentchattr
'

ssh hermes '
  systemctl show hermes-firewall.service \
    -p ActiveState -p SubState -p FragmentPath -p User -p Group -p ExecStart
  iptables -S INPUT
  iptables -S DOCKER-USER
  journalctl -k --since "30 days ago" --no-pager
'
```

## Gate before the first VPS write

- Local Team Up has all five exact providers ready and its private canary passed.
- Headless wrapper mode has focused tests and a local restart-recovery smoke.
- Exact deploy SHA and dependency locks exist.
- CLI install versions and per-provider authentication procedure are documented.
- Jonathan approves the first VPS write slice: create the isolated account/directories and install the pinned runtime, with Hermes health checks before and after.
