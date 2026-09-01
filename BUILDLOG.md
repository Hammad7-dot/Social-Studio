# Build log

## Disclosure

This project was built with AI assistance. The implementation was written by
Claude (Anthropic) working from a detailed capstone brief, in one continuous
build session. Every command shown in EVIDENCE.md was actually executed and its
output captured verbatim — nothing there was written by hand to look like
output. Where a claim is only partially verified, EVIDENCE.md says so explicitly
rather than glossing over it.

This log describes what was actually built and what actually broke. It is not a
reconstruction of an idealised process.

---

## Session — single continuous build

### 1. Scaffold and configuration

Directory tree, `requirements.txt` with loose version pins, MIT `LICENSE`,
`.gitignore` (excluding `.venv`, `data/*.db`, generated `artifacts/**/*.png`,
but keeping `.gitkeep` placeholders), and `.env.example`.

The brief required that the app never crash on a missing env var.
`app/config.py` therefore supplies a working default for everything, including
`ENCRYPTION_KEY` and `WEBHOOK_SECRET`. To keep that from becoming a silent
security hole, using a dev fallback sets `using_dev_secrets`, logs a warning at
startup, and is reported by `/health`. `_decode_key` accepts base64 or hex and
falls back to deriving 32 bytes from the raw string, so even a malformed key
yields a running (if warned-about) service.

### 2. Design document

Written before the implementation, and it did real work: the "contain + blurred
backdrop" image strategy and the decision that `published` may only be set by a
verified webhook were both settled on paper first, and the code follows the
document rather than the document being written afterwards to match the code.

### 3. Data layer

Three models. The one design decision worth recording is that
`social_posts.idempotency_key` is a **stored column with a UNIQUE constraint
alongside platform**, not a value computed at publish time. Computing it per
attempt is the classic way to build something that looks idempotent and isn't.

`PostStatus` was made an explicit class with a docstring naming each transition,
so the status machine is documented where it is used rather than only in prose.

### 4. Images and captions

Pillow. The naive implementation is a center-crop, which slices ~44% off a 16:9
hero to make a square and regularly cuts off heads. Implemented contain-and-pad
instead, with the padding filled by a cover-scaled Gaussian-blurred copy of the
source so the frame is still filled edge to edge. `test_contain_preserves_whole_subject`
feeds in a 1:3 source and asserts the subject survives in the square variant.

Captions are deterministic templates. The body summary budget is computed as
`platform_limit - len(title) - len(tags) - len(url)`, so captions fit by
construction rather than being generated and then blindly truncated. An
optional `set_ai_rewriter` hook exists as a post-processor, deliberately not as
a dependency — nothing needs a paid model to run.

### 5. Mock platform

Backed by a real SQLite file, not a dict, specifically so
`UNIQUE(platform, idempotency_key)` is enforced by the database. The insert
path is try-INSERT / catch `IntegrityError` / read back the winning row, which
is what makes concurrent duplicates collapse rather than race.

The important ordering detail: on a `simulate-timeout`, the post is created
**first** and only then is the response held. That is what a real platform does,
and it is the only version of the simulation that actually tests anything.

### 6. Adapters

`SocialPublisher` is the abstract contract. All the retry, rate-limit, and
authentication logic lives once in `HttpMockPublisher`; `FakeInstagramPublisher`
and `FakeXPublisher` are four lines each, setting only `platform` and
`image_spec`. `factory.py` is the single place in the codebase that maps a
platform string to a class.

To keep that honest rather than aspirational, `tests/test_architecture.py`
greps the service layer for `platform == "instagram"`-shaped branching and
fails if any appears, and separately registers a third platform at runtime to
prove the extensibility claim.

### 7. Security

AES-256-GCM with `os.urandom(12)` per encryption. The tests go past the happy
path: one reads the SQLite file as raw bytes and asserts the plaintext token
does not appear anywhere in it, another captures log records during a real
authentication and asserts the bearer token never leaks.

Webhook verification signs the **raw body bytes**. Signing a re-serialised dict
would let a semantically-equal but byte-different payload through, so
`app/api/webhooks.py` reads `await request.body()` and verifies before it even
parses the JSON.

---

## Problems hit, and how they were fixed

### Problem 1 — `ASGITransport` cannot be used with a synchronous httpx client

**Symptom.** The first test run was 16 failed / 30 passed / 16 errors, all with
`AttributeError: 'ASGITransport' object has no attribute 'close'` and transport
failures underneath.

**Cause.** The first `conftest.py` wired the adapters to the mock platform via
`httpx.ASGITransport` to avoid running a server. But the adapters use
`httpx.Client` (synchronous, because `publish_service` and the APScheduler job
target are synchronous), and `ASGITransport` is async-only.

**Fix.** Stopped faking the transport. `conftest.py` now starts the mock
platform on a real uvicorn server, on an ephemeral port, in a background thread
for the test session. This is slower (~35s for the suite) but it exercises the
adapters' genuine synchronous HTTP path — real headers, real status codes, real
`Retry-After`, real client timeouts — which is precisely what the resilience
tests are supposed to be proving. Faking the transport would have made the
timeout and 429 tests test the fake.

### Problem 2 — a genuine race, found by the live demo and not by the tests

**Symptom.** The first full `./demo.sh` run showed a post with
`"status": "publishing"` and a populated `"published_at"` — an impossible
combination.

**Cause.** A real bug. The mock platform creates the post, fires the delivery
webhook, and *then* answers the publish call. When the webhook is fast (or the
publish response is held by a timeout simulation), the webhook sets
`published`, and then `publish_post` — holding a row it loaded before the
publish call — writes `publishing` straight over the top of it. The status
machine was moving backwards.

**Fix.** `publish_post` now calls `db.refresh(post)` after the publish returns
and only sets `publishing` when the row is not already `published`. The status
machine only moves forward. This is documented in `docs/design.md` §9 and
called out in EVIDENCE.md, because it is a real defect that a live end-to-end
run caught and a green test suite did not — which is exactly the argument for
requiring evidence rather than assertions.

### Problem 3 — the forged-webhook demo was racing the real webhook

**Symptom.** The "forged signature leaves status unchanged" step was
non-deterministic: by the time the forgery was attempted, the platform's own
legitimate signed webhook had sometimes already promoted the post to
`published`, so "unchanged" proved nothing.

**Fix.** Added `POST /platform/{p}/webhook-delay` to the mock so delivery
callbacks can be held back for a demo. The demo now holds X's callbacks for 600
seconds before the forgery steps, guaranteeing the post is sitting in
`publishing` when the forged request arrives — so "status unchanged" is a real
assertion. The automatic round trip is still demonstrated separately, at normal
delay, in section 5.

### Problem 4 — an f-string with a backslash inside a shell heredoc

**Symptom.** Demo step 5 printed
`SyntaxError: f-string expression part cannot include a backslash`.

**Cause.** A `python -c` one-liner inside single quotes needed escaped double
quotes inside an f-string expression, which Python 3.11 rejects.

**Fix.** Replaced the one-liner with a proper heredoc using `.format()`. Minor,
but it is in this log because it was a real failure in a real run.

### Problem 5 — Pydantic v2 deprecation noise

Class-based `Config` emitted `PydanticDeprecatedSince20` on every run. Switched
to `ConfigDict(from_attributes=True)` and added a `pytest.ini` filtering the
remaining third-party deprecation warnings, so the test output is readable
enough to be worth pasting into EVIDENCE.md.

---

## Final state

- 46 tests, all passing (`screenshots/pytest_output.txt`).
- Full live demo across both servers, all twelve sections succeeding
  (`screenshots/demo_output.txt`).
- One real bug found and fixed by the evidence process (Problem 2).
- Known verification gaps documented honestly in EVIDENCE.md rather than
  papered over — most notably that the pytest suite does not exercise the mock
  platform's *outbound* webhook, which is proven live instead.
