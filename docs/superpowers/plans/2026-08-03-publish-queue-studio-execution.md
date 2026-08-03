# Publish Queue and Studio Execution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Import one QC-passed recreation manifest into Studio, approve its immutable digest once, execute enabled platforms without duplicates, reconcile each target durably, and expose receipts in `publish-queue`.

**Architecture:** A session-owned local importer verifies package paths/hashes and uploads private media; deployed Studio never reads the local filesystem. Studio owns manifests, authenticated approvals, per-target attempts/leases/idempotency/reconciliation, adapters, and receipts. Platform enablement is per mode and remains manual until an approved live smoke passes.

**Tech Stack:** Next.js, TypeScript, Drizzle/Postgres/PGlite, Supabase private storage, Vitest, existing Studio session gate and platform adapter seams.

## Global Constraints

- Target path is `/Users/jonathan/Documents/metricool-rebuild`, which currently has no `.git`; Task 0 is a hard gate before edits.
- Never print, copy, commit, or send `.env.local`, tokens, cookies, auth headers, service-role keys, or raw provider responses.
- Never use `SUPABASE_SERVICE_ROLE_KEY`; never run production DDL through `pnpm db:migrate`.
- Approval occurs only in authenticated Studio for one canonical manifest digest; chat text cannot approve.
- First live platform smoke, OAuth consent, TikTok credential swap/production approval, Trial graduation, and paid X activation require Jonathan.
- Execute one target at a time. A successful target is never rolled back because another target fails.
- TikTok `publish_id` means `submitted`; inbox-ready means `manual_action`, never `published`.
- Run lint and build sequentially. Use PGlite for migration tests.

---

## Task 0: Resolve repository ownership before mutation

**Files:** read-only inspection first; no code changes

- [ ] Run `find /Users/jonathan/Documents/metricool-rebuild -maxdepth 4 -name .git -print` and inspect documented origins in `CONTEXT.md`, `.vercel/project.json` (without printing secrets), and any parent workspace metadata.
- [ ] Identify the authoritative Git remote/history or an existing worktree containing the same project. Compare file hashes before selecting it.
- [ ] If an authoritative repository exists, create a dedicated `codex/publish-queue-studio` worktree and use that path for all later tasks.
- [ ] If no repository exists, stop and report a blocker. Do not run `git init`, invent history, overwrite the deployed folder, or implement unversioned changes without Jonathan's explicit authorization.
- [ ] Record the resolved repository root, branch, clean/dirty status, and commit base in the execution checkpoint. Preserve all pre-existing changes.

## Task 1: Add the manifest contract and local import boundary

**Files:** create `lib/publishing/manifest.ts`, `lib/services/publish-manifests.ts`, `app/api/publish-manifests/import/route.ts`, `tests/publish-manifest.test.ts`, `tests/publish-import.test.ts`; modify `lib/db/schema.ts`, `lib/services/posts.ts`; create next Drizzle migration

- [ ] Write failing tests for schema v1, recursive unknown credential/header rejection, recursively sorted object keys, stable array order, UTF-8 compact JSON, SHA-256 digest, traversal/absolute/symlink escape rejection, asset hash mismatch, idempotent same-digest import, and approval revocation on changed digest.
- [ ] Implement:

```ts
export function parsePublishManifest(input: unknown): PublishManifestV1;
export function canonicalizeManifest(m: PublishManifestV1): string;
export function digestManifest(m: PublishManifestV1): string;
export async function resolvePackageAsset(root: string, rel: string): Promise<string>;
export async function verifyFileSha256(path: string, expected: string): Promise<void>;
```

- [ ] Add `publish_manifests` and `publish_approvals`; keep approved rows immutable. Link imported posts to a manifest. Store canonical JSON, digest, account, caption, UTC schedule, asset/cover hashes, and private object keys—never local paths as deployed runtime dependencies.
- [ ] Make the local importer verify `outputs/recreation/<content_id>`, then use the existing signed private-upload seam. The authenticated API accepts verified manifest data plus private object keys; Vercel never attempts `fs.realpath` on Jon's machine.
- [ ] Run `pnpm test -- tests/publish-manifest.test.ts tests/publish-import.test.ts`. Expected: pass.
- [ ] Commit as `feat(publishing): import immutable manifests`.

## Task 2: Build authenticated review and digest approval

**Files:** create `app/publish/[manifestId]/page.tsx`, `components/publish-review.tsx`, `components/publish-approval-actions.tsx`, `lib/services/publish-approvals.ts`, API routes under `app/api/publish-manifests/[id]/`, tests; modify `middleware.ts`, dashboard, focused CSS

- [ ] Write failing service tests for authenticated approval, digest re-check in the approval transaction, stale/changed digest rejection, revocation, and non-human/chat execution rejection.
- [ ] Implement `approveManifest`, `assertApprovedDigest`, and `revokeApproval`. Persist authenticated approver, timestamp, manifest digest, optional revocation time/reason.
- [ ] Protect `/publish/:path*` and every manifest route with the existing Studio session gate.
- [ ] Build a review presentation model showing private playable video, optional cover, exact caption, account, all target mode/privacy/options values, adapter preflight, `America/Chicago` time, and UTC.
- [ ] Test that changing asset bytes/hash, cover, caption, account, targets, mode, privacy, options, or schedule requires a new digest and approval.
- [ ] Run `pnpm test -- tests/publish-approval.test.ts tests/publish-review.test.ts`. Expected: pass.
- [ ] Commit as `feat(publishing): add immutable approval review`.

## Task 3: Add durable targets, attempts, leases, and aggregate states

**Files:** modify `lib/db/schema.ts`, `lib/adapters/types.ts`, `lib/services/posts.ts`, `lib/services/scheduler.ts`, scheduler route, lifecycle tests; create `lib/publishing/idempotency.ts`, `lib/services/publish-targets.ts`, `lib/services/recovery.ts`, `lib/services/reconciliation.ts`, retry route, execution/recovery/reconciliation tests; add migration

- [ ] Write failing tests for a durable attempt before adapter call, one-target lease exclusivity, stable idempotency across retries, expired-lease recovery, uncertain timeout reconciliation, retry eligibility/backoff, partial aggregate state, and no duplicate call after crash.
- [ ] Add target states `pending|submitted|processing|published|failed|manual_action`; persist mode, privacy, canonical options, required flag, idempotency key, lease owner/expiry, retry fields, external ID/permalink, and timestamps.
- [ ] Add `publish_attempts` with monotonic attempt number and unique `(post_target_id, attempt_number)`. Store sanitized status/error/receipt only.
- [ ] Implement:

```ts
targetIdempotencyKey(digest, platform, account, mode): string;
claimDueTarget(ctx, workerId, leaseMs): Promise<ClaimedTarget | null>;
releaseExpiredLeases(ctx, now): Promise<number>;
deriveAggregateStatus(targets): "scheduled"|"processing"|"partial"|"published"|"failed";
```

- [ ] Replace the current `pending -> publishing -> adapter` shortcut. Scheduler order is recover expired leases, claim one approved digest-matched target, create attempt, execute, then reconcile.
- [ ] Keep an uncertain/provider-timeout attempt non-terminal. Successful targets remain durable when another target becomes failed/manual.
- [ ] Run `pnpm test -- tests/publish-execution.test.ts tests/publish-recovery.test.ts tests/publish-reconciliation.test.ts tests/lifecycle.test.ts`. Expected: pass.
- [ ] Commit as `feat(publishing): add durable target execution`.

## Task 4: Define adapter capabilities and per-mode gates

**Files:** modify `lib/adapters/types.ts`, `lib/adapters/registry.ts`, `lib/adapters/mock.ts`; create `lib/adapters/capabilities.ts`, `lib/services/preflight.ts`, `tests/adapter-contract.test.ts`, `tests/platform-gates.test.ts`

- [ ] Write contract tests for preflight, execute, reconcile, sanitized evidence, explicit enablement, mode-specific scheduling, and disabled-by-default live adapters.
- [ ] Define execution result states `submitted|processing|published|failed|manual_action`, provider correlation ID, sanitized receipt, retryability, and next reconciliation time.
- [ ] Add an explicit platform/mode gate registry. Passing LinkedIn must not enable Instagram or any other mode.
- [ ] Require lease/recovery/retry/reconciliation contract coverage before a mode can be scheduling-enabled.
- [ ] Run `pnpm test -- tests/adapter-contract.test.ts tests/platform-gates.test.ts`. Expected: pass.
- [ ] Commit as `feat(adapters): add capability gates`.

## Task 5: Add LinkedIn native-video and Instagram workflows

**Files:** create typed LinkedIn and Instagram clients/config/adapters/tests; create `lib/services/trial-handoff.ts` and Trial handoff route/tests; modify adapter registry

- [ ] Reimplement the typed official LinkedIn API boundary from reference behavior in `AG_ContentPipeline-phase0/execution/linkedin_publish.py`; do not shell out or move credentials to Agent Chatter.
- [ ] Test chunk upload, processing poll, native post creation, permalink/receipt, timeout-to-reconcile, sanitized errors, and disabled gate. Keep live mode disabled until Jonathan approves token revalidation and one live smoke.
- [ ] Reimplement Instagram regular Reel container-create, poll, publish, and permalink behavior from `tools/content_factory/ig_publish.py`. Test target account verification, processing, retry, and disabled gate.
- [ ] Implement Trial Reel release one as a phone-ready private package and `manual_action` receipt. It must never call `media_publish`; graduation remains Jonathan-only.
- [ ] Run `pnpm test -- tests/linkedin-client.test.ts tests/linkedin-adapter.test.ts tests/instagram-client.test.ts tests/instagram-adapter.test.ts tests/trial-handoff.test.ts`. Expected: pass with network mocked.
- [ ] Commit as `feat(adapters): add linkedin and instagram workflows`.

## Task 6: Repair TikTok asynchronous reconciliation

**Files:** modify `lib/adapters/tiktok.ts`, `lib/platforms/tiktok/jobs.ts`, `tests/tiktok-webhooks.test.ts`; add focused TikTok target tests

- [ ] Write failing tests: init/upload returns submitted; processing remains processing; `SEND_TO_USER_INBOX` becomes manual action with inbox-ready receipt; visible `PUBLISH_COMPLETE` becomes published; duplicate webhook/status fetch is idempotent.
- [ ] Link provider-specific `publish_jobs` to generic target/attempt rather than using it as the cross-platform ledger.
- [ ] Persist target options unchanged through scheduling and execution.
- [ ] Keep TikTok scheduling disabled until all reliability tests pass and production credentials/approval are manually supplied.
- [ ] Run `pnpm test -- tests/tiktok-options.test.ts tests/tiktok-webhooks.test.ts tests/tiktok-publish.test.ts`. Expected: pass.
- [ ] Commit as `fix(tiktok): reconcile asynchronous publish states`.

## Task 7: Add the Content Machine receipt port and Agent Chatter evidence

**Files:** create `lib/integrations/content-machine/types.ts`, `lib/integrations/content-machine/sync.ts`, `tests/content-machine-sync.test.ts`; modify receipt API/presentation; update `CONTEXT.md`

- [ ] Define injected `ContentMachineReceiptSink` because the Content Machine spine is designed but not implemented.
- [ ] Test: partial/failed/manual keeps `scheduled`; all required published requests `posted`; authenticated waiver may request `posted`; `measured` requires a later metrics event.
- [ ] Emit `PublishReceiptEnvelopeV1` with content item ID, manifest digest, aggregate state, sanitized per-target receipts, and waiver evidence. Exclude credentials/raw responses.
- [ ] Expose authenticated Studio receipt URLs and a sanitized payload for Agent Chatter `publish-queue` audit messages.
- [ ] Run `pnpm test -- tests/content-machine-sync.test.ts`. Expected: pass.
- [ ] Commit as `feat(publishing): expose durable publish receipts`.

## Task 8: Migration, dry-run, and release gates

**Files:** migrations/tests and `CONTEXT.md`; no credential file edits

- [ ] Validate migrations in PGlite and verify `studio_app` privileges do not widen. Production DDL later requires privileged Supabase SQL/MCP plus matching `studio.__drizzle_migrations` bookkeeping.
- [ ] Run sequentially:

```bash
pnpm test
pnpm lint
pnpm build
```

- [ ] Import one QC-passed fixture manifest, upload private fixture media, review it, approve its digest, dry-run every configured target, execute the mock adapter once, simulate crash/recovery, and verify no duplicate attempt.
- [ ] Confirm live gates remain: LinkedIn enabled only after explicit approved smoke; Instagram regular, TikTok, YouTube, Facebook, and X disabled; Trial is manual handoff.
- [ ] Update `CONTEXT.md` with repository root, migrations, validations, adapter gate matrix, and exact manual next actions.
- [ ] Commit as `docs(publishing): record publish queue readiness`.

## Handoff gate

No live platform call occurs under this plan without a separate, explicit Jonathan approval for that platform's first smoke. If Task 0 cannot establish Git ownership, this plan is blocked before mutation while Agent Chatter and video-lab continue independently.
