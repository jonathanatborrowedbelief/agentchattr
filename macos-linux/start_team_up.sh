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

if [ ! -x "$PYTHON" ]; then
    python3 -m venv "$VENV_DIR"
    "$VENV_DIR/bin/pip" install -r "$REPO_DIR/requirements.txt"
fi

port_is_listening() {
    lsof -nP -iTCP:8300 -sTCP:LISTEN >/dev/null 2>&1
}

wait_for_server() {
    attempts=20
    while [ "$attempts" -gt 0 ]; do
        if port_is_listening; then
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

if ! port_is_listening; then
    if ! tmux_pane_is_live "$SERVER_WINDOW_TARGET"; then
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
    if [ "$identity" = "gemini-video" ] && [ -n "${TEAM_UP_GEMINI_MODEL:-}" ]; then
        tmux new-window -d -t "$SERVER_SESSION_TARGET" -n "$owner_window" \
            -c "$REPO_DIR" "$PYTHON" "$REPO_DIR/wrapper.py" "$identity" \
            --cwd "$PROJECT_DIR" --role "$role" \
            --model "$TEAM_UP_GEMINI_MODEL"
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

printf '\nTeam Up: http://127.0.0.1:8300\n'
printf '%s\n' "Lead:       agentchattr-claude-lead    tmux attach -t =agentchattr-claude-lead"
printf '%s\n' "Video:      agentchattr-gemini-video  tmux attach -t =agentchattr-gemini-video"
printf '%s\n' "Integrator: agentchattr-codex-sol     tmux attach -t =agentchattr-codex-sol"
printf '%s\n' "Builder:    agentchattr-codex-terra   tmux attach -t =agentchattr-codex-terra"
printf '%s\n' "Scout:      agentchattr-codex-luna    tmux attach -t =agentchattr-codex-luna"
