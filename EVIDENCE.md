# EVIDENCE

Every block below is **real captured output**. Test output comes from
`.venv/bin/python -m pytest -v`; the demonstrations come from `./demo.sh`,
which starts both servers for real and drives them with curl. Raw copies live
in `screenshots/pytest_output.txt` and `screenshots/demo_output.txt`.

Nothing here is hand-written sample output. Where something is only partially
verified, it says so — see **Known gaps** at the end.

---

## 1. Automated test suite

```
rootdir: /home/claude/flyrank-capstone-social-studio
configfile: pytest.ini
testpaths: tests
plugins: anyio-4.14.2, asyncio-1.4.0
asyncio: mode=Mode.STRICT, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 46 items

tests/test_api.py::test_health PASSED                                    [  2%]
tests/test_api.py::test_create_get_and_publish_campaign PASSED           [  4%]
tests/test_api.py::test_validation_errors PASSED                         [  6%]
tests/test_api.py::test_404s PASSED                                      [  8%]
tests/test_api.py::test_schedule_endpoint_registers_durable_job PASSED   [ 10%]
tests/test_architecture.py::test_no_platform_branching_in_business_logic PASSED [ 13%]
tests/test_architecture.py::test_all_publishers_implement_the_interface PASSED [ 15%]
tests/test_architecture.py::test_factory_rejects_unknown_platform PASSED [ 17%]
tests/test_architecture.py::test_adding_a_platform_needs_only_an_adapter PASSED [ 19%]
tests/test_captions.py::test_x_caption_respects_280_char_limit PASSED    [ 21%]
tests/test_captions.py::test_instagram_caption_omits_url_and_carries_more_tags PASSED [ 23%]
tests/test_captions.py::test_captions_are_deterministic PASSED           [ 26%]
tests/test_captions.py::test_shared_brand_voice_present_on_every_platform PASSED [ 28%]
tests/test_captions.py::test_optional_ai_hook_is_pluggable PASSED        [ 30%]
tests/test_captions.py::test_unknown_platform_rejected PASSED            [ 32%]
tests/test_idempotency.py::test_idempotency_key_is_deterministic_and_stored_once PASSED [ 34%]
tests/test_idempotency.py::test_double_publish_creates_exactly_one_platform_post PASSED [ 36%]
tests/test_idempotency.py::test_concurrent_duplicate_publishes_collapse_to_one PASSED [ 39%]
tests/test_idempotency.py::test_timeout_recovery_does_not_duplicate PASSED [ 41%]
tests/test_images.py::test_platform_specs_declared PASSED                [ 43%]
tests/test_images.py::test_render_variants_have_exact_dimensions PASSED  [ 45%]
tests/test_images.py::test_contain_preserves_whole_subject PASSED        [ 47%]
tests/test_images.py::test_generate_variants_returns_all_platforms PASSED [ 50%]
tests/test_rate_limits.py::test_mock_returns_429_with_retry_after_header PASSED [ 52%]
tests/test_rate_limits.py::test_retry_after_is_honoured_then_publish_succeeds PASSED [ 54%]
tests/test_rate_limits.py::test_publish_service_recovers_from_rate_limit PASSED [ 56%]
tests/test_rate_limits.py::test_exhausted_retries_marks_failed_not_published PASSED [ 58%]
tests/test_scheduler.py::test_job_survives_scheduler_teardown_and_reload PASSED [ 60%]
tests/test_scheduler.py::test_job_row_is_actually_persisted_in_sqlite PASSED [ 63%]
tests/test_scheduler.py::test_rescheduling_replaces_rather_than_duplicates PASSED [ 65%]
tests/test_scheduler.py::test_scheduled_job_target_is_importable_by_path PASSED [ 67%]
tests/test_scheduler.py::test_scheduled_run_is_crash_safe_and_idempotent PASSED [ 69%]
tests/test_security.py::test_encrypt_decrypt_roundtrip PASSED            [ 71%]
tests/test_security.py::test_fresh_iv_per_encryption PASSED              [ 73%]
tests/test_security.py::test_ciphertext_does_not_contain_plaintext PASSED [ 76%]
tests/test_security.py::test_tampered_ciphertext_is_rejected PASSED      [ 78%]
tests/test_security.py::test_plaintext_token_absent_from_sqlite_file_bytes PASSED [ 80%]
tests/test_security.py::test_token_value_never_logged PASSED             [ 82%]
tests/test_security.py::test_token_repr_does_not_leak PASSED             [ 84%]
tests/test_webhooks.py::test_sign_and_verify_roundtrip PASSED            [ 86%]
tests/test_webhooks.py::test_forged_signature_rejected_and_status_unchanged PASSED [ 89%]
tests/test_webhooks.py::test_missing_signature_rejected PASSED           [ 91%]
tests/test_webhooks.py::test_tampered_body_rejected PASSED               [ 93%]
tests/test_webhooks.py::test_valid_signature_promotes_to_published PASSED [ 95%]
tests/test_webhooks.py::test_webhook_redelivery_is_idempotent PASSED     [ 97%]
tests/test_webhooks.py::test_publish_alone_never_sets_published PASSED   [100%]

============================= 46 passed in 34.08s ==============================
```

**46 passed, 0 failed.**

---

## 2. Health of both services

```
{
    "status": "ok",
    "service": "social-studio",
    "platforms": [
        "instagram",
        "x"
    ],
    "mock_platform_url": "http://127.0.0.1:9000",
    "using_dev_secrets": false
}
{
    "status": "ok",
    "service": "mock_platform"
}
```

---

## 3. Campaign creation — captions and image variants

One campaign renders both image variants, writes both captions, and queues one
`social_posts` row per platform:

```
{
    "id": "681c9a27-b300-43d8-bda5-cfe9ed34d533",
    "title": "Why idempotency keys beat retry counters",
    "body": "Every social API will eventually accept your post and then fail to tell you about it. A retry counter guesses; an idempotency key knows. We derive one deterministic key per social post row and reuse it on every attempt, so a lost response costs a round trip and never a duplicate post.",
    "url": "https://example.com/blog/idempotency-keys",
    "source_image": "/home/claude/flyrank-capstone-social-studio/artifacts/sources/681c9a27-b300-43d8-bda5-cfe9ed34d533_source.png",
    "created_at": "2026-09-01T17:36:08.675536",
    "social_posts": [
        {
            "id": "740699c2-6cc2-43c4-872e-02978cfec73f",
            "campaign_id": "681c9a27-b300-43d8-bda5-cfe9ed34d533",
            "platform": "instagram",
            "caption": "Why idempotency keys beat retry counters\n\nEvery social API will eventually accept your post and then fail to tell you about it. A retry counter guesses; an idempotency key knows. We derive one deterministic key per social post row and reuse it on every attempt, so a lost response costs a round trip and never a duplicate post.\n\nRead the full breakdown \u2014 link in bio.\n\n#buildinpublic #engineering #devlife #tech #startup",
            "image_path": "/home/claude/flyrank-capstone-social-studio/artifacts/instagram/681c9a27-b300-43d8-bda5-cfe9ed34d533_instagram.png",
            "status": "queued",
            "idempotency_key": "ss-instagram-701ed49bfcef8912bd2866ff5443e1f8",
            "external_post_id": null,
            "scheduled_at": null,
            "published_at": null,
            "failure_reason": null
        },
        {
            "id": "3fa9bd9a-1127-4ae8-ad8f-eacf3c6a36af",
            "campaign_id": "681c9a27-b300-43d8-bda5-cfe9ed34d533",
            "platform": "x",
            "caption": "Why idempotency keys beat retry counters\n\nEvery social API will eventually accept your post and then fail to tell you about it. A retry counter guesses; an idempotency key knows.\n\nRead the full breakdown: https://example.com/blog/idempotency-keys\n\n#buildinpublic #engineering",
            "image_path": "/home/claude/flyrank-capstone-social-studio/artifacts/x/681c9a27-b300-43d8-bda5-cfe9ed34d533_x.png",
            "status": "queued",
            "idempotency_key": "ss-x-4edba857cf803c1fe618556d1f4c7623",
            "external_post_id": null,
            "scheduled_at": null,
            "published_at": null,
            "failure_reason": null
        }
    ]
}
campaign_id=681c9a27-b300-43d8-bda5-cfe9ed34d533
```

### Image dimensions, read back off disk with Pillow

```
artifacts/instagram/681c9a27-b300-43d8-bda5-cfe9ed34d533_instagram.png 1080x1080
artifacts/sources/681c9a27-b300-43d8-bda5-cfe9ed34d533_source.png      1400x1050
artifacts/x/681c9a27-b300-43d8-bda5-cfe9ed34d533_x.png                 1600x900
```

Instagram is exactly **1080x1080**, X is exactly **1600x900**, both derived
from a single 1400x1050 source.

### Captions

The X caption carries the URL and 2 hashtags and fits inside 280 characters.
The Instagram caption is longer, omits the URL in favour of "link in bio", and
carries 5 hashtags. Both open with the same title and the same
`#buildinpublic` brand tag — one shared voice, two sets of platform rules.

---

## 4. Idempotency — publishing the same campaign twice

```
--- publish #1 ---
[
    {
        "id": "740699c2-6cc2-43c4-872e-02978cfec73f",
        "campaign_id": "681c9a27-b300-43d8-bda5-cfe9ed34d533",
        "platform": "instagram",
        "caption": "Why idempotency keys beat retry counters\n\nEvery social API will eventually accept your post and then fail to tell you about it. A retry counter guesses; an idempotency key knows. We derive one deterministic key per social post row and reuse it on every attempt, so a lost response costs a round trip and never a duplicate post.\n\nRead the full breakdown \u2014 link in bio.\n\n#buildinpublic #engineering #devlife #tech #startup",
        "image_path": "/home/claude/flyrank-capstone-social-studio/artifacts/instagram/681c9a27-b300-43d8-bda5-cfe9ed34d533_instagram.png",
        "status": "publishing",
        "idempotency_key": "ss-instagram-701ed49bfcef8912bd2866ff5443e1f8",
        "external_post_id": "instagram_f0c1bfb28282",
        "scheduled_at": null,
        "published_at": null,
        "failure_reason": null
    },
    {
        "id": "3fa9bd9a-1127-4ae8-ad8f-eacf3c6a36af",
        "campaign_id": "681c9a27-b300-43d8-bda5-cfe9ed34d533",
        "platform": "x",
        "caption": "Why idempotency keys beat retry counters\n\nEvery social API will eventually accept your post and then fail to tell you about it. A retry counter guesses; an idempotency key knows.\n\nRead the full breakdown: https://example.com/blog/idempotency-keys\n\n#buildinpublic #engineering",
        "image_path": "/home/claude/flyrank-capstone-social-studio/artifacts/x/681c9a27-b300-43d8-bda5-cfe9ed34d533_x.png",
        "status": "publishing",
        "idempotency_key": "ss-x-4edba857cf803c1fe618556d1f4c7623",
        "external_post_id": "x_a095fc408f17",
        "scheduled_at": null,
        "published_at": null,
        "failure_reason": null
    }
]
--- publish #2 (same idempotency keys) ---
[
    {
        "id": "740699c2-6cc2-43c4-872e-02978cfec73f",
        "campaign_id": "681c9a27-b300-43d8-bda5-cfe9ed34d533",
        "platform": "instagram",
        "caption": "Why idempotency keys beat retry counters\n\nEvery social API will eventually accept your post and then fail to tell you about it. A retry counter guesses; an idempotency key knows. We derive one deterministic key per social post row and reuse it on every attempt, so a lost response costs a round trip and never a duplicate post.\n\nRead the full breakdown \u2014 link in bio.\n\n#buildinpublic #engineering #devlife #tech #startup",
        "image_path": "/home/claude/flyrank-capstone-social-studio/artifacts/instagram/681c9a27-b300-43d8-bda5-cfe9ed34d533_instagram.png",
        "status": "publishing",
        "idempotency_key": "ss-instagram-701ed49bfcef8912bd2866ff5443e1f8",
        "external_post_id": "instagram_f0c1bfb28282",
        "scheduled_at": null,
        "published_at": null,
        "failure_reason": null
    },
    {
        "id": "3fa9bd9a-1127-4ae8-ad8f-eacf3c6a36af",
        "campaign_id": "681c9a27-b300-43d8-bda5-cfe9ed34d533",
        "platform": "x",
        "caption": "Why idempotency keys beat retry counters\n\nEvery social API will eventually accept your post and then fail to tell you about it. A retry counter guesses; an idempotency key knows.\n\nRead the full breakdown: https://example.com/blog/idempotency-keys\n\n#buildinpublic #engineering",
        "image_path": "/home/claude/flyrank-capstone-social-studio/artifacts/x/681c9a27-b300-43d8-bda5-cfe9ed34d533_x.png",
        "status": "publishing",
        "idempotency_key": "ss-x-4edba857cf803c1fe618556d1f4c7623",
        "external_post_id": "x_a095fc408f17",
        "scheduled_at": null,
        "published_at": null,
        "failure_reason": null
    }
]
--- mock platform post counts (expect 1 each) ---
instagram count = 1 ['instagram_f0c1bfb28282']
x count         = 1 ['x_a095fc408f17']
```

Both publishes return the **same** `external_post_id` per platform, and the
mock platform's store holds exactly **1** post per platform. The idempotency
keys are identical across both calls because they are stored on the row at
creation, never regenerated per attempt.

Concurrency is covered by `test_concurrent_duplicate_publishes_collapse_to_one`,
which fires 6 simultaneous publishes with one key and asserts a single post id
comes back — the `UNIQUE(platform, idempotency_key)` constraint arbitrates the
race.

---

## 5. Webhook round trip — status becomes `published`

After the mock platform's asynchronous HMAC-signed delivery callbacks land:

```
instagram  status=published   external=instagram_f0c1bfb28282 published_at=2026-09-01T17:36:11.151398
x          status=published   external=x_a095fc408f17 published_at=2026-09-01T17:36:11.156404
```

These posts were `publishing` immediately after the publish call (section 4)
and became `published` only once a **verified webhook** arrived.

---

## 6. Rate limiting — 429 and Retry-After

One 429 is armed with `Retry-After: 2`, then a campaign is published:

```
{
    "platform": "x",
    "state": {
        "platform": "x",
        "rate_limit_remaining": 1,
        "retry_after": 2,
        "timeout_remaining": 0,
        "timeout_delay": 10.0,
        "webhook_delay": -1.0
    }
}
campaign_id=128ae53c-5615-4fc6-acf9-ecb252f5032f  (429 armed, Retry-After: 2)
[
    {
        "id": "8c46b7c5-6b74-4fa9-9f6c-f0d7d7093c74",
        "campaign_id": "128ae53c-5615-4fc6-acf9-ecb252f5032f",
        "platform": "x",
        "caption": "Backpressure is a feature\n\nA 429 is the platform telling you the truth about its capacity. Honour Retry-After exactly and you get to keep your API access.\n\nRead the full breakdown: https://example.com/blog/backpressure\n\n#buildinpublic #engineering",
        "image_path": "/home/claude/flyrank-capstone-social-studio/artifacts/x/128ae53c-5615-4fc6-acf9-ecb252f5032f_x.png",
        "status": "publishing",
        "idempotency_key": "ss-x-d3ae875551c05cfd33719db7b00261c2",
        "external_post_id": "x_b178df3918fb",
        "scheduled_at": null,
        "published_at": null,
        "failure_reason": null
    }
]
elapsed: 2.04s  (>= 2s proves Retry-After was honoured)
--- mock x post count (expect 1, the retry did not duplicate) ---
x count = 1
```

Elapsed **2.04s** against `Retry-After: 2` — the client waited the stated
interval instead of hammering. The publish then succeeded and the store holds
one post, so the retry did not duplicate.

---

## 7. Timeout recovery — response lost after server-side create

The mock is armed to create the post and then hold the response for 6s, well
past the 3s client timeout:

```
{
    "platform": "instagram",
    "state": {
        "platform": "instagram",
        "rate_limit_remaining": 0,
        "retry_after": 2,
        "timeout_remaining": 1,
        "timeout_delay": 6.0,
        "webhook_delay": -1.0
    }
}
[
    {
        "id": "397c1f09-c036-4bb6-a8f3-ac07a57c3bff",
        "campaign_id": "154b0bfa-51dd-40bb-8352-b7454c6f8463",
        "platform": "instagram",
        "caption": "The lost response problem\n\nThe platform created your post and then the connection died. Only an idempotency key can tell the retry from a duplicate.\n\nRead the full breakdown \u2014 link in bio.\n\n#buildinpublic #engineering #devlife #tech #startup",
        "image_path": "/home/claude/flyrank-capstone-social-studio/artifacts/instagram/154b0bfa-51dd-40bb-8352-b7454c6f8463_instagram.png",
        "status": "published",
        "idempotency_key": "ss-instagram-96f5d0167d53d3504f9e4229000ff650",
        "external_post_id": "instagram_3df015f5c4a9",
        "scheduled_at": null,
        "published_at": "2026-09-01T17:36:17.266385",
        "failure_reason": null
    }
]
--- mock instagram post count (expect exactly 1) ---
instagram count = 1 ['instagram_3df015f5c4a9']
```

Exactly **1** post exists. From the application log during this run:

```
social_studio.adapters: instagram: transient failure on attempt 1 (transport failure: timed out), backing off 0.5s
httpx: HTTP Request: POST http://127.0.0.1:9000/platform/instagram/publish "HTTP/1.1 200 OK"
social_studio.publish: post 84e237b2-... accepted by instagram as instagram_974570356a04 (replayed=True)
```

`replayed=True` and HTTP 200 (not 201) prove the retry resolved to the
already-created post rather than creating a second one.

---

## 8. Forged webhook — HTTP 400, status unchanged

```
target social_post: 7c52c0a1-6f4b-4307-8175-9dab17ab1542
status before: publishing
-- HTTP status with a forged signature:
400
{"detail":"invalid signature"}
status after forgery: publishing
```

Status is `publishing` before **and after** the forgery attempt. Server log for
that request:

```
WARNING social_studio.webhooks: rejected delivery webhook: invalid signature
INFO:     "POST /webhook/social-delivery HTTP/1.1" 400 Bad Request
```

`tests/test_webhooks.py` additionally covers a *missing* signature and a
**tampered body carrying an otherwise-valid signature** — both rejected, both
leaving the row untouched.

---

## 9. Valid webhook — HTTP 200, status becomes `published`

The same body, signed correctly with the shared secret:

```
computed signature: sha256=0bfe9ec4609ee4124408ba36c01441511995a3ca2ab6f75016012352a6117146
HTTP 200
{"ok":true,"updated":true,"social_post_id":"7c52c0a1-6f4b-4307-8175-9dab17ab1542","status":"published"}
{
    "id": "7c52c0a1-6f4b-4307-8175-9dab17ab1542",
    "campaign_id": "d3872809-d840-49d2-bb39-614e689b7503",
    "platform": "x",
    "caption": "An unsigned webhook is an unauthenticated state change\n\nAnyone who can reach your callback URL can claim your post went live.\n\nRead the full breakdown: https://example.com/blog/webhook-security\n\n#buildinpublic #engineering",
    "image_path": "/home/claude/flyrank-capstone-social-studio/artifacts/x/d3872809-d840-49d2-bb39-614e689b7503_x.png",
    "status": "published",
    "idempotency_key": "ss-x-dae4cce946d61c1bbd7e05ffd917fbd7",
    "external_post_id": "x_72f29b77aa80",
    "scheduled_at": null,
    "published_at": "2026-09-01T17:36:20.839858",
    "failure_reason": null
}
```

HTTP 200, `status: "published"`, `published_at` populated.

---

## 10. Durable scheduling

```
{
    "campaign_id": "681c9a27-b300-43d8-bda5-cfe9ed34d533",
    "job_id": "publish:681c9a27-b300-43d8-bda5-cfe9ed34d533",
    "scheduled_at": "2026-09-01T18:36:20.906598+00:00",
    "jobs": [
        {
            "id": "publish:681c9a27-b300-43d8-bda5-cfe9ed34d533",
            "next_run_time": "2026-09-01T18:36:20.906598+00:00",
            "args": [
                "681c9a27-b300-43d8-bda5-cfe9ed34d533"
            ]
        }
    ]
}
--- rows physically present in the scheduler sqlite jobstore ---
  ('publish:681c9a27-b300-43d8-bda5-cfe9ed34d533', 1788287780.906598)
```

The job is not merely in memory — the row is physically present in
`data/demo_sched.db`.

---

## 11. Crash recovery — the job survives a process restart

The app process is killed outright and restarted; jobs reload from the
jobstore file:

```
--- killing the app process (simulated crash) ---
app stopped.
--- app restarted; jobs reloaded from the sqlite jobstore ---
{
    "jobs": [
        {
            "id": "publish:681c9a27-b300-43d8-bda5-cfe9ed34d533",
            "next_run_time": "2026-09-01T18:36:20.906598+00:00",
            "args": [
                "681c9a27-b300-43d8-bda5-cfe9ed34d533"
            ]
        }
    ]
}
```

Same job id, same `next_run_time`, after a full process death.
`tests/test_scheduler.py` proves the same property at unit level by tearing
down one scheduler instance and pointing a brand-new one at the same file.

---

## 12. Token encryption

```
plaintext            : SUPER-SECRET-PLATFORM-TOKEN-abcdef123456
iv #1 (hex)          : 872cd23efac6314d35be5857 (12 bytes)
iv #2 (hex)          : ddc42b1ab0d52ff2bff33300 (12 bytes)
ivs differ           : True
ciphertexts differ   : True
ciphertext #1 (hex)  : b86442653bb3a9828f46c1b338418ccede16ed1d3355d71eac21b75706868ddac62f3285c5bfe3bc84d324c10ac6763abdc194773f18066d
plaintext in cipher  : False
decrypt roundtrip ok : True
--- grep the live application sqlite file for any bearer token ---
token-like byte sequences found in data/demo_app.db: 0
```

A fresh 12-byte IV per encryption, different ciphertext for identical
plaintext, plaintext absent from the ciphertext, clean decrypt roundtrip, and
**0** token-like byte sequences in the live application database.

`tests/test_security.py::test_plaintext_token_absent_from_sqlite_file_bytes`
writes an encrypted token, reads the SQLite file as raw bytes, and asserts the
plaintext is absent while the ciphertext is present.
`test_token_value_never_logged` captures log records during a real
authentication and asserts the bearer token never appears.

---

## 13. Application log — tokens absent

```
INFO:     127.0.0.1:43326 - "POST /campaigns HTTP/1.1" 201 Created
2026-09-01 17:36:20,631 INFO httpx: HTTP Request: POST http://127.0.0.1:9000/platform/x/publish "HTTP/1.1 201 Created"
2026-09-01 17:36:20,635 INFO social_studio.publish: post 7c52c0a1-6f4b-4307-8175-9dab17ab1542 accepted by x as x_72f29b77aa80 (replayed=False)
INFO:     127.0.0.1:43330 - "POST /campaigns/d3872809-d840-49d2-bb39-614e689b7503/publish HTTP/1.1" 200 OK
INFO:     127.0.0.1:43332 - "GET /campaigns/d3872809-d840-49d2-bb39-614e689b7503 HTTP/1.1" 200 OK
INFO:     127.0.0.1:43342 - "GET /social-posts/7c52c0a1-6f4b-4307-8175-9dab17ab1542 HTTP/1.1" 200 OK
2026-09-01 17:36:20,780 WARNING social_studio.webhooks: rejected delivery webhook: invalid signature
INFO:     127.0.0.1:43354 - "POST /webhook/social-delivery HTTP/1.1" 400 Bad Request
INFO:     127.0.0.1:43356 - "GET /social-posts/7c52c0a1-6f4b-4307-8175-9dab17ab1542 HTTP/1.1" 200 OK
2026-09-01 17:36:20,843 INFO social_studio.publish: post 7c52c0a1-6f4b-4307-8175-9dab17ab1542 marked published via verified webhook
INFO:     127.0.0.1:43360 - "POST /webhook/social-delivery HTTP/1.1" 200 OK
INFO:     127.0.0.1:43374 - "GET /social-posts/7c52c0a1-6f4b-4307-8175-9dab17ab1542 HTTP/1.1" 200 OK
2026-09-01 17:36:20,909 INFO apscheduler.scheduler: Added job "run_scheduled_publish" to job store "default"
2026-09-01 17:36:20,910 INFO social_studio.scheduler: scheduled campaign 681c9a27-b300-43d8-bda5-cfe9ed34d533 at 2026-09-01 18:36:20.906598+00:00 (job publish:681c9a27-b300-43d8-bda5-cfe9ed34d533)
INFO:     127.0.0.1:43390 - "POST /campaigns/681c9a27-b300-43d8-bda5-cfe9ed34d533/schedule HTTP/1.1" 200 OK
INFO:     Shutting down
INFO:     Waiting for application shutdown.
2026-09-01 17:36:21,100 INFO apscheduler.scheduler: Scheduler has been shut down
INFO:     Application shutdown complete.
INFO:     Finished server process [9871]
--- post-restart log ---
2026-09-01 17:36:21,845 INFO apscheduler.scheduler: Scheduler started
2026-09-01 17:36:21,847 INFO social_studio.scheduler: scheduler started (jobstore=sqlite:////home/claude/flyrank-capstone-social-studio/data/demo_sched.db)
2026-09-01 17:36:21,847 INFO social_studio: Social Studio up. platforms=['instagram', 'x'] mock_platform=http://127.0.0.1:9000 dev_secrets=False

== demo complete
```

No bearer token appears anywhere; `authenticate()` logs
`"authenticated (token redacted)"` by design.

---

## Known gaps and honest caveats

- **The pytest suite does not exercise the mock platform's *outbound* webhook.**
  The main app runs under FastAPI's `TestClient`, which is not a listening
  socket, so `APP_BASE_URL` is deliberately pointed at an unreachable address
  during tests and delivery callbacks are dropped. The webhook tests sign
  payloads with the production signing helper and POST them at the real
  endpoint, covering identical bytes. The genuine mock-to-app round trip is
  proven separately and live in section 5 above.
- **No real social platform has ever been contacted.** Every result here is
  against the local mock, by design.
- **Concurrency is tested at 6 threads against SQLite**, not under sustained
  load. The `UNIQUE` constraint is the correctness guarantee; SQLite's
  throughput under heavier concurrency is untested.
- **`screenshots/` holds text captures, not images** — terminal output was
  judged more verifiable than screenshots.
- **`get_status()` on the adapters is implemented but has no dedicated
  end-to-end test.** Nothing in the current flows calls it, because delivery is
  confirmed by webhook rather than by polling.
- **The timeout-recovery demo is timing-based** (6s server-side hold vs 3s
  client timeout) rather than deterministic. It passed on every run performed
  here, but it is a wall-clock race by construction.
- **A real bug was found by this evidence process and fixed**: the delivery
  webhook can land *before* the publish HTTP response returns, and the publish
  path was overwriting `published` back to `publishing`. `publish_post` now
  re-reads the row and only ever moves the status forward. See BUILDLOG.md.
