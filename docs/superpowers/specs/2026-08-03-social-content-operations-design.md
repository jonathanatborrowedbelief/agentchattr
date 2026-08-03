# Social Content Operations Design

**Date:** 2026-08-03

**Status:** Approved design pending written-spec review

**Control plane:** `/Users/jonathan/Documents/agentchattr/.worktrees/team-up-v2`

**Media pipeline:** `/Users/jonathan/Workspace/AG_ContentPipeline-phase0`

**Publishing service:** `/Users/jonathan/Documents/metricool-rebuild`

## Decision summary

Build two persistent Agent Chatter channels over the existing media and
publishing systems:

- `video-lab` selects, deconstructs, and recreates archived Jon videos.
- `publish-queue` prepares, approves, publishes, reconciles, and reports posts.

Agent Chatter is the orchestration and evidence surface. It does not become the
media repository, content state machine, credential store, scheduler, or social
API implementation. AG_ContentPipeline remains authoritative for content and
media artifacts. Studio (`metricool-rebuild`) remains authoritative for
publishing execution and per-target status.

The authorization model is one approval for one immutable publish manifest. An
approved manifest may execute automatically at its approved time. Any material
change invalidates the approval. First-ever platform smokes, OAuth consent,
Instagram Trial Reel graduation, TikTok production credential changes, and paid
X activation remain manual.

## Goals

1. Turn one archived Jon video into a complete, reproducible recreation package
   without manually moving instructions between terminals.
2. Turn one QC-passed asset into an approved multi-platform post with durable
   per-target receipts.
3. Coordinate Claude, Gemini, and three Codex roles through named workflows with
   visible state and bounded responsibilities.
4. Reuse the Content Machine spine, Lindsay deconstruction playbook, archived
   media, and existing social adapters.
5. Prevent duplicate posts, false readiness, premature success states, secret
   leakage, and unapproved publishing.

## Non-goals

- Rebuild video deconstruction from scratch.
- Put social credentials or raw credential-bearing responses in Agent Chatter.
- Store master media inside Agent Chatter.
- Auto-graduate Instagram Trial Reels in the first release.
- Enable a platform before one manually approved live smoke succeeds.
- Enable scheduling for an adapter without leases, durable attempts,
  idempotency, retry policy, and reconciliation.
- Run two workflows concurrently against the same five-agent cast in the first
  release.
- Restore deprecated Lindsay shift studios, SFX translation, barfill patching,
  or the old v6 split builder.

## Existing assets and authority

### Agent Chatter

- Channels are persistent namespaces and already support the names `video-lab`
  and `publish-queue`.
- Session templates are reusable JSON workflows with a channel, cast, phases,
  and output phase.
- One session may run per channel, but the shared cast currently has no global
  capacity lease.
- Current heartbeat health is insufficient because a provider can be blocked by
  an update or MCP approval screen while remaining registered and heartbeat
  online.

### Media pipeline

- Downloads contains 43 videos (41 MP4, two MOV), mostly portrait.
- The Instagram archive contains 95 root reels plus No Cap-era copies and cover
  frames.
- The YouTube archive contains 22 Shorts and metadata.
- The March teardown covers 96 posts and 90 transcripts and provides the initial
  remake ranking.
- `tools/video_deconstruct/PLAYBOOK.md` produces the generic decomposition.
- `tools/lindsay_deconstruct/PLAYBOOK.md` provides the proven recreation stages,
  including `THE_READ.md`, `LAYOUT_MAP.md`, and keep/replace/re-record/rebuild/drop
  decisions.
- Lindsay reel 2 v4 proved the process, not a postable deliverable. No new source
  reel is currently selected, and old final renders/source symlinks are not
  reliable inputs.

### Publishing service

- LinkedIn native video is the only unattended publisher with recorded live
  proof.
- Instagram regular Reel publishing exists but requires a fresh account/token
  smoke before use.
- Instagram Trial Reel publishing was previously proven, but the initial
  operating path remains a phone-ready manual handoff and manual graduation.
- TikTok has proven sandbox OAuth, reads, and inbox upload. Direct Post is not
  enabled; production approval and credential swap are still gated.
- YouTube Shorts and X have dry-run implementations but no approved live smoke.
- Facebook Reels has no verified direct adapter.
- Studio's scheduler must not be used for TikTok until options persistence,
  leases, durable attempts, idempotency, retry, and reconciliation are repaired.

## System architecture

### Ownership boundaries

| System | Owns | Must not own |
|---|---|---|
| Agent Chatter | channels, workflow phases, agent assignments, summaries, approval prompts, evidence links | credentials, source media, post execution state |
| AG_ContentPipeline | source provenance, content lineage, deconstruction artifacts, recording/edit/QC packages, Content Machine stage | social tokens, publish retries |
| Studio | authenticated approval record, schedule, per-target options, attempts, idempotency, adapter execution, reconciliation, receipts | creative source-of-truth, raw agent chat |

### Shared cast

| Identity | Responsibility |
|---|---|
| `claude-lead` | scope, decisions, assignments, approval summary, final audit |
| `gemini-video` | native visual analysis, frame/scene judgment, visual QC |
| `codex-luna` | archive research, performance evidence, platform readiness |
| `codex-terra` | recreation packages, configurations, adapter implementation |
| `codex-sol` | integration, dry-run, execution evidence, reconciliation |

A global cast lease serializes `video-lab` and `publish-queue` sessions in the
first release. Jobs may queue independently in both channels, but only one may
own the shared cast at a time. Parallelism occurs between phase participants
inside the active workflow, not between two workflows competing for the same
terminal.

## Control-plane readiness

The launcher must not report success from process existence or heartbeat alone.

1. Each dedicated identity reacquires its exact stable name after restart.
   Dedicated Team Up names do not enter the generic 30-second name reservation
   path.
2. A wrapper becomes `provider_ready` only after the child CLI exists and its
   prompt is able to receive input.
3. The launcher creates a private canary channel and sends a unique nonce through
   the production path: queue -> wrapper -> provider CLI -> `chat_send`.
4. Every exact identity must return its nonce as the correct sender.
5. Update dialogs, trust screens, MCP startup failures, and tool approvals produce
   `manual_action_required`; they never count as ready.
6. The canary channel is excluded from user work and retains only bounded status
   evidence, not raw terminal output.
7. Startup fails closed with the exact blocked identity and reason.

## `video-lab` workflow

### Intake

The initial selector uses the March teardown ranking and archive metadata. A user
may instead select a file from Downloads. Downloads is an intake source, never a
working directory.

The selected source is copied to:

`/Users/jonathan/Workspace/AG_ContentPipeline-phase0/outputs/recreation/<content_id>/source/`

`content_id` is `YYYYMMDD-<source-shortcode-or-sha8>`. Intake writes
`source/provenance.json` containing original path, copy path, SHA-256, byte size,
duration, dimensions, source account, source post identifier when available, and
capture/export date. Originals are never deleted or overwritten.

### Phases

1. **Intake + Goal — `claude-lead`**
   - Confirm account (`ai.systemsbyjon` or `itsjongutierrez`), source, remake goal,
     non-goals, target duration, and done criteria.
2. **Native Visual Teardown — `gemini-video`**
   - Analyze the copied source natively and report visual structure, camera,
     overlays, motion, artifacts, and uncertain observations.
3. **Evidence + Decomposition — `codex-luna`**
   - Run the existing local deconstruction path, attach performance evidence,
     and produce transcript/cut/beat/layout artifacts. Numeric cuts come from
     deterministic tools, not Gemini estimates.
4. **Recreation Decision — `claude-lead`**
   - Produce the remake hypothesis and the explicit
     keep/replace/re-record/rebuild/drop map. Falsifiable claims must pass the
     existing fact-check gate.
5. **Production Package — `codex-terra`**
   - Produce recording packet, asset/capture list, edit configuration, caption
     configuration, SFX proposal, and resumable execution configuration by
     reusing the Lindsay playbook and generic production components.
6. **Integrate + QC — `codex-sol` and `gemini-video`**
   - Run structural checks, measurable QC, and visual comparison. Failures return
     to the exact responsible artifact or stage.
7. **Release — `claude-lead`**
   - Audit the package and mark it `publish-ready` only with a QC report and
     immutable asset hash.

### Required artifact package

```text
outputs/recreation/<content_id>/
  source/
    source.<original-extension>
    source.normalized.mp4
    provenance.json
  teardown/
    decomposition.json
    transcript.json
    scenes.json
    beats.json
    rebuild_recipe.md
  recreation/
    REMAKE_HYPOTHESIS.md
    THE_READ.md
    LAYOUT_MAP.md
    action_map.json
    recording_packet.md
    asset_manifest.json
    edit_config.json
    caption_config.json
    sfx_config.json
  output/
    final.mp4
    qc_report.json
  publish/
    manifest.json
```

`source.normalized.mp4` is created only when a downstream tool requires a
normalized MP4; the byte-identical copied original remains beside it. The
workflow may stop before `output/final.mp4` when Jonathan must record new
footage. That is a valid `recording_required` handoff, not completion.

## Content state

The existing Content Machine spine remains authoritative:

`captured -> idea -> researched -> scripted -> recorded -> edited -> qc -> repurposed -> scheduled -> posted -> measured`

The recreation item records its source content item or source post ID. The video
workflow advances stages only after required artifacts exist. Studio owns
publishing substates; a partially published item remains `scheduled` in the
Content Machine until every required target succeeds or Jonathan explicitly
waives a failed target.

## Publish manifest and approval

### Manifest

Studio imports `publish/manifest.json`. The manifest contains no credentials.

Required fields:

```json
{
  "schema_version": 1,
  "content_item_id": "20260803-example",
  "asset": {
    "path": "output/final.mp4",
    "sha256": "64-lowercase-hex",
    "cover_path": null
  },
  "account": "ai.systemsbyjon",
  "caption": "Exact approved caption",
  "schedule_at": "2026-08-04T19:00:00Z",
  "targets": [
    {
      "platform": "linkedin",
      "mode": "native_video",
      "privacy": "public",
      "options": {}
    }
  ]
}
```

`cover_path` is nullable when a target does not accept or require a separate
cover. The manifest digest is SHA-256 over canonical JSON with sorted keys and UTF-8
encoding. Studio stores the digest, a generated approval ID, approval timestamp,
and authenticated approver. Changing the asset bytes, caption, cover, account,
target list, mode, privacy, options, or schedule changes the digest and revokes
the approval automatically.

### Approval interaction

`publish-queue` posts a fixed summary and a link to Studio's authenticated review
screen. The review screen shows the playable asset, cover, exact caption,
account, every platform/mode/privacy option, schedule in Chicago time and UTC,
and preflight results. Approval is recorded in Studio, not in chat text.

One approval authorizes execution of that exact manifest at the approved time.
It does not authorize future revisions or future posts.

## `publish-queue` workflow

1. **Import — `codex-terra`**
   - Validate manifest schema, resolve paths inside the recreation package,
     verify hashes, and create a Studio draft.
2. **Platform Preflight — `codex-luna`**
   - Report adapter status, account connection, platform limits, media
     compatibility, privacy/options completeness, and whether live execution is
     enabled.
3. **Creative QC — `gemini-video` and `claude-lead`**
   - Verify the final asset/cover/caption match the approved creative package.
4. **User Approval — Jonathan**
   - Approve the immutable manifest in Studio. This phase cannot auto-advance.
5. **Schedule/Execute — `codex-sol`**
   - Execute one target at a time using the approved digest and adapter-specific
     idempotency key.
6. **Reconcile — `codex-sol`**
   - Resolve asynchronous states and persist external ID, permalink, timestamps,
     attempt history, and terminal status.
7. **Audit — `claude-lead`**
   - Post receipts, failed targets, retry eligibility, and Content Machine stage
     change. No unsupported success claim is allowed.

## Publishing execution rules

- Each target has a durable attempt row before the adapter call.
- Idempotency key is derived from manifest digest plus platform/account/mode.
- A lease prevents a second worker from executing the same target concurrently.
- Retrying a target reuses its idempotency key.
- A target is `submitted`, `processing`, `published`, `failed`, or
  `manual_action`.
- An aggregate post is `partial` when at least one required target is published
  and at least one required target is failed/manual. Successful targets are not
  rolled back.
- TikTok `publish_id` maps to `submitted`. An inbox upload reconciles to
  `manual_action` with an inbox-ready receipt; it is not published. Only a
  subsequent platform-visible post confirmation may mark the target published.
- A platform response is sanitized before it becomes Agent Chatter evidence.
- Scheduling remains disabled per adapter until its lease, recovery, retry, and
  reconciliation tests pass.

## Platform rollout

| Order | Platform/mode | Initial state | Enablement gate |
|---|---|---|---|
| 1 | LinkedIn native video | live-capable | Revalidate existing token and run one approved live smoke |
| 2 | Instagram regular Reel | gated | Repair/verify token path, verify target account, run one approved live smoke |
| 3 | Instagram Trial Reel | manual handoff | Produce phone-ready package; graduation remains manual |
| 4 | TikTok inbox upload | gated | Production approval, approved credential swap, options persistence, reconciliation smoke |
| 5 | YouTube Shorts | disabled | OAuth consent, audited API project, privacy confirmation, approved live smoke |
| 6 | Facebook Reels | disabled | Verify intended Page, implement adapter, approved live smoke |
| 7 | X video | disabled | Paid API activation, credentials, approved live smoke |

No platform is enabled globally because another platform passed.

## Security

- Social credentials remain in their owning runtime/environment.
- Agent Chatter stores only sanitized status, immutable identifiers, and links.
- The publish manifest contains no tokens, cookies, authorization headers, or raw
  provider responses.
- Upload/publish actions require the existing private Studio session gate.
- Destructive operations, OAuth consent, production credential swaps, legal
  agreements, CAPTCHA, account-owner attestation, paid API activation, and Trial
  Reel graduation require Jonathan.
- Source media and publishing logs follow existing gitignore and secret-hygiene
  rules.

## Observability

Each workflow exposes fixed-caption lifecycle events in Agent Chatter:

- queued, waiting for cast, running phase, recording required, approval required,
  scheduled, submitted, reconciling, partial, published, failed, done.
- Recent activity never includes raw terminal text.
- Artifact links point to the canonical package or authenticated Studio page.
- Publish receipts include platform, account, mode, external ID, permalink when
  available, submitted/published timestamps, and attempt number.
- A blocked identity or adapter names the required manual action.

## Failure behavior

- A missing or changed source hash stops video processing.
- A missing recording stops at `recording_required` and preserves the package.
- A QC failure does not create a publish manifest.
- A changed publish manifest revokes approval and returns to approval-required.
- A provider timeout remains non-terminal until adapter-specific reconciliation
  determines whether the platform accepted the request.
- A platform failure affects only its target and produces a retryable or manual
  status.
- A crash releases expired leases through startup reconciliation; it does not
  silently reset attempts or create a new post.
- Agent Chatter readiness failure blocks new workflow starts. It does not pause,
  mutate, or cancel an already-approved Studio schedule.

## Validation strategy

### Agent Chatter

- Unit-test exact dedicated-name reacquisition without the generic reservation
  collision.
- Test provider-ready state separately from registration/heartbeat.
- Test all five nonce round trips and each manual-action failure mode.
- Verify two configured channels and templates persist across restart.
- Verify the global cast lease queues the second workflow.

### Video pipeline

- Run one archived Jon MP4 through intake using local/free tools.
- Verify source copy hash equals the original and the original remains unchanged.
- Verify required teardown/recreation artifacts and state transitions.
- Verify recording-required and QC-failure resumability.
- Compare deterministic cut data with Gemini's qualitative report without using
  Gemini for numeric timing.

### Publishing

- Schema, canonicalization, digest, and approval-invalidation tests.
- Path containment and asset hash tests.
- Per-target lease, idempotency, crash recovery, retry, partial, and
  reconciliation tests.
- Dry-run every adapter with the exact approved manifest.
- One manually approved live smoke per platform before enablement.
- Verify Content Machine remains `scheduled` during partial execution and moves
  to `posted` only after required-target completion or explicit waiver.

## Implementation sequence

1. Repair Agent Chatter identities, provider-ready state, five-agent canary, and
   global cast lease.
2. Add and persist `video-lab` and `publish-queue` templates/channels.
3. Build the recreation intake/package wrapper around the existing March,
   video-deconstruct, and Lindsay components.
4. Prove the video workflow with one archived Jon reel through a complete package
   or explicit recording-required checkpoint.
5. Add manifest import, authenticated review/approval, attempts, leases,
   idempotency, retry, partial status, and reconciliation to Studio.
6. Integrate LinkedIn and Instagram regular Reel through the unified Studio
   boundary; emit Trial Reel phone packages.
7. Enable TikTok inbox, YouTube, Facebook, and X individually as their gates pass.
8. Connect publishing receipts to Content Machine `posted` and `measured` stages.

## Planning decomposition

This umbrella design becomes three independently executable implementation
plans, completed in dependency order:

1. **Agent Chatter reliability and workflow configuration** — stable identities,
   provider-ready state, five-agent canary, global cast lease, channels, and
   templates.
2. **Video-lab recreation package** — archive intake, provenance, existing
   deconstruction/Lindsay orchestration, resumable artifacts, and QC contract.
3. **Publish-queue and Studio execution** — manifest import, review/approval,
   target attempts, adapter gates, scheduling, reconciliation, and Content
   Machine receipts.

Each plan must pass its own tests and review before the dependent plan begins.

## Acceptance criteria

1. The launcher cannot report ready until all five exact identities complete a
   real nonce round trip.
2. `video-lab` can select an archived Jon video and produce the defined package
   without touching the original.
3. A QC-passed final asset can create a manifest whose approval is invalidated by
   any material change.
4. An approved manifest can execute an enabled adapter once without duplicate
   posting and produce a durable receipt.
5. Multi-target partial failure preserves successful receipts and exposes an
   explicit retry/manual action for failed targets.
6. Trial Reels produce a complete phone-ready handoff without auto-graduation.
7. No disabled platform, paid action, OAuth consent, credential swap, or live
   first smoke occurs without Jonathan's manual authorization.
8. Agent Chatter, AG_ContentPipeline, Studio, and Content Machine each retain the
   ownership boundaries defined in this document.
