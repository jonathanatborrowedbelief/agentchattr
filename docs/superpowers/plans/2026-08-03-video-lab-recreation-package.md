# Video Lab Recreation Package Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn one archived Jon video into a hash-verified, resumable recreation package by wrapping the existing generic deconstruction and Lindsay recreation tools without modifying the original media.

**Architecture:** Add a small `tools/video_lab` package and CLI inside AG_ContentPipeline. The package owns selection, intake, artifact contracts, workflow state, and orchestration; existing `tools/video_deconstruct` modules continue to own deterministic analysis, and the Lindsay playbook continues to define the recreation method. A `ContentStatePort` validates desired stage transitions against a fake until the planned Content Machine spine exists. Agent Chatter receives sanitized lifecycle events and artifact paths, while media stays in `outputs/recreation/<content_id>`.

**Tech Stack:** Python 3, `ffprobe`/`ffmpeg`, existing `tools.video_deconstruct` CLI and reports, existing Lindsay playbook and `execution/clone_reel.py`, `pytest`, JSON Schema-style validation with standard-library Python.

## Global Constraints

- Work only in `/Users/jonathan/Workspace/AG_ContentPipeline-phase0` on branch `phase-0-feed`.
- Never delete, rename, overwrite, or edit the source file in Downloads or an archive.
- Copy video, not audio-only media. Deterministic scene/cut timestamps come from local tools; Gemini supplies qualitative visual judgment only.
- Do not reuse `24_lindsay_shift_studio.py`, `25_lindsay_broll_align_studio.py`, `22_sfx_translate.py`, `14_captions.py`, `13_build_v6_split.py`, old `_v6_tmp`/quarantine outputs, Zernio `execution/distribute_reel.py`, barfill v2, or any retired reel-specific compositor.
- Do not spend paid API credits or generate paid SFX in automated tests.
- A missing Jonathan recording ends in `recording_required`; it is not completion and not failure.
- A QC failure must not create `publish/manifest.json`.
- The Content Machine spine is not implemented in this worktree. Use a port/fake; do not invent production Supabase writes.
- Ignore generated `outputs/recreation/` artifacts in `.gitignore`; commit code and deliberate fixtures only.
- Use `apply_patch` for edits. Preserve unrelated changes. Commit only files owned by the task.

---

## Task 1: Define the package contract and state machine

**Files:**

- Create: `tools/video_lab/__init__.py`
- Create: `tools/video_lab/models.py`
- Create: `tools/video_lab/paths.py`
- Create: `tools/video_lab/content_state.py`
- Create: `tests/test_video_lab_models.py`
- Create: `tests/test_video_lab_paths.py`
- Create: `tests/test_video_lab_state.py`

- [ ] Write failing tests for the authoritative stages:

```python
STAGES = (
    "captured", "idea", "researched", "scripted", "recorded", "edited",
    "qc", "repurposed", "scheduled", "posted", "measured",
)
```

The tests must reject skipped or backward transitions, except an idempotent write of the current stage. They must also assert that `recording_required` and `qc_failed` are workflow statuses, not Content Machine stages. `ContentStatePort` is an injected protocol; production Supabase integration is out of scope until Spine v1 exists.

- [ ] Write failing tests for `RecreationPaths.for_id(root, content_id)`. It must reject traversal, absolute identifiers, and identifiers not matching `^[0-9]{8}-[a-zA-Z0-9_-]+$`; every returned path must resolve below `<root>/outputs/recreation/<content_id>`.

- [ ] Implement immutable dataclasses or typed dictionaries for:

```python
class WorkflowStatus(str, Enum):
    ACTIVE = "active"
    RECORDING_REQUIRED = "recording_required"
    QC_FAILED = "qc_failed"
    PUBLISH_READY = "publish_ready"

@dataclass(frozen=True)
class RecreationState:
    schema_version: int
    content_id: str
    content_stage: str
    workflow_status: str
    source_sha256: str
```

- [ ] Implement atomic JSON writes using a temporary sibling file plus `Path.replace`; never partially rewrite state.

- [ ] Run:

```bash
python3 -m pytest tests/test_video_lab_models.py tests/test_video_lab_paths.py tests/test_video_lab_state.py -q
```

Expected: all tests pass.

- [ ] Commit:

```bash
git add tools/video_lab tests/test_video_lab_models.py tests/test_video_lab_paths.py tests/test_video_lab_state.py
git commit -m "feat(recreation): define package contract"
```

## Task 2: Select an approved source and build immutable video intake

**Files:**

- Create: `tools/video_lab/selector.py`
- Create: `tools/video_lab/intake.py`
- Create: `tests/test_video_lab_selector.py`
- Create: `tests/test_video_lab_intake.py`
- Modify: `tools/video_lab/models.py`
- Modify: `.gitignore`

- [ ] Write failing selector tests against the approved ten-shortcode queue in `docs/superpowers/plans/2026-07-25-phase-0-runbook.md` and the shortcode-keyed feature shape from `execution/scaffold_redo_batch.py`. Never invent a new numeric ranking from individual March post rank.

- [ ] Write failing intake tests using a generated one-second MP4 fixture. Cover byte-identical copy, SHA-256 equality, original mtime/content unchanged, deterministic `content_id`, collision reuse for the same hash, collision rejection for different bytes, and MOV preservation.

- [ ] Define the public interface:

```python
def ingest_source(
    source: Path,
    output_root: Path,
    *,
    source_account: str,
    source_post_id: str | None = None,
    captured_at: str | None = None,
) -> tuple[RecreationPaths, dict]:
    """Copy source bytes and atomically write source/provenance.json."""
```

- [ ] Use streaming SHA-256. Copy to `source/source.<original-extension>` with `shutil.copy2`; verify the destination hash after copy. Do not follow a dead symlink as a valid source.

- [ ] Probe with `ffprobe` JSON and persist only: original path, copy path relative to package, SHA-256, byte size, duration, width, height, source account, optional post ID, and capture/export date. Never write environment values or command output.

- [ ] Add `normalize_source_if_required(paths) -> Path` that creates `source/source.normalized.mp4` only when the existing downstream probe rejects the original format. Preserve the original copy beside it.

- [ ] Run:

```bash
python3 -m pytest tests/test_video_lab_selector.py tests/test_video_lab_intake.py -q
```

Expected: all tests pass and the fixture original is unchanged.

- [ ] Commit:

```bash
git add .gitignore tools/video_lab/selector.py tools/video_lab/intake.py tools/video_lab/models.py tests/test_video_lab_selector.py tests/test_video_lab_intake.py
git commit -m "feat(recreation): add immutable video intake"
```

## Task 3: Orchestrate deterministic teardown using existing tools

**Files:**

- Create: `tools/video_lab/teardown.py`
- Create: `tests/test_video_lab_teardown.py`
- Modify: `tools/video_lab/models.py`
- Reuse unchanged: `tools/video_deconstruct/cli.py`
- Reuse unchanged: `tools/video_deconstruct/reports/rebuild_recipe.py`

- [ ] Write a failing orchestration test with subprocess calls mocked. Assert the command begins with:

```bash
python3 -m tools.video_deconstruct.cli full --source <copied-source> --work <package>/teardown/work
```

Then assert the wrapper materializes the exact aliases: `work/decomposition.json -> teardown/decomposition.json`, `work/audio/transcript.json -> teardown/transcript.json`, `work/visual/cuts.json -> teardown/scenes.json`, `work/segments/_manifest.json -> teardown/beats.json`, and `work/_reports/rebuild_recipe.md -> teardown/rebuild_recipe.md`.

- [ ] Implement:

```python
def run_teardown(paths: RecreationPaths, *, dry_run: bool = False) -> dict:
    """Run/resume deterministic deconstruction and return sanitized evidence."""
```

It must verify the current copied source hash before every run, use `subprocess.run(..., check=True)` with argument arrays, and preserve completed artifacts on failure.

- [ ] Map existing generic outputs explicitly. If an upstream artifact has a different filename, copy/project it; do not teach downstream callers the generic work-tree layout.

- [ ] Run the existing rebuild recipe report from the resulting `decomposition.json`. Numeric scene/cut timestamps may only come from `s02_scene_cuts`/manifest evidence.

- [ ] Record command, start/end timestamps, exit status, and output artifact hashes in `teardown/run.json`; exclude stdout/stderr bodies.

- [ ] Run:

```bash
python3 -m pytest tests/test_video_lab_teardown.py tools/video_deconstruct/tests/test_s02_scene_cuts.py tools/video_deconstruct/tests/test_s06_manifest.py -q
```

Expected: all tests pass.

- [ ] Commit:

```bash
git add tools/video_lab/teardown.py tools/video_lab/models.py tests/test_video_lab_teardown.py
git commit -m "feat(recreation): wrap deterministic teardown"
```

## Task 4: Create the recreation decision and recording handoff

**Files:**

- Create: `tools/video_lab/decision.py`
- Create: `tests/test_video_lab_decision.py`
- Create: `tools/video_lab/schemas/action-map.schema.json`
- Reference: `tools/lindsay_deconstruct/PLAYBOOK.md`
- Reference: `directives/lindsay-clone-sop.md`

- [ ] Write failing validation tests for the seven required recreation artifacts:

```text
recreation/REMAKE_HYPOTHESIS.md
recreation/THE_READ.md
recreation/LAYOUT_MAP.md
recreation/action_map.json
recreation/recording_packet.md
recreation/asset_manifest.json
recreation/edit_config.json
recreation/caption_config.json
recreation/sfx_config.json
```

- [ ] Define `action_map.json` so every deterministic beat ID appears exactly once and has one action from `keep`, `replace`, `re-record`, `rebuild`, `drop`, plus rationale and evidence references. Reject unknown beats and duplicate coverage.

- [ ] Implement `validate_recreation_decision(paths) -> list[str]`. It must confirm `THE_READ.md` and `LAYOUT_MAP.md` exist before any recording/capture action and verify that `asset_manifest.json` references only package-contained or explicitly declared external source paths.

- [ ] Implement `derive_recording_status(paths)`. When any `re-record` action lacks a corresponding recording asset, atomically persist `workflow_status=recording_required`, preserve the package, and print the exact `recording_packet.md` path.

- [ ] Keep SFX proposal non-spending: `sfx_config.json` defaults to `proposal_only: true`; generation/burn requires an explicit later user action.

- [ ] Run:

```bash
python3 -m pytest tests/test_video_lab_decision.py -q
```

Expected: all tests pass.

- [ ] Commit:

```bash
git add tools/video_lab/decision.py tools/video_lab/schemas tests/test_video_lab_decision.py
git commit -m "feat(recreation): validate remake decisions"
```

## Task 5: Add resumable production and QC gates

**Files:**

- Create: `tools/video_lab/production.py`
- Create: `tools/video_lab/qc.py`
- Create: `tests/test_video_lab_production.py`
- Create: `tests/test_video_lab_qc.py`
- Reuse: `execution/clone_reel.py`

- [ ] Write a failing production test proving the wrapper renders the existing `clone_reel.py --dry-run` command from `recreation/edit_config.json`, maps only supported generic stages, and refuses a package still marked `recording_required`.

- [ ] Implement `build_or_resume(paths, from_stage=None, to_stage=None, dry_run=False)`. It must call the existing clone wrapper with an argument list, never the deprecated studios, and preserve intermediate outputs for resume.

- [ ] Write failing QC tests for: missing final video, final hash mismatch, invalid codec/dimensions/duration, missing deterministic teardown, failed structural checks, and a visual-review status other than `passed`.

- [ ] Define `output/qc_report.json`:

```json
{
  "schema_version": 1,
  "asset_sha256": "<64 lowercase hex>",
  "structural": {"status": "passed", "checks": []},
  "visual": {"status": "passed", "reviewer": "gemini-video", "evidence": []},
  "overall": "passed",
  "checked_at": "<UTC ISO-8601>"
}
```

- [ ] Implement `release_if_qc_passes(paths, content_state: ContentStatePort)`. On failure, set `qc_failed` and ensure no publish manifest exists. On success, request stage `qc` through the injected port, set workflow status `publish_ready`, and persist the immutable final hash. The tests use a fake port.

- [ ] Run:

```bash
python3 -m pytest tests/test_video_lab_production.py tests/test_video_lab_qc.py -q
./tools/lindsay_deconstruct/tests/test_stage6_plan_smoke.sh
```

Expected: tests and the existing stage-six smoke pass.

- [ ] Commit:

```bash
git add tools/video_lab/production.py tools/video_lab/qc.py tests/test_video_lab_production.py tests/test_video_lab_qc.py
git commit -m "feat(recreation): add resumable build and qc gate"
```

## Task 6: Expose one CLI and prove one archived Jon source

**Files:**

- Create: `execution/recreate_video.py`
- Create: `tests/test_video_lab_cli.py`
- Modify: `CONTEXT.md`
- Runtime output: `outputs/recreation/<content_id>/`

- [ ] Write CLI tests for `intake`, `teardown`, `validate-decision`, `build`, `qc`, and `status`. Every command must support `--package`; intake alone accepts `--source`. `status` must be read-only and JSON-safe.

- [ ] Implement the CLI with this safe shape:

```bash
python3 execution/recreate_video.py intake --source /absolute/video.mp4 --account ai.systemsbyjon
python3 execution/recreate_video.py teardown --package outputs/recreation/<content_id>
python3 execution/recreate_video.py status --package outputs/recreation/<content_id>
```

- [ ] Select one source from the March ranked remake queue whose MP4 exists in the Instagram/YouTube archives; fall back to a portrait MP4 in Downloads only if the ranked source is unavailable. Record why it was selected in `REMAKE_HYPOTHESIS.md`.

- [ ] Run intake and deterministic teardown with local/free tools. Verify with `shasum -a 256` that original and copied source match, and verify the original size and mtime did not change.

- [ ] Drive the package through `publish_ready` when existing footage suffices, otherwise stop at a complete `recording_required` handoff. Never fabricate a final render.

- [ ] Run:

```bash
python3 -m pytest tests/test_video_lab_*.py tools/video_deconstruct/tests -q
python3 execution/recreate_video.py status --package outputs/recreation/<content_id>
git status --short
```

Expected: all tests pass; status is `publish_ready` or `recording_required`; only intended code/docs are tracked, while generated media stays ignored.

- [ ] Update `CONTEXT.md` with the completed package ID, current status, exact artifact path, validation commands, and next human gate.

- [ ] Commit:

```bash
git add execution/recreate_video.py tools/video_lab tests/test_video_lab_cli.py CONTEXT.md
git commit -m "feat(recreation): prove archived Jon video workflow"
```

## Cross-plan handoff

The publishing plan may start only when this plan emits `publish/manifest.json` from a QC-passed asset. If execution stops at `recording_required`, the handoff is the immutable package plus `recreation/recording_packet.md`; Studio import must not run.
