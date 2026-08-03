#!/bin/sh
# Start the persistent Team Up runtime without placing credentials in commands or logs.

set -eu
umask 077

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
PROJECT_DIR=${1:-"$HOME/Documents/Codex"}
PROJECT_DIR=$(CDPATH= cd -- "$PROJECT_DIR" && pwd)
VENV_DIR="$REPO_DIR/.venv"
PYTHON="$VENV_DIR/bin/python"
LOG_DIR="$REPO_DIR/logs/team-up"
SERVER_SESSION="agentchattr-team-up-server"
SERVER_WINDOW="server"
SERVER_SESSION_TARGET="=$SERVER_SESSION"
SERVER_WINDOW_TARGET="=$SERVER_SESSION:=$SERVER_WINDOW"

mkdir -p "$LOG_DIR"

# The launcher never consumes a credential value directly. Keep inherited or
# tmux-global Gemini credentials out of the server and non-Gemini wrappers;
# gemini-video receives its selected value later from wrapper.py.
unset GEMINI_API_KEY
tmux set-environment -gu GEMINI_API_KEY >/dev/null 2>&1 || true
if tmux has-session -t "$SERVER_SESSION_TARGET" 2>/dev/null; then
    tmux set-environment -u -t "$SERVER_SESSION_TARGET" GEMINI_API_KEY \
        >/dev/null 2>&1 || true
fi

if [ ! -x "$PYTHON" ]; then
    python3 -m venv "$VENV_DIR"
    "$VENV_DIR/bin/pip" install -r "$REPO_DIR/requirements.txt"
fi

port_is_listening() {
    port=$1
    lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1
}

team_up_health_matches() {
    mode=$1
    "$PYTHON" -c '
import json
import sys
import urllib.request

mode = sys.argv[1]
expected = {
    "claude-lead",
    "gemini-video",
    "codex-sol",
    "codex-terra",
    "codex-luna",
}
try:
    with urllib.request.urlopen("http://127.0.0.1:8300/healthz", timeout=1) as response:
        payload = json.load(response)
    valid = payload.get("service") == "agentchattr-team-up-v2"
    if mode == "agents":
        canary = payload.get("canary", {})
        canary_agents = canary.get("agents", {})
        valid = (
            valid
            and payload.get("ready") is True
            and set(payload.get("agents", [])) == expected
            and canary.get("state") == "passed"
            and canary.get("complete") is True
            and set(canary_agents) == expected
            and all(
                item.get("state") == "passed"
                for item in canary_agents.values()
            )
        )
except Exception:
    valid = False
raise SystemExit(0 if valid else 1)
' "$mode" >/dev/null 2>&1
}

team_up_blocker() {
    "$PYTHON" -c '
import json
import urllib.request

identities = (
    "claude-lead",
    "gemini-video",
    "codex-sol",
    "codex-terra",
    "codex-luna",
)
safe_reasons = {
    "unknown_screen",
    "update_dialog",
    "trust_screen",
    "mcp_startup_failure",
    "tool_approval",
    "provider_offline",
    "awaiting_response",
    "wrong_sender",
    "wrong_channel",
    "nonce_mismatch",
    "replayed_nonce",
    "invalid_response",
    "response_timeout",
    "queue_delivery_failed",
    "provider_unavailable",
}
with urllib.request.urlopen("http://127.0.0.1:8300/healthz", timeout=1) as response:
    payload = json.load(response)
agents = payload.get("agents", {})
for identity in identities:
    item = agents.get(identity, {})
    if not item.get("online") or item.get("provider_state") != "provider_ready":
        reason = item.get("reason_code", "provider_unavailable")
        safe_reason = reason if reason in safe_reasons else "provider_unavailable"
        print(f"{identity}: {safe_reason}")
        raise SystemExit(0)
canary_agents = payload.get("canary", {}).get("agents", {})
for identity in identities:
    item = canary_agents.get(identity, {})
    if item.get("state") != "passed":
        reason = item.get("reason", "provider_unavailable")
        safe_reason = reason if reason in safe_reasons else "provider_unavailable"
        print(f"{identity}: {safe_reason}")
        raise SystemExit(0)
' blocker
}

server_is_ready() {
    port_is_listening 8300 \
        && port_is_listening 8200 \
        && team_up_health_matches server
}

wait_for_server() {
    attempts=20
    while [ "$attempts" -gt 0 ]; do
        if server_is_ready; then
            return 0
        fi
        attempts=$((attempts - 1))
        sleep 1
    done
    return 1
}

wait_for_team() {
    attempts=30
    while [ "$attempts" -gt 0 ]; do
        if team_up_health_matches agents; then
            return 0
        fi
        attempts=$((attempts - 1))
        sleep 1
    done
    return 1
}

tmux_pane_is_live() {
    target=$1
    pane_state=$(
        tmux list-panes -t "$target" -F '#{pane_dead}' 2>/dev/null
    ) || return 1
    [ "$pane_state" = "0" ]
}

tmux_window_exists() {
    target=$1
    tmux list-panes -t "$target" -F '#{pane_id}' >/dev/null 2>&1
}

if ! server_is_ready; then
    if tmux has-session -t "$SERVER_SESSION_TARGET" 2>/dev/null; then
        if tmux_window_exists "$SERVER_WINDOW_TARGET"; then
            tmux kill-window -t "$SERVER_WINDOW_TARGET"
        fi
        tmux new-window -d -t "$SERVER_SESSION_TARGET" \
            -n "$SERVER_WINDOW" -c "$REPO_DIR" \
            "$PYTHON" "$REPO_DIR/run.py"
    else
        tmux new-session -d -s "$SERVER_SESSION" \
            -n "$SERVER_WINDOW" -c "$REPO_DIR" \
            "$PYTHON" "$REPO_DIR/run.py"
    fi
fi

if ! wait_for_server; then
    printf '%s\n' "Server failed to become ready; wrappers were not started." >&2
    exit 1
fi

wrapper_owner_is_live() {
    owner_window=$1
    tmux_pane_is_live "=$SERVER_SESSION:=$owner_window"
}

start_wrapper() {
    identity=$1
    role=$2
    session="agentchattr-$identity"
    owner_window="wrapper-$identity"
    owner_target="=$SERVER_SESSION:=$owner_window"
    log_file="$LOG_DIR/$identity.redacted.log"

    if wrapper_owner_is_live "$owner_window"; then
        printf 'Skipping %s; wrapper owner %s is still running.\n' \
            "$role" "$SERVER_SESSION:$owner_window"
        return
    fi

    if tmux_window_exists "$owner_target"; then
        tmux kill-window -t "$owner_target"
    fi

    if tmux has-session -t "=$session" 2>/dev/null; then
        tmux kill-session -t "=$session"
    fi

    printf '%s\n' "Wrapper started; runtime output is suppressed to protect credentials." >"$log_file"
    if [ "$identity" = "gemini-video" ] \
        && [ -n "${TEAM_UP_GEMINI_MODEL:-}" ] \
        && [ -n "${TEAM_UP_GEMINI_ENV_FILE:-}" ]; then
        tmux new-window -d -t "$SERVER_SESSION_TARGET" -n "$owner_window" \
            -c "$REPO_DIR" "$PYTHON" "$REPO_DIR/wrapper.py" "$identity" \
            --cwd "$PROJECT_DIR" --role "$role" \
            --model "$TEAM_UP_GEMINI_MODEL" \
            --env-file "$TEAM_UP_GEMINI_ENV_FILE"
    elif [ "$identity" = "gemini-video" ] && [ -n "${TEAM_UP_GEMINI_MODEL:-}" ]; then
        tmux new-window -d -t "$SERVER_SESSION_TARGET" -n "$owner_window" \
            -c "$REPO_DIR" "$PYTHON" "$REPO_DIR/wrapper.py" "$identity" \
            --cwd "$PROJECT_DIR" --role "$role" \
            --model "$TEAM_UP_GEMINI_MODEL"
    elif [ "$identity" = "gemini-video" ] && [ -n "${TEAM_UP_GEMINI_ENV_FILE:-}" ]; then
        tmux new-window -d -t "$SERVER_SESSION_TARGET" -n "$owner_window" \
            -c "$REPO_DIR" "$PYTHON" "$REPO_DIR/wrapper.py" "$identity" \
            --cwd "$PROJECT_DIR" --role "$role" \
            --env-file "$TEAM_UP_GEMINI_ENV_FILE"
    else
        tmux new-window -d -t "$SERVER_SESSION_TARGET" -n "$owner_window" \
            -c "$REPO_DIR" "$PYTHON" "$REPO_DIR/wrapper.py" "$identity" \
            --cwd "$PROJECT_DIR" --role "$role"
    fi
}

start_wrapper "claude-lead" "Lead"
start_wrapper "gemini-video" "Video"
start_wrapper "codex-sol" "Integrator"
start_wrapper "codex-terra" "Builder"
start_wrapper "codex-luna" "Scout"

if ! wait_for_team; then
    blocker=$(team_up_blocker 2>/dev/null || true)
    if [ -n "$blocker" ]; then
        printf 'Team Up startup blocked: %s\n' "$blocker" >&2
    else
        printf '%s\n' "Team Up startup canary did not complete; runtime is not ready." >&2
    fi
    exit 1
fi

printf '\nTeam Up: http://127.0.0.1:8300\n'
printf '%s\n' "Lead:       agentchattr-claude-lead    tmux attach -t =agentchattr-claude-lead"
printf '%s\n' "Video:      agentchattr-gemini-video  tmux attach -t =agentchattr-gemini-video"
printf '%s\n' "Integrator: agentchattr-codex-sol     tmux attach -t =agentchattr-codex-sol"
printf '%s\n' "Builder:    agentchattr-codex-terra   tmux attach -t =agentchattr-codex-terra"
printf '%s\n' "Scout:      agentchattr-codex-luna    tmux attach -t =agentchattr-codex-luna"
