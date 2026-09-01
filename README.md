# Social Studio

Turn one blog post into platform-native social posts — correctly sized images,
platform-appropriate captions — and publish them to social platforms that time
out, rate limit you, and confirm delivery out of band, **without ever creating
a duplicate post**.

Everything runs locally against a mock platform server that deliberately
misbehaves. No real social APIs, no paid services, no API keys.

- **[docs/design.md](docs/design.md)** — architecture and the reasoning behind it
- **[EVIDENCE.md](EVIDENCE.md)** — real captured output for every claim below
- **[BUILDLOG.md](BUILDLOG.md)** — how it was built, including what broke

## Features

- **One campaign → many platforms.** Post a title, body and URL; get a
  1080×1080 Instagram image, a 1600×900 X image, and a caption tuned to each
  platform's limits and conventions.
- **Images that don't decapitate the subject.** Contain-and-pad against a
  blurred backdrop derived from the source, never a blind center-crop.
- **A real `SocialPublisher` abstraction.** Business logic never names a
  platform; a test enforces that.
- **Idempotent publishing.** One deterministic key per post, reused on every
  retry, enforced by a database `UNIQUE` constraint that survives concurrent
  duplicates.
- **Retries that behave.** `Retry-After` honoured exactly; exponential backoff
  for transport failures; permanent errors fail fast.
- **Durable scheduling.** APScheduler on a SQLite jobstore — jobs survive a
  process kill.
- **Encrypted tokens.** AES-256-GCM, fresh nonce per encryption, plaintext
  never written or logged.
- **Signed webhooks.** HMAC-SHA256 over the raw body, constant-time compare;
  a forged signature changes nothing.

## Architecture

```
   POST /campaigns ──▶ FastAPI :8000
                          │
              ┌───────────┴────────────┐
     campaign_service            publish_service
     ├ image_service (Pillow)    status machine
     └ caption_service           no platform ifs
              │                         │
        SQLite (ORM)          publisher_factory.get(platform)
        campaigns                       │
        social_posts             «SocialPublisher»
        platform_tokens          authenticate / publish / get_status
              ▲                    │              │
       APScheduler           Instagram         X adapter
       SQLAlchemy jobstore       └──── httpx + Idempotency-Key ────┐
                                                                   ▼
                                          Mock Platform :9000
                                          OAuth · UNIQUE(platform, key)
                                          429+Retry-After · dropped responses
                                                   │
                          HMAC-SHA256 signed delivery webhook
                                                   ▼
                          POST /webhook/social-delivery → status=published
```

## Status machine

```
queued ── publish() 2xx ──▶ publishing ── verified webhook ──▶ published
   └────── permanent error / retries exhausted ──────▶ failed
```

`published` is set **only** by an HMAC-verified webhook. An HTTP 200 from the
publish call means *accepted*, which is not the same fact as *delivered*.

## Requirements

Python 3.11+. Dependencies (all free, all local): FastAPI, uvicorn, SQLAlchemy,
APScheduler, Pillow, httpx, cryptography, pytest.

## Installation

```bash
git clone <this repo> && cd flyrank-capstone-social-studio
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env      # optional — sane defaults apply if you skip this
```

## Environment variables

Every variable has a working default; **the app never crashes on a missing
one**. When a security-critical default is used, it logs a warning and
`/health` reports `"using_dev_secrets": true`.

| Variable | Default | Purpose |
|----------|---------|---------|
| `ENCRYPTION_KEY` | insecure dev key | 32-byte AES-256-GCM key, base64 or hex |
| `WEBHOOK_SECRET` | `dev-webhook-secret-change-me` | HMAC secret shared with the platform |
| `MOCK_PLATFORM_URL` | `http://127.0.0.1:9000` | where the adapters publish |
| `APP_BASE_URL` | `http://127.0.0.1:8000` | where the platform sends webhooks |
| `DATABASE_URL` | `sqlite:///./data/social_studio.db` | application database |
| `SCHEDULER_DB_URL` | `sqlite:///./data/scheduler.db` | APScheduler jobstore |
| `ARTIFACTS_DIR` | `./artifacts` | rendered image output |
| `PUBLISH_TIMEOUT_SECONDS` | `5` | HTTP timeout per publish attempt |
| `PUBLISH_MAX_RETRIES` | `4` | attempts before marking `failed` |

Generate a real key:

```bash
python -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())"
```

## Running

Two servers, two terminals:

```bash
# terminal 1 — the mock social platform
.venv/bin/python -m uvicorn mock_platform.main:app --port 9000

# terminal 2 — Social Studio
.venv/bin/python -m uvicorn app.main:app --port 8000
```

Interactive API docs: <http://127.0.0.1:8000/docs> and
<http://127.0.0.1:9000/docs>.

## Seed a demo campaign

```bash
curl -X POST http://127.0.0.1:8000/campaigns \
  -H 'Content-Type: application/json' \
  -d '{"title":"Why idempotency keys beat retry counters",
       "body":"Every social API will eventually accept your post and then fail to tell you about it.",
       "url":"https://example.com/blog/idempotency-keys"}'
```

Then publish it (twice, to see idempotency hold):

```bash
curl -X POST http://127.0.0.1:8000/campaigns/<id>/publish
curl -X POST http://127.0.0.1:8000/campaigns/<id>/publish
curl http://127.0.0.1:9000/platform/instagram/posts   # count stays 1
```

## Running the tests

```bash
.venv/bin/python -m pytest -v
```

46 tests, all passing. The suite starts the mock platform on a real ephemeral
port in a background thread, so the adapters' actual HTTP path is under test.

## Full demonstration

```bash
./demo.sh
```

Starts both servers, walks the entire feature set — idempotency, 429 handling,
timeout recovery, forged and valid webhooks, durable scheduling, a process
kill, token encryption — and tears down. Its output is what
[EVIDENCE.md](EVIDENCE.md) is built from.

## API endpoints

### Social Studio (:8000)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | liveness, configured platforms, dev-secret warning |
| POST | `/campaigns` | create a campaign; renders images, writes captions, queues posts |
| GET | `/campaigns/{id}` | campaign with all its social posts |
| POST | `/campaigns/{id}/publish` | publish every post in the campaign now |
| POST | `/campaigns/{id}/schedule` | schedule a durable publish (`run_at` or `delay_seconds`) |
| GET | `/social-posts/{id}` | one social post's state |
| POST | `/webhook/social-delivery` | signed delivery callback (requires `X-Signature`) |
| GET | `/scheduler/jobs` | jobs currently in the persistent jobstore |

### Mock platform (:9000)

| Method | Path | Description |
|--------|------|-------------|
| POST | `/oauth/token` | issue a bearer token |
| POST | `/platform/{p}/publish` | publish; requires `Authorization` + `Idempotency-Key` |
| GET | `/platform/{p}/posts` | everything the platform has stored |
| POST | `/platform/{p}/reset` | wipe posts and simulation state |
| POST | `/platform/{p}/rate-limit` | arm N × 429 with a given `Retry-After` |
| POST | `/platform/{p}/simulate-timeout` | create the post, then drop/delay the response |
| POST | `/platform/{p}/webhook-delay` | hold delivery callbacks back (demo determinism) |
| GET | `/platform/{p}/state` | current simulation state |

## Reliability design

**Idempotency.** Each `social_posts` row gets one key at creation, derived from
its own UUID, stored on the row and reused on every attempt — never
regenerated. The platform enforces `UNIQUE(platform, idempotency_key)` with a
try-insert/catch-`IntegrityError`/read-back pattern, so six concurrent
duplicate publishes all receive the same post id.

**Retries.** 429 → sleep exactly `Retry-After`. Timeout or 5xx → exponential
backoff. 401 → re-authenticate once. Other 4xx → permanent failure, no retry.
Retries exhausted → `failed`, with the reason recorded.

**The lost response.** The mock creates the post *before* dropping the
response, because that is what really happens. The retry carries the same key
and resolves to the same post — verified end to end in EVIDENCE.md §7.

**Crash safety.** APScheduler persists jobs to SQLite and stores the target as
an import path, so jobs survive a restart. `misfire_grace_time` means a job
whose moment passed during downtime still runs. Re-running a scheduled publish
is harmless because idempotency, not bookkeeping, is what makes it safe.

## Security

**Tokens.** AES-256-GCM with a fresh 12-byte nonce per encryption. Ciphertext
and nonce stored in separate columns; no plaintext column exists. Tests assert
the plaintext appears neither in the SQLite file's raw bytes nor in captured
log output.

**Webhooks.** HMAC-SHA256 over the raw request body — never a re-serialised
dict — compared with `hmac.compare_digest`. Verification happens before the
body is parsed, so a forged, missing, or stale signature returns 400 having
touched nothing.

**Config.** Dev fallbacks keep the app running but announce themselves in the
logs and at `/health`, so an insecure deployment is loud rather than silent.

## Limitations and non-goals

- No real social APIs — everything targets the local mock, by design.
- No AI caption generation. The hook exists
  (`caption_service.set_ai_rewriter`); the default is deterministic templates,
  so nothing here needs a paid model.
- Single-tenant: no users or auth on the Social Studio API itself.
- Images are local files; no object storage or CDN.
- SQLite only. The ORM would permit Postgres, but only SQLite was tested.
- One still image per platform — no video, carousels, or alt-text generation.
- No post-delivery analytics.

Verification caveats are listed honestly in
[EVIDENCE.md § Known gaps](EVIDENCE.md#known-gaps-and-honest-caveats).

## 6-minute demo script

1. **(0:00) The problem.** Social platforms accept your post and then fail to
   tell you. A retry counter guesses; an idempotency key knows. Show
   `docs/design.md`'s architecture diagram.
2. **(0:45) Start both servers**, `curl /health` on each. Point out
   `"using_dev_secrets"` — config that can't crash but can't hide either.
3. **(1:15) Create a campaign.** Show the response: two queued posts, two
   captions from one shared voice, two image paths. Open both PNGs — 1080×1080
   and 1600×900 from one source, subject fully intact.
4. **(2:15) Publish twice.** Same `external_post_id` both times;
   `/platform/instagram/posts` count stays at 1. Show the stored
   `idempotency_key` on the row — assigned once, never regenerated.
5. **(3:00) Break the platform on purpose.** Arm a 429 with `Retry-After: 2`,
   publish, show 2.04s elapsed and one post. Then arm `simulate-timeout`, and
   show the log: `timed out` → retry → `replayed=True` → still one post.
6. **(4:15) Attack the webhook.** Forged signature → 400, status stays
   `publishing`. Correct signature → 200, status `published`. Emphasise that
   the publish HTTP 200 never set `published` — only the verified webhook did.
7. **(5:15) Kill the process.** Schedule a campaign, show the row in
   `apscheduler_jobs`, `kill` the app, restart it, `GET /scheduler/jobs` —
   same job, same run time.
8. **(5:45) Close on architecture.** `grep` the service layer for
   `platform ==` and find nothing; show `test_adding_a_platform_needs_only_an_adapter`
   registering a third platform in five lines. Finish with `pytest -v`: 46
   passing.

## License

MIT — see [LICENSE](LICENSE).
