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
PID_DIR="$REPO_DIR/.pids"

mkdir -p "$LOG_DIR" "$PID_DIR"

if [ ! -x "$PYTHON" ]; then
    python3 -m venv "$VENV_DIR"
    "$VENV_DIR/bin/pip" install -r "$REPO_DIR/requirements.txt"
fi

port_is_listening() {
    lsof -nP -iTCP:8300 -sTCP:LISTEN >/dev/null 2>&1
}

if ! port_is_listening; then
    nohup "$PYTHON" "$REPO_DIR/run.py" >"$LOG_DIR/server.redacted.log" 2>&1 &
    printf '%s\n' "$!" >"$PID_DIR/server.pid"
fi

start_wrapper() {
    identity=$1
    role=$2
    session="agentchattr-$identity"
    pid_file="$PID_DIR/$identity.pid"
    log_file="$LOG_DIR/$identity.redacted.log"

    if tmux has-session -t "$session" 2>/dev/null; then
        printf 'Skipping %s; tmux session %s already exists.\n' "$role" "$session"
        return
    fi

    printf '%s\n' "Wrapper started; runtime output is suppressed to protect credentials." >"$log_file"
    nohup "$PYTHON" "$REPO_DIR/wrapper.py" "$identity" \
        --cwd "$PROJECT_DIR" --role "$role" >/dev/null 2>&1 &
    printf '%s\n' "$!" >"$pid_file"
}

start_wrapper "claude-lead" "Lead"
start_wrapper "gemini-video" "Video"
start_wrapper "codex-sol" "Integrator"
start_wrapper "codex-terra" "Builder"
start_wrapper "codex-luna" "Scout"

printf '\nTeam Up: http://127.0.0.1:8300\n'
printf '%s\n' "Lead:       agentchattr-claude-lead    tmux attach -t agentchattr-claude-lead"
printf '%s\n' "Video:      agentchattr-gemini-video  tmux attach -t agentchattr-gemini-video"
printf '%s\n' "Integrator: agentchattr-codex-sol     tmux attach -t agentchattr-codex-sol"
printf '%s\n' "Builder:    agentchattr-codex-terra   tmux attach -t agentchattr-codex-terra"
printf '%s\n' "Scout:      agentchattr-codex-luna    tmux attach -t agentchattr-codex-luna"
