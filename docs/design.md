# Social Studio — Design

## 1. Problem

A team publishes a blog post and then wants it on every social channel, sized
correctly and worded natively for each, without a human re-cropping images and
retyping captions. The hard part is not the transformation — it is that social
platforms are unreliable in specific, well-known ways:

- they time out **after** accepting your post,
- they rate limit you and expect you to honour `Retry-After`,
- they confirm delivery asynchronously, out of band,
- and they punish naive retries with duplicate posts on a public timeline.

Social Studio therefore treats "publish" as a distributed-systems problem, not
a formatting problem.

## 2. Architecture

```
                       ┌────────────────────────────────────────────┐
   POST /campaigns ───▶│              FastAPI  (:8000)              │
                       │                                            │
                       │  api/campaigns  api/posts  api/webhooks    │
                       └───────┬────────────────────────┬───────────┘
                               │                        │
                    ┌──────────▼──────────┐   ┌─────────▼──────────┐
                    │  campaign_service   │   │  publish_service   │
                    │  validate           │   │  status machine    │
                    │  ├ image_service    │   │  no platform ifs   │
                    │  └ caption_service  │   └─────────┬──────────┘
                    └──────────┬──────────┘             │
                               │                        │
                       ┌───────▼────────┐    ┌──────────▼───────────┐
                       │  SQLite (ORM)  │    │  publisher_factory   │
                       │  campaigns     │    │        .get(platform)│
                       │  social_posts  │    └──────────┬───────────┘
                       │  platform_tokens│              │
                       └────────────────┘    ┌──────────▼───────────┐
                               ▲             │  «SocialPublisher»   │
                               │             │  authenticate()      │
                       ┌───────┴────────┐    │  publish()           │
                       │  APScheduler   │    │  get_status()        │
                       │  SQLAlchemy    │    └──────┬────────┬──────┘
                       │  jobstore(.db) │           │        │
                       └────────────────┘   ┌───────▼──┐ ┌───▼──────┐
                                            │ Instagram│ │    X     │
                                            │ adapter  │ │ adapter  │
                                            └───────┬──┘ └───┬──────┘
                                                    │        │
                                                 httpx + Idempotency-Key
                                                    │        │
                       ┌────────────────────────────▼────────▼───────┐
                       │        Mock Platform  (:9000)               │
                       │  OAuth · UNIQUE(platform, idem_key)         │
                       │  429+Retry-After · dropped responses        │
                       └────────────────────┬────────────────────────┘
                                            │
                     HMAC-SHA256 signed delivery webhook
                                            │
                       POST /webhook/social-delivery  ──▶ status=published
```

The single most important structural rule: **business logic never names a
platform.** `publish_service` asks `publisher_factory.get(post.platform)` for a
`SocialPublisher` and calls the interface. Adding a third platform is one
adapter subclass plus one registry line — `tests/test_architecture.py` enforces
both the absence of platform branching and the extensibility claim.

## 3. Platform specs

| Platform  | Image      | Aspect | Caption limit | Hashtags | URL in caption |
|-----------|-----------|--------|---------------|----------|----------------|
| Instagram | 1080×1080 | 1:1    | 2200 chars    | up to 8  | no — not clickable, "link in bio" |
| X         | 1600×900  | 16:9   | 280 chars     | up to 2  | yes            |

**Image strategy — contain + derived backdrop, not center-crop.** A hard
center-crop of a 16:9 hero into a 1:1 square discards ~44% of the frame and
routinely cuts off the subject. Instead the whole source is scaled to *fit*
inside the target box, and the leftover space is filled with a cover-scaled,
Gaussian-blurred copy of the same image. Nothing is ever lost, and the result
still fills the frame edge-to-edge.

**Caption strategy.** One shared brand voice object (tone, CTA, signature
hashtags) is composed with a per-platform `PlatformCaptionRules` record. The
body summary budget is computed from the platform limit minus the fixed parts,
so captions fit by construction rather than by blind truncation. Generation is
deterministic and offline, which makes it testable. An optional AI rewriter can
be installed with `caption_service.set_ai_rewriter(fn)`; it is a post-processor
over the deterministic draft, so the system degrades to templates if the model
is unavailable and never becomes dependent on a paid API.

## 4. Data model

**campaigns** — `id, title, body, url, source_image, created_at`

**social_posts** — `id, campaign_id, platform, caption, image_path, status,
idempotency_key, external_post_id, scheduled_at, published_at, failure_reason,
created_at, updated_at`, with `UNIQUE(platform, idempotency_key)`.

**platform_tokens** — `id, platform, encrypted_token, iv, created_at`. There is
deliberately no plaintext column.

Mock platform (separate SQLite file): **platform_posts** with
`UNIQUE(platform, idempotency_key)`, plus **platform_state** holding the armed
failure simulations.

## 5. API surface

| Method | Path | Purpose |
|--------|------|---------|
| GET  | `/health` | liveness + configured platforms |
| POST | `/campaigns` | create campaign, render images, write captions, queue posts |
| GET  | `/campaigns/{id}` | campaign with all social posts |
| POST | `/campaigns/{id}/publish` | publish now |
| POST | `/campaigns/{id}/schedule` | durable scheduled publish |
| GET  | `/social-posts/{id}` | single post state |
| POST | `/webhook/social-delivery` | signed delivery callback |
| GET  | `/scheduler/jobs` | jobs currently in the persistent jobstore |

## 6. Idempotency strategy

Each `social_posts` row is assigned, **once at creation**, a key derived from
its own UUID:

```
idempotency_key = "ss-{platform}-" + sha256(f"{platform}:{social_post_id}")[:32]
```

The key is stored on the row and reused verbatim on every attempt. It is never
regenerated per attempt, per process, or per retry — regenerating it would
defeat the entire mechanism.

On the platform side, the key is enforced by a real
`UNIQUE(platform, idempotency_key)` constraint. The insert path is
try-INSERT / catch-`IntegrityError` / read-back-the-existing-row, so concurrent
duplicate requests race at the database and *both* receive the winner's post
id. `test_concurrent_duplicate_publishes_collapse_to_one` fires six
simultaneous publishes with one key and asserts a single post id comes back.

## 7. Retry strategy

| Condition | Classification | Action |
|-----------|---------------|--------|
| HTTP 429 | `RateLimitedError` | sleep **exactly** `Retry-After`, then retry |
| timeout / connection reset | `TransientPublishError` | exponential backoff (0.5→1→2→4s, capped) |
| HTTP 5xx | `TransientPublishError` | same backoff |
| HTTP 401 | transient once | drop the cached token, re-authenticate, retry |
| HTTP 4xx (other) | `PublishError` | permanent — mark `failed`, no retry |
| retries exhausted | — | mark `failed` with the reason recorded |

Every retry carries the original idempotency key, so a retry after a lost
response resolves to the *same* platform post rather than a duplicate. The
adapter honours the server's stated `Retry-After` rather than a guess of its
own — the demo measures 2.04s elapsed against a `Retry-After: 2`.

## 8. Scheduling strategy

APScheduler with a `SQLAlchemyJobStore` on a SQLite file. Job targets are
stored as the **import path string** `app.scheduler.worker:run_scheduled_publish`,
not as a closure, so a job written by one process is resolvable by the next
one. `coalesce=True` collapses runs missed during downtime into one, and
`misfire_grace_time=3600` means a job whose moment passed while the process was
dead still runs on restart rather than being silently dropped.

Crash safety comes from idempotency rather than from bookkeeping: re-running
`run_scheduled_publish` is harmless because already-published posts short
circuit and everything else retries under its original key.

## 9. Status machine

```
  queued ──── publish() returns 2xx ────▶ publishing
     │                                        │
     │                          verified webhook (HMAC OK)
     │                                        ▼
     │                                    published
     └── permanent error / retries exhausted ──▶ failed
```

`published` is set in exactly one place: `publish_service.mark_published`,
reachable only from the verified-webhook path. An HTTP 200 from the publish
call means *accepted*, which is not the same fact as *delivered*, and the
schema refuses to conflate them.

One subtlety found during the live run: the platform can fire its delivery
webhook **before** the publish HTTP response comes back, so a post can already
be `published` when the publish call returns. `publish_post` therefore
re-reads the row and never downgrades `published` back to `publishing` — the
status machine only moves forward.

## 10. Webhook security

The signature is HMAC-SHA256 over the **raw request body bytes**, never over a
re-serialised dict — re-serialising would let a semantically-equal but
byte-different payload pass. Comparison uses `hmac.compare_digest`, which does
not short-circuit on the first differing byte and so leaks no timing
information about the expected digest.

An invalid, missing, or stale signature returns HTTP 400 and mutates nothing:
verification happens before the body is even parsed, let alone before any row
is touched. A verified redelivery is idempotent — a post already `published`
stays `published` with its original timestamp.

## 11. Token encryption

AES-256-GCM via `cryptography`'s `AESGCM`. A fresh 12-byte nonce is generated
for every single encryption; the nonce and ciphertext are stored in separate
columns and the plaintext is never written or logged. GCM is authenticated, so
a tampered ciphertext raises rather than silently decrypting to garbage.

Two tests guard the claim beyond the happy path: one reads the SQLite file as
raw bytes and asserts the plaintext token does not appear anywhere in it, and
another captures log output during a real authentication and asserts the bearer
token is absent.

## 12. Configuration robustness

`config.py` supplies working defaults for every variable, including the
security-critical ones, so the app never crashes on a missing env var. When a
dev fallback is used it logs a warning and reports `using_dev_secrets: true`
from `/health`, so an insecure deployment is visible rather than silent.

## 13. Non-goals

- **No real social APIs.** Everything targets the local mock platform.
- **No AI caption generation.** The hook exists; the default is deterministic
  templates. No paid inference is required to run or grade this project.
- **No multi-tenancy, users, or auth on the Social Studio API itself.** It is
  a single-tenant service; the OAuth in play is Social Studio → platform.
- **No object storage or CDN.** Images are files on local disk.
- **SQLite only.** The ORM would permit Postgres, but concurrency has only been
  designed and tested against SQLite.
- **No media beyond a single still image per platform** — no video, carousels,
  or alt-text generation.
- **No analytics or engagement metrics** after delivery.
