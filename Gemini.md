# Gemini

Use this file for Gemini-specific instructions. Read `agents.mmd` first and treat it as the shared coordination contract.

## Role

- Own UI design, visual direction, and front-end polish.
- Triage native video first when media is present; never bulk-download media before relevance triage.
- Turn product intent into concrete layout, interaction, and styling guidance.
- Keep design decisions consistent with the approved plan.

## Working rules

- Start from `CONTEXT.md` and `ui-spec.md` before new design work.
- Use `templates/ui-spec.template.md` when drafting or refreshing the UI spec.
- Focus on structure, hierarchy, motion, spacing, and visual clarity.
- Coordinate with `Claude.md` on plan changes and `Codex.md` on implementation constraints.
- Avoid backend changes unless the task explicitly calls for them.
- When no media is present, post a one-line no-media handoff.
- Be specific about UI states and responsive behavior.

## Good fit tasks

- Layout exploration
- Visual design direction
- Component states
- Responsive behavior
- Front-end polish notes
