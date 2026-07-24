# agentchattr setup from the video transcript

This repo already ships most of the workflow the transcript describes. The missing pieces are the local setup steps and the planning templates the video expects you to keep alongside the app.

## Step-by-step

1. Install the terminal multiplexer on macOS or Linux.
   - macOS: `brew install tmux`
   - Ubuntu / Debian: `apt install tmux`
2. Clone this repo and open it locally.
3. Start the app from the platform launcher.
   - Windows: open `windows/` and run the launcher you want.
   - macOS / Linux: open `macos-linux/` and run `sh start.sh` or one of the agent launchers.
4. Run each agent in its own terminal.
   - The transcript recommends one terminal per agent, even when one human is orchestrating all of them.
5. Configure each CLI’s permissions before you let the agents work.
   - Keep normal approval flow for safety.
   - Only use the skip/bypass launchers if you intentionally want auto-approval.
6. Make sure MCP is configured for the agent CLIs that need it.
   - This repo already injects MCP settings for the built-in launchers.
   - Use `config.local.toml` for any local API-based agents you want to add.
7. Create the planning files the transcript calls out.
   - `agents.mmd`
   - `Claude.md`
   - `Codex.md`
   - `Gemini.md`
   - `PRD.md`
   - `backend.md`
   - `ui-spec.md`
   - the matching template files in `templates/`
8. Start with planning before implementation.
   - Put the idea in a planning session.
   - Let the planner frame the work.
   - Let the challenger stress-test it.
   - Let the synthesiser produce the final plan.
9. Create channels for the workstreams.
   - Use at least one frontend channel and one backend channel for complex work.
10. Approve the plan before implementation starts.
    - The transcript’s workflow is deliberate: plan first, implement second, review again before build-out.
11. Keep the loop guard in mind.
    - When the channel pauses, use `/continue` to resume.
12. Prefer separate worktrees for larger multi-agent changes.
    - The transcript specifically calls out worktrees as the cleaner way to avoid agents overwriting one another.

## What this repo already gives you

- `macos-linux/start_*.sh` and `windows/start_*.bat` launchers for the supported agents.
- `config.toml` with the default server, routing, MCP, and agent settings.
- `config.local.toml.example` for local API agents.
- `session_templates/planning.json` for the plan / challenge / synthesize flow.
- `session_templates/code-review.json`, `session_templates/design-critique.json`, and `session_templates/debate.json` for other multi-agent workflows.
- `Claude.md`, `Codex.md`, and `Gemini.md` for model-specific behavior.
- `PRD.md`, `backend.md`, and `ui-spec.md` for the live planning docs.

## Recommended operating order

1. Start the server.
2. Bring up the agents you want to use.
3. Open `http://localhost:8300`.
4. Create or choose the planning session.
5. Fill in `agents.mmd`, the per-model files, and the planning docs.
6. Review the plan.
7. Implement.
8. Review again.
