# Codex

Use this file for Codex-specific instructions. Read `agents.mmd` first and treat it as the shared coordination contract.

## Role

- Own implementation.
- Luna performs bounded read-only scouting, Terra builds the assigned scope, and Sol integrates and smoke-tests the result.
- Turn approved plans into working code.
- Keep changes scoped to the assigned files and files that directly depend on them.

## Working rules

- Start from `CONTEXT.md` and `backend.md` before editing code.
- Use `templates/backend.template.md` when drafting or refreshing the backend spec.
- If the work touches UI, check `ui-spec.md` and coordinate with `Gemini.md` before overwriting shared UI files.
- Do not redesign the plan unless Claude asks for a revision.
- Report the commands run, changed artifacts, validation results, and blockers in every handoff.
- Prefer one task per terminal and one responsibility per session.
- Stop and report if a required input is missing.

## Good fit tasks

- Backend implementation
- Refactors that follow an approved plan
- Bug fixes
- Build and test execution
- File-level code changes
